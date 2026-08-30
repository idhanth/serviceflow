"""Notes and photos on a job."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from serviceflow.db.models.enums import NoteVisibility, PhotoType
from serviceflow.db.models.job_note import JobNote
from serviceflow.services.photos import PhotoView


class NoteRead(BaseModel):
    id: uuid.UUID
    content: str
    visibility: NoteVisibility
    author_name: str
    created_at: datetime

    @classmethod
    def from_model(cls, note: JobNote) -> NoteRead:
        return cls(
            id=note.id,
            content=note.content,
            visibility=note.visibility,
            author_name=note.author.full_name,
            created_at=note.created_at,
        )


class NoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    # Never defaulted: every write states who the note is for.
    visibility: NoteVisibility


class PhotoRead(BaseModel):
    id: uuid.UUID
    photo_type: PhotoType
    mime_type: str
    file_size: int
    uploaded_by_name: str
    created_at: datetime
    # Short-lived presigned GET. The bucket itself stays private.
    url: str

    @classmethod
    def from_view(cls, view: PhotoView) -> PhotoRead:
        photo = view.photo
        return cls(
            id=photo.id,
            photo_type=photo.photo_type,
            mime_type=photo.mime_type,
            file_size=photo.file_size,
            uploaded_by_name=photo.uploader.full_name,
            created_at=photo.created_at,
            url=view.url,
        )


class PhotoPresignRequest(BaseModel):
    """What the client declares. Everything is re-checked against the real object."""

    mime_type: str = Field(max_length=60)
    file_size: int = Field(gt=0)


class PhotoPresignResponse(BaseModel):
    url: str
    fields: dict[str, str]
    storage_key: str
    expires_in: int
    max_bytes: int


class PhotoFinalizeRequest(BaseModel):
    # Only ever a key this API minted; it is validated against the job's prefix.
    storage_key: str = Field(max_length=500)
    photo_type: PhotoType
