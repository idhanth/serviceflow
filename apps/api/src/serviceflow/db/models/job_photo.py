from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey
from serviceflow.db.models.enums import PhotoType
from serviceflow.db.models.mixins import OrganizationScoped

if TYPE_CHECKING:
    from serviceflow.db.models.job import Job
    from serviceflow.db.models.user import User

MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTOS_PER_JOB = 12


class JobPhoto(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """Metadata for one object in the media bucket (PRD 7, 15).

    A row exists only once the object has been verified present in storage, so a
    JobPhoto never advertises a photo that was not actually uploaded. The bytes
    live in S3; nothing here is served from the database.

    There is no visibility column, matching the PRD's field list: a job's photos
    are the record of work done on that customer's vehicle, and its own customer
    may see all of them. Internal remarks belong in an INTERNAL JobNote.
    See docs/adr-0005.
    """

    __tablename__ = "job_photos"
    __table_args__ = (
        # The bucket is shared across tenants, so a key must be unique globally.
        CheckConstraint("file_size > 0", name="file_size_positive"),
        CheckConstraint(f"file_size <= {MAX_PHOTO_BYTES}", name="file_size_within_limit"),
        CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png', 'image/webp')", name="mime_type_allowed"
        ),
        Index("ix_job_photos_job_id_photo_type", "job_id", "photo_type"),
        Index("ix_job_photos_job_id_created_at", "job_id", "created_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    photo_type: Mapped[PhotoType] = mapped_column(
        SAEnum(PhotoType, name="photo_type", native_enum=True), nullable=False
    )
    # Server-generated and never accepted from a client.
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(60), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    job: Mapped[Job] = relationship(back_populates="photos")
    uploader: Mapped[User] = relationship(lazy="joined")
