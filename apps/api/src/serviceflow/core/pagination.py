"""Shared pagination for list endpoints (PRD 37, 45)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query

MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: Annotated[int, Query(ge=1, description="1-indexed page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


Pagination = Annotated[PageParams, Depends(page_params)]


@dataclass(frozen=True, slots=True)
class Page[T]:
    """A slice of results plus the total, ready for the response envelope."""

    items: list[T]
    total: int


@dataclass(frozen=True, slots=True)
class SortSpec:
    """A validated sort choice, resolved against a per-resource allowlist.

    Sort keys are never interpolated from user input into SQL; the request names
    one of a fixed set of options and the endpoint maps it to columns.
    """

    key: str
    descending: bool


def parse_sort(raw: str | None, *, allowed: frozenset[str], default: str) -> SortSpec:
    """Accepts "name" or "-name"; anything unknown falls back to the default."""
    candidate = (raw or default).strip()
    descending = candidate.startswith("-")
    key = candidate.lstrip("-")
    if key not in allowed:
        key, descending = default.lstrip("-"), default.startswith("-")
    return SortSpec(key=key, descending=descending)
