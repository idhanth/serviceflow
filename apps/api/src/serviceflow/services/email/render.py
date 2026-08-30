"""Turning a Notification row into an email.

Only fields already vetted for the recipient are used: `subject` and `body` are
written by `services/notifications.py`, which never puts internal notes, tokens
or another tenant's data in them. Nothing here reads a JobNote or a job's
internal_notes.
"""

from __future__ import annotations

from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization
from serviceflow.services.email.message import EmailMessage


def _signature(organization: Organization) -> str:
    lines = [organization.name]
    if organization.phone:
        lines.append(organization.phone)
    if organization.address:
        lines.append(organization.address)
    return "\n".join(lines)


def render(
    notification: Notification,
    *,
    organization: Organization,
    recipient_email: str,
    recipient_name: str,
    app_url: str,
) -> EmailMessage:
    booking_id = (notification.payload or {}).get("booking_id")
    link = f"{app_url.rstrip('/')}/bookings/{booking_id}" if booking_id else app_url.rstrip("/")

    text = (
        f"Hi {recipient_name.split(' ')[0]},\n\n"
        f"{notification.body}\n\n"
        f"View it here: {link}\n\n"
        f"— {_signature(organization)}\n"
    )

    signature_html = _signature(organization).replace("\n", "<br>")
    html = (
        f"<p>Hi {recipient_name.split(' ')[0]},</p>"
        f"<p>{notification.body}</p>"
        f'<p><a href="{link}">View it in ServiceFlow</a></p>'
        f'<p style="color:#666;font-size:13px">{signature_html}</p>'
    )

    return EmailMessage(
        to=recipient_email,
        subject=f"{notification.subject} · {organization.name}",
        text=text,
        html=html,
    )
