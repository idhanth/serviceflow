"""Unit tests for logic with no database or HTTP involved."""

from __future__ import annotations

import pytest

from serviceflow.core.pagination import PageParams
from serviceflow.schemas.envelope import paged
from serviceflow.services.search import like_pattern


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("tesla", "%tesla%"),
        ("  spaced  ", "%spaced%"),
        ("100%", r"%100\%%"),
        ("a_b", r"%a\_b%"),
        (r"back\slash", r"%back\\slash%"),
    ],
)
def test_like_pattern_escapes_wildcards(term: str, expected: str) -> None:
    assert like_pattern(term) == expected


@pytest.mark.parametrize(
    ("page", "page_size", "offset"),
    [(1, 25, 0), (2, 25, 25), (3, 10, 20)],
)
def test_page_offset(page: int, page_size: int, offset: int) -> None:
    assert PageParams(page=page, page_size=page_size).offset == offset


@pytest.mark.parametrize(
    ("total", "page_size", "pages"),
    [(0, 25, 0), (1, 25, 1), (25, 25, 1), (26, 25, 2), (100, 25, 4), (101, 25, 5)],
)
def test_page_count_rounds_up(total: int, page_size: int, pages: int) -> None:
    assert paged([], page=1, page_size=page_size, total=total).meta.pages == pages
