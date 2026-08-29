from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr


class UserSummary(BaseModel):
    """The person behind a customer or employee record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    full_name: str
    phone: str | None = None
    avatar_url: str | None = None
