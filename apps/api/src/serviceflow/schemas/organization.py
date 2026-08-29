from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    email: EmailStr
    phone: str | None = None
    timezone: str
    address: str | None = None
    logo_url: str | None = None
