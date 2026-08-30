"""Global admin search (PRD 32)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from serviceflow.api.deps import AdminUser, DbSession
from serviceflow.schemas.envelope import DataResponse
from serviceflow.services import global_search

router = APIRouter(prefix="/search", tags=["search"])


class SearchResult(BaseModel):
    kind: str
    id: str
    title: str
    subtitle: str
    href: str


@router.get("", response_model=DataResponse[list[SearchResult]], summary="Search everything")
def search(
    current_user: AdminUser,
    db: DbSession,
    q: Annotated[str, Query(min_length=0, max_length=120)] = "",
) -> DataResponse[list[SearchResult]]:
    """Scoped to the caller's organization; a short term returns nothing."""
    hits = global_search.search(db, current_user.organization_id, q)
    return DataResponse[list[SearchResult]](
        data=[
            SearchResult(
                kind=hit.kind,
                id=str(hit.id),
                title=hit.title,
                subtitle=hit.subtitle,
                href=hit.href,
            )
            for hit in hits
        ]
    )
