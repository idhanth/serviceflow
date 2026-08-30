from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey
from serviceflow.db.models.enums import NoteVisibility
from serviceflow.db.models.mixins import OrganizationScoped

if TYPE_CHECKING:
    from serviceflow.db.models.job import Job
    from serviceflow.db.models.user import User


class JobNote(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """A note against a job (PRD 7).

    `visibility` is the only thing standing between an internal remark and the
    customer, so it is never defaulted implicitly: every write states it.
    """

    __tablename__ = "job_notes"
    __table_args__ = (
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        Index("ix_job_notes_job_id_created_at", "job_id", "created_at"),
        Index("ix_job_notes_job_id_visibility", "job_id", "visibility"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # RESTRICT: a note must always be attributable to whoever wrote it.
    author_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[NoteVisibility] = mapped_column(
        SAEnum(NoteVisibility, name="note_visibility", native_enum=True), nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="notes")
    author: Mapped[User] = relationship(lazy="joined")

    @property
    def customer_visible(self) -> bool:
        return self.visibility is NoteVisibility.CUSTOMER_VISIBLE
