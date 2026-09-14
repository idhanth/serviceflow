"""Tenant context for PostgreSQL row level security.

Every tenant-owned table has RLS enabled *and forced* (see the
`tenant_integrity_and_row_level_security` migration), with one policy:

    organization_id = current_setting('app.organization_id')::uuid
    OR current_setting('app.rls_bypass') = 'on'

So a query that forgets its `WHERE organization_id = ...` does not leak another
tenant's rows - it returns nothing, and an insert that names the wrong tenant is
refused by the policy's WITH CHECK.

How the setting gets there
--------------------------
Both values are *transaction-local* (`set_config(..., true)`), so a pooled
connection can never carry one request's tenant into the next. The session
remembers the tenant in `session.info`, and the `after_begin` listener below
re-applies it at the start of every transaction the session opens - including
the ones that begin after a service calls `commit()`.

`bind_tenant` is called exactly once per request, by `api.deps.get_current_user`,
with the organization derived from the caller's verified membership. Nothing
reads a tenant id from a request body.

The bypass exists for work that is cross-tenant by nature: the Celery outbox
sweep, reminders across every business, seeds and migrations. It is set only
by `db.session.session_scope()` and by the test fixtures, never on a request
path.

What this is and is not
-----------------------
RLS here is a backstop against a *missing filter in application code*. It is
not a boundary against someone who can already run arbitrary SQL as the
application role - such a caller could set the bypass themselves. Parameterized
queries are what keep untrusted input from ever becoming SQL.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, SessionTransaction

TENANT_KEY = "serviceflow.organization_id"
BYPASS_KEY = "serviceflow.rls_bypass"

_APPLY = text(
    "SELECT set_config('app.organization_id', :organization_id, true),"
    " set_config('app.rls_bypass', :bypass, true)"
)


def bind_tenant(session: Session, organization_id: uuid.UUID) -> None:
    """Scope every following statement on this session to one organization."""
    session.info[TENANT_KEY] = str(organization_id)
    session.info.pop(BYPASS_KEY, None)
    if session.in_transaction():
        session.execute(_APPLY, {"organization_id": str(organization_id), "bypass": "off"})


def allow_cross_tenant(session: Session) -> None:
    """For system work only: background jobs, seeds, migrations and test fixtures."""
    session.info[BYPASS_KEY] = True
    if session.in_transaction():
        session.execute(
            _APPLY,
            {"organization_id": session.info.get(TENANT_KEY, ""), "bypass": "on"},
        )


def current_tenant(session: Session) -> str | None:
    value: Any = session.info.get(TENANT_KEY)
    return str(value) if value else None


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    # Both settings are transaction-local, so a new transaction already starts
    # with no tenant and no bypass - which is the fail-closed state. Only a
    # session that has been given one needs the round trip.
    if not session.info.get(TENANT_KEY) and not session.info.get(BYPASS_KEY):
        return
    connection.execute(
        _APPLY,
        {
            "organization_id": session.info.get(TENANT_KEY, ""),
            "bypass": "on" if session.info.get(BYPASS_KEY) else "off",
        },
    )
