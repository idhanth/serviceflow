"""Email providers.

The PRD allows Resend, SendGrid or SES. No provider credentials existed on this
machine, so development delivers over real SMTP to MailPit - a genuine SMTP
server with an inspectable mailbox - rather than pretending a send succeeded.
Production sets `EMAIL_PROVIDER=resend` and an API key; nothing in the booking or
job code changes.

Every provider raises `EmailDeliveryError` and nothing else, so the Celery task
has one failure mode to retry on.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage as MimeMessage
from functools import lru_cache
from typing import Protocol

import httpx

from serviceflow.core.config import Settings, get_settings
from serviceflow.services.email.message import EmailMessage

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """The provider did not accept the message. Retryable unless stated."""

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        # A permanent failure (a rejected address) should not be retried forever.
        self.permanent = permanent


class EmailProvider(Protocol):
    name: str

    def send(self, message: EmailMessage) -> str:
        """Deliver, returning a provider message id. Raise EmailDeliveryError."""
        ...


class SmtpEmailProvider:
    """Development transport. Talks real SMTP; MailPit captures it."""

    name = "smtp"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, message: EmailMessage) -> str:
        mime = MimeMessage()
        mime["From"] = self._settings.email_from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        if message.html:
            mime.add_alternative(message.html, subtype="html")

        try:
            with smtplib.SMTP(
                self._settings.smtp_host,
                self._settings.smtp_port,
                timeout=self._settings.email_timeout_seconds,
            ) as client:
                if self._settings.smtp_use_tls:
                    client.starttls()
                if self._settings.smtp_username:
                    client.login(self._settings.smtp_username, self._settings.smtp_password or "")
                client.send_message(mime)
        except smtplib.SMTPRecipientsRefused as exc:
            # The address itself is bad; retrying will not help.
            raise EmailDeliveryError("Recipient refused.", permanent=True) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailDeliveryError(f"SMTP delivery failed: {type(exc).__name__}") from exc

        # SMTP has no useful id of its own; the Message-ID header is what exists.
        return str(mime.get("Message-ID") or "smtp")


class ResendEmailProvider:
    """Production transport. One HTTPS call per message."""

    name = "resend"
    endpoint = "https://api.resend.com/emails"

    def __init__(self, settings: Settings) -> None:
        if not settings.resend_api_key:
            raise ValueError("RESEND_API_KEY is required when EMAIL_PROVIDER=resend")
        self._settings = settings

    def send(self, message: EmailMessage) -> str:
        payload: dict[str, object] = {
            "from": self._settings.email_from,
            "to": [message.to],
            "subject": message.subject,
            "text": message.text,
        }
        if message.html:
            payload["html"] = message.html

        try:
            response = httpx.post(
                self.endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {self._settings.resend_api_key}"},
                timeout=self._settings.email_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise EmailDeliveryError(f"Could not reach the email provider: {exc}") from exc

        if response.status_code in (400, 422):
            # Malformed or rejected: retrying sends the same thing again.
            raise EmailDeliveryError(
                f"Provider rejected the message ({response.status_code}).", permanent=True
            )
        if response.status_code >= 300:
            raise EmailDeliveryError(f"Provider returned {response.status_code}.")

        body = response.json()
        return str(body.get("id", "resend"))


def build_email_provider(settings: Settings) -> EmailProvider:
    if settings.email_provider == "resend":
        return ResendEmailProvider(settings)
    if settings.is_production:
        raise RuntimeError("The SMTP development transport must not be used in production.")
    return SmtpEmailProvider(settings)


@lru_cache(maxsize=1)
def get_email_provider() -> EmailProvider:
    return build_email_provider(get_settings())


def reset_email_provider() -> None:
    """Test hook, for swapping providers between cases."""
    get_email_provider.cache_clear()
