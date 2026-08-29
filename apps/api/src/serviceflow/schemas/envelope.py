"""Response envelopes (PRD 37)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PageMeta(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)


class DataResponse[T](BaseModel):
    data: T


class PagedResponse[T](BaseModel):
    data: list[T]
    meta: PageMeta


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict[str, object] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def paged[T](items: list[T], *, page: int, page_size: int, total: int) -> PagedResponse[T]:
    pages = (total + page_size - 1) // page_size if page_size else 0
    return PagedResponse[T](
        data=items,
        meta=PageMeta(page=page, page_size=page_size, total=total, pages=pages),
    )
