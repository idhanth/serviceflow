from __future__ import annotations

from fastapi import APIRouter

from serviceflow.api.v1 import auth, organizations

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
