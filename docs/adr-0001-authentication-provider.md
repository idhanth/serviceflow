# ADR 0001 - Authentication is provider-pluggable, defaulting to local tokens

Status: accepted
Date: 2026-08-29

## Context

The PRD prefers Clerk (or Supabase Auth) and says not to hand-roll password
infrastructure. Two constraints pull against adopting Clerk outright today:

1. Clerk needs a live account and API keys. Neither exists yet, so nothing
   authenticated could be built or tested until they do.
2. PRD 50 requires three demo logins a recruiter can click into immediately.
   Shared demo credentials are awkward to model in a hosted identity provider.

## Decision

Authentication sits behind an `AuthProvider` interface
(`apps/api/src/serviceflow/auth/provider.py`) with two implementations:

- `DevJWTAuthProvider` - self-issued HS256 tokens, Argon2 password hashes, and
  the seeded demo accounts. The default, and refused outright when
  `ENVIRONMENT=production`.
- `ClerkAuthProvider` - verifies Clerk session tokens against the instance JWKS.
  Selected by setting `AUTH_PROVIDER=clerk` plus `CLERK_JWKS_URL`.

Both yield the same `TokenPrincipal`, and `User.auth_provider_id` stores the
subject claim, so switching providers does not rewrite foreign keys.

Authorization is unaffected: roles live on `OrganizationMembership` and every
route is guarded in FastAPI regardless of who issued the token.

## Consequences

- The app is fully testable and demo-able now, with no third-party account.
- Switching to Clerk is configuration plus a re-keying of `auth_provider_id`,
  not a rewrite.
- The dev provider is a liability if it ever ships to production, so
  `build_auth_provider` raises rather than allowing it there.
