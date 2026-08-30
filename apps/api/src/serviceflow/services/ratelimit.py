"""Rate limiting on Redis (PRD 42).

A fixed-window counter, incremented and expired by one Lua script so the whole
check is a single atomic round trip. A Python dictionary would not survive a
second API process, and INCR-then-EXPIRE as two calls leaves a window where a
crash between them makes a key immortal.

Limits live in `LIMITS`, not scattered through route handlers, so the whole
policy is readable in one place.

**Outage policy is per class, not global.** Failing open everywhere would leave
signup unprotected the moment Redis blinks; failing closed everywhere would take
the product down for a dependency that is not needed to read a booking. So each
limiter says which it does, and the choice is made on what the endpoint protects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import redis

from serviceflow.core.config import get_settings
from serviceflow.core.errors import RateLimited

logger = logging.getLogger(__name__)

# INCR the window key, set its TTL on first use, return count and remaining TTL.
# One script, one round trip, no interleaving.
_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


@dataclass(frozen=True, slots=True)
class Limit:
    """One policy: how many, over how long, and what to do if Redis is gone."""

    name: str
    max_requests: int
    window_seconds: int
    # True  -> refuse when Redis is unavailable (abuse-sensitive, unauthenticated)
    # False -> allow when Redis is unavailable (authenticated, low blast radius)
    fail_closed: bool
    message: str


LIMITS: dict[str, Limit] = {
    # Unauthenticated and abuse-sensitive: an open signup endpoint is how you get
    # a database full of junk accounts, so this refuses rather than waves through.
    "signup": Limit(
        name="signup",
        max_requests=5,
        window_seconds=3600,
        fail_closed=True,
        message="Too many sign-up attempts. Please try again later.",
    ),
    "login": Limit(
        name="login",
        max_requests=10,
        window_seconds=900,
        fail_closed=True,
        message="Too many sign-in attempts. Please wait a few minutes and try again.",
    ),
    # Authenticated writes: a known user, and the damage from a brief lapse is
    # small, so availability wins.
    "booking_create": Limit(
        name="booking_create",
        max_requests=20,
        window_seconds=3600,
        fail_closed=False,
        message="You've made a lot of booking requests. Please try again shortly.",
    ),
    "photo_presign": Limit(
        name="photo_presign",
        max_requests=60,
        window_seconds=600,
        fail_closed=False,
        message="Too many uploads at once. Please wait a moment and try again.",
    ),
    "search": Limit(
        name="search",
        max_requests=120,
        window_seconds=60,
        fail_closed=False,
        message="You're searching very quickly. Please slow down a little.",
    ),
}


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    remaining: int
    retry_after: int


@lru_cache(maxsize=1)
def _client() -> redis.Redis[bytes]:
    return redis.Redis.from_url(
        str(get_settings().redis_url), socket_connect_timeout=1, socket_timeout=1
    )


def reset_client() -> None:
    """Test hook, for when settings change between cases."""
    _client.cache_clear()


def _key(limit: Limit, identity: str) -> str:
    return f"sf:rl:{limit.name}:{identity}"


def check(limit: Limit, identity: str) -> Decision:
    """Count one request against the limit. Never raises on a Redis failure."""
    try:
        # redis-py's eval() is untyped upstream; the shape is pinned by _SCRIPT.
        result: Any = _client().eval(  # type: ignore[no-untyped-call]
            _SCRIPT, 1, _key(limit, identity), limit.window_seconds
        )
        current, ttl = result[0], result[1]
    except Exception:
        logger.warning(
            "rate limiter unavailable; applying outage policy",
            extra={"limit": limit.name, "fail_closed": limit.fail_closed},
        )
        return Decision(
            allowed=not limit.fail_closed,
            remaining=0,
            retry_after=limit.window_seconds,
        )

    count = int(current)
    retry_after = int(ttl) if int(ttl) > 0 else limit.window_seconds
    return Decision(
        allowed=count <= limit.max_requests,
        remaining=max(limit.max_requests - count, 0),
        retry_after=retry_after,
    )


def enforce(limit_name: str, identity: str) -> None:
    """Apply a limit, raising RateLimited when it is exceeded.

    The error carries only a retry hint - never the Redis key, the identity, or
    how the limiter works.
    """
    limit = LIMITS[limit_name]
    decision = check(limit, identity)
    if decision.allowed:
        return

    logger.info(
        "rate limit exceeded",
        extra={"limit": limit.name, "retry_after": decision.retry_after},
    )
    raise RateLimited(limit.message, details={"retry_after": decision.retry_after})
