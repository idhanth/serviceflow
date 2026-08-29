"""Search helpers shared by list endpoints."""

from __future__ import annotations


def like_pattern(term: str) -> str:
    """Build a safe ILIKE pattern.

    Escapes the wildcards so a user searching for "50%" or "a_b" gets a literal
    match instead of an accidental wildcard. Pair with `.ilike(pattern)`;
    SQLAlchemy's default escape character is backslash.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.strip()}%"
