"""Global search for staff with tenant-wide read access."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from serviceflow.api.deps import DbSession, Searcher, rate_limit_user
from serviceflow.schemas.envelope import DataResponse
from serviceflow.services import global_search

router = APIRouter(prefix="/search", tags=["search"])


class SearchResult(BaseModel):
    kind: str
    id: str
    title: str
    subtitle: str
    href: str


@router.get(
    "",
    response_model=DataResponse[list[SearchResult]],
    summary="Search everything",
    dependencies=[Depends(rate_limit_user("search"))],
)
def search(
    current_user: Searcher,
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
