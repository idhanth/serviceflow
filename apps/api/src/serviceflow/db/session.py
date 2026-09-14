"""Engine and session lifecycle."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from serviceflow.core.config import get_settings
from serviceflow.db.tenancy import allow_cross_tenant

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
# Sync routes run on a thread pool, so the first burst of requests after startup
# reaches these lazy initialisers concurrently. Without the lock several threads
# each build an engine - each with its own pool - and the process opens more
# connections than the pool settings allow. Found by the load test, which saw
# more PostgreSQL connections than workers x (pool_size + max_overflow).
_init_lock = threading.Lock()


def get_engine() -> Engine:
    global _engine
    if _engine is not None:
        return _engine
    with _init_lock:
        if _engine is not None:
            return _engine
        settings = get_settings()
        _engine = create_engine(
            str(settings.database_url),
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            # Wait briefly for a connection, then give up. SQLAlchemy's default
            # is 30 seconds, which under saturation holds a worker thread for
            # half a minute per waiting request - the server starves itself of
            # threads and throughput collapses rather than degrading. Failing
            # fast frees the thread and lets the caller be told to retry.
            pool_timeout=settings.database_pool_timeout,
            pool_recycle=settings.database_pool_recycle,
            pool_pre_ping=True,
            # Timestamps leave the API in UTC whatever the server's own TimeZone
            # setting is. Without this a server configured for local time hands
            # back local offsets, and the same instant serialises as "-04:00"
            # on one machine and "Z" on another. Business-timezone conversion
            # happens explicitly in the service layer, never in the session.
            connect_args={"options": "-c timezone=UTC"},
            echo=settings.database_echo,
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is not None:
        return _session_factory
    engine = get_engine()
    with _init_lock:
        if _session_factory is None:
            _session_factory = sessionmaker(
                bind=engine, autoflush=False, expire_on_commit=False, future=True
            )
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background jobs, seeds and scripts.

    These sessions work across tenants by nature - the outbox sweep delivers
    every business's email - so they are the one place row level security is
    bypassed (see db/tenancy.py). Request handlers never use this.
    """
    session = get_session_factory()()
    allow_cross_tenant(session)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Test hook: drop cached engine/session factory so settings can change."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
