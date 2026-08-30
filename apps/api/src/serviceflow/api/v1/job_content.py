"""Notes and photos hanging off a job.

Mounted outside the /jobs router because customers reach these while having no
access to /jobs at all: they see their own job's photos and the notes marked for
them, through `resolve_job_for_viewer`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from serviceflow.api.deps import ActiveUser, DbSession
from serviceflow.db.models.job_photo import MAX_PHOTO_BYTES
from serviceflow.schemas.envelope import DataResponse
from serviceflow.schemas.job_content import (
    NoteCreate,
    NoteRead,
    PhotoFinalizeRequest,
    PhotoPresignRequest,
    PhotoPresignResponse,
    PhotoRead,
)
from serviceflow.services import notes as notes_service
from serviceflow.services import photos as photos_service

router = APIRouter(prefix="/jobs/{job_id}", tags=["job content"])


# ------------------------------------------------------------------ notes


@router.get("/notes", response_model=DataResponse[list[NoteRead]], summary="Notes on a job")
def list_notes(
    job_id: uuid.UUID, current_user: ActiveUser, db: DbSession
) -> DataResponse[list[NoteRead]]:
    """Staff see everything; a customer sees only CUSTOMER_VISIBLE notes."""
    rows = notes_service.list_notes(
        db,
        current_user.organization_id,
        job_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    return DataResponse[list[NoteRead]](data=[NoteRead.from_model(note) for note in rows])


@router.post(
    "/notes",
    response_model=DataResponse[NoteRead],
    status_code=status.HTTP_201_CREATED,
    summary="Add a note",
)
def create_note(
    job_id: uuid.UUID, payload: NoteCreate, current_user: ActiveUser, db: DbSession
) -> DataResponse[NoteRead]:
    note = notes_service.create_note(
        db,
        current_user.organization_id,
        job_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        content=payload.content,
        visibility=payload.visibility,
    )
    return DataResponse[NoteRead](data=NoteRead.from_model(note))


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a note")
def delete_note(
    job_id: uuid.UUID, note_id: uuid.UUID, current_user: ActiveUser, db: DbSession
) -> Response:
    notes_service.delete_note(
        db,
        current_user.organization_id,
        note_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ photos


@router.get("/photos", response_model=DataResponse[list[PhotoRead]], summary="Photos on a job")
def list_photos(
    job_id: uuid.UUID, current_user: ActiveUser, db: DbSession
) -> DataResponse[list[PhotoRead]]:
    views = photos_service.list_photos(
        db,
        current_user.organization_id,
        job_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    return DataResponse[list[PhotoRead]](data=[PhotoRead.from_view(view) for view in views])


@router.post(
    "/photos/presign",
    response_model=DataResponse[PhotoPresignResponse],
    summary="Request an upload slot",
)
def presign_photo(
    job_id: uuid.UUID, payload: PhotoPresignRequest, current_user: ActiveUser, db: DbSession
) -> DataResponse[PhotoPresignResponse]:
    """Returns a presigned POST. The storage key is minted here, never supplied."""
    presigned = photos_service.presign_upload(
        db,
        current_user.organization_id,
        job_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        mime_type=payload.mime_type,
        file_size=payload.file_size,
    )
    return DataResponse[PhotoPresignResponse](
        data=PhotoPresignResponse(
            url=presigned.url,
            fields=presigned.fields,
            storage_key=presigned.key,
            expires_in=presigned.expires_in,
            max_bytes=MAX_PHOTO_BYTES,
        )
    )


@router.post(
    "/photos",
    response_model=DataResponse[PhotoRead],
    status_code=status.HTTP_201_CREATED,
    summary="Confirm an upload landed",
)
def finalize_photo(
    job_id: uuid.UUID, payload: PhotoFinalizeRequest, current_user: ActiveUser, db: DbSession
) -> DataResponse[PhotoRead]:
    """Verifies the object exists and matches before any metadata is written."""
    view = photos_service.finalize_upload(
        db,
        current_user.organization_id,
        job_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        storage_key=payload.storage_key,
        photo_type=payload.photo_type,
    )
    return DataResponse[PhotoRead](data=PhotoRead.from_view(view))


@router.delete(
    "/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a photo"
)
def delete_photo(
    job_id: uuid.UUID, photo_id: uuid.UUID, current_user: ActiveUser, db: DbSession
) -> Response:
    photos_service.delete_photo(
        db,
        current_user.organization_id,
        photo_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
