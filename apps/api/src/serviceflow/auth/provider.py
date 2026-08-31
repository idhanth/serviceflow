"""Pluggable authentication providers.

The PRD prefers Clerk. Clerk needs an account and live API keys, which the demo
accounts in PRD 50 also have to work without, so authentication sits behind this
interface: `dev` (self-issued HS256 tokens, seeded demo logins) is the default and
`clerk` (JWKS verification) activates as soon as CLERK_SECRET_KEY is configured.
Authorization is enforced in FastAPI either way (PRD 6).
"""

from __future__ import annotations

import time
from typing import Any, Protocol

import httpx
import jwt
from jwt import PyJWKClient

from serviceflow.auth.principal import TokenPrincipal
from serviceflow.core.config import Settings
from serviceflow.core.errors import Unauthorized


class AuthProvider(Protocol):
    def verify_token(self, token: str) -> TokenPrincipal: ...


class DevJWTAuthProvider:
    """Self-issued tokens. Local/demo only - never enable in production."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def issue_token(self, subject: str, *, email: str, ttl_seconds: int | None = None) -> str:
        now = int(time.time())
        ttl = ttl_seconds or self._settings.access_token_ttl_seconds
        payload: dict[str, Any] = {
            "sub": subject,
            "email": email,
            "iat": now,
            "exp": now + ttl,
            "iss": "serviceflow-dev",
        }
        return jwt.encode(
            payload, self._settings.jwt_secret, algorithm=self._settings.jwt_algorithm
        )

    def verify_token(self, token: str) -> TokenPrincipal:
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=[self._settings.jwt_algorithm],
                issuer="serviceflow-dev",
            )
        except jwt.ExpiredSignatureError as exc:
            raise Unauthorized("Your session has expired. Please sign in again.") from exc
        except jwt.PyJWTError as exc:
            raise Unauthorized() from exc
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise Unauthorized()
        email = payload.get("email")
        return TokenPrincipal(
            auth_provider_id=subject, email=email if isinstance(email, str) else None
        )


class ClerkAuthProvider:
    """Verifies Clerk session tokens against the instance JWKS."""

    def __init__(self, settings: Settings) -> None:
        if not settings.clerk_jwks_url:
            raise ValueError("CLERK_JWKS_URL is required when AUTH_PROVIDER=clerk")
        self._settings = settings
        self._jwk_client = PyJWKClient(settings.clerk_jwks_url, cache_keys=True)

    def verify_token(self, token: str) -> TokenPrincipal:
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except (jwt.PyJWTError, httpx.HTTPError) as exc:
            raise Unauthorized() from exc
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise Unauthorized()
        email = payload.get("email")
        return TokenPrincipal(
            auth_provider_id=subject, email=email if isinstance(email, str) else None
        )


def build_auth_provider(settings: Settings) -> AuthProvider:
    """Pick the provider, refusing the local one in production by default.

    The guard stays: shipping local token issuance to production by accident is
    exactly the mistake it exists to prevent. A public demo is not an accident,
    so it has to say so - `PUBLIC_DEMO_MODE=true` - and that decision is then
    visible in the environment and in the startup log.
    """
    if settings.auth_provider == "clerk":
        return ClerkAuthProvider(settings)
    if settings.is_production and not settings.public_demo_mode:
        raise RuntimeError(
            "The dev auth provider must not be used in production. Set AUTH_PROVIDER=clerk, "
            "or PUBLIC_DEMO_MODE=true if this deployment is a deliberately public demo."
        )
    return DevJWTAuthProvider(settings)
