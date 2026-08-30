from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """What every provider is given. Deliberately plain - no provider types leak."""

    to: str
    subject: str
    text: str
    html: str | None = None
