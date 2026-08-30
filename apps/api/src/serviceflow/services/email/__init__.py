"""Email delivery, behind one provider-agnostic interface."""

from serviceflow.services.email.message import EmailMessage
from serviceflow.services.email.provider import (
    EmailDeliveryError,
    EmailProvider,
    get_email_provider,
    reset_email_provider,
)

__all__ = [
    "EmailDeliveryError",
    "EmailMessage",
    "EmailProvider",
    "get_email_provider",
    "reset_email_provider",
]
