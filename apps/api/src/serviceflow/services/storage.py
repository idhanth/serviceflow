"""Object storage behind one interface (PRD 15, 41).

The same `S3ObjectStorage` talks to MinIO in development and AWS S3 in
production; only `s3_endpoint_url` and the credentials differ. No business logic
knows which is behind it.

Two properties matter more than the plumbing:

  * **The bucket is private.** Nothing is ever made world-readable to keep the
    UI simple. Reads go through short-lived presigned GETs.
  * **The size and type limits are enforced by the storage service**, not only by
    the API. A presigned POST carries a policy with `content-length-range` and an
    exact `Content-Type` condition, so a client that lies about either has its
    upload rejected by S3 itself. The API's own checks are the first gate, not
    the only one.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from serviceflow.core.config import Settings, get_settings
from serviceflow.core.errors import DependencyUnavailable, UploadFailed

logger = logging.getLogger(__name__)

# JPEG, PNG and WebP only (PRD 15). Anything else - including anything
# executable - has no extension mapping and is refused before it reaches S3.
ALLOWED_MIME_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    """A browser-usable POST target plus the fields its form must carry."""

    url: str
    fields: dict[str, str] = field(default_factory=dict)
    key: str = ""
    expires_in: int = 0


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int
    content_type: str


class ObjectStorage(Protocol):
    def build_key(
        self, *, organization_id: uuid.UUID, job_id: uuid.UUID, mime_type: str
    ) -> str: ...
    def presign_upload(self, *, key: str, mime_type: str, max_bytes: int) -> PresignedUpload: ...
    def presign_download(self, key: str) -> str: ...
    def head(self, key: str) -> StoredObject | None: ...
    def delete(self, key: str) -> None: ...


class S3ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            # SigV4 is required for presigned POST policies to be honoured.
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    # ------------------------------------------------------------- keys

    def build_key(self, *, organization_id: uuid.UUID, job_id: uuid.UUID, mime_type: str) -> str:
        """Server-generated, tenant-scoped, and unguessable.

        A client never supplies a key. The random component means one job's photo
        key cannot be derived from another's, and the organization prefix keeps
        objects sorted by tenant for lifecycle rules and audits.
        """
        extension = ALLOWED_MIME_TYPES[mime_type]
        return (
            f"organizations/{organization_id}/jobs/{job_id}/photos/{uuid.uuid4().hex}.{extension}"
        )

    def owns_key(self, key: str, *, organization_id: uuid.UUID, job_id: uuid.UUID) -> bool:
        """Guard against a stored key being used outside the scope it was minted for."""
        return key.startswith(f"organizations/{organization_id}/jobs/{job_id}/photos/")

    # ------------------------------------------------------------- operations

    def presign_upload(self, *, key: str, mime_type: str, max_bytes: int) -> PresignedUpload:
        try:
            presigned: dict[str, Any] = self._client.generate_presigned_post(
                Bucket=self._bucket,
                Key=key,
                Fields={"Content-Type": mime_type},
                Conditions=[
                    {"Content-Type": mime_type},
                    # Enforced by S3, so a client that understates its size fails.
                    ["content-length-range", 1, max_bytes],
                ],
                ExpiresIn=self._settings.s3_upload_ttl_seconds,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.exception("presign upload failed")
            raise DependencyUnavailable("Photo uploads are unavailable right now.") from exc

        return PresignedUpload(
            url=self._browser_url(presigned["url"]),
            fields={str(k): str(v) for k, v in presigned["fields"].items()},
            key=key,
            expires_in=self._settings.s3_upload_ttl_seconds,
        )

    def presign_download(self, key: str) -> str:
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=self._settings.s3_download_ttl_seconds,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.exception("presign download failed")
            raise DependencyUnavailable("Photos are unavailable right now.") from exc
        return self._browser_url(url)

    def head(self, key: str) -> StoredObject | None:
        """What is actually stored, or None. Used to verify a claimed upload."""
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            logger.exception("head object failed")
            raise DependencyUnavailable("Photo storage is unavailable right now.") from exc
        except BotoCoreError as exc:
            logger.exception("head object failed")
            raise DependencyUnavailable("Photo storage is unavailable right now.") from exc

        return StoredObject(
            key=key,
            size=int(response["ContentLength"]),
            content_type=str(response.get("ContentType", "application/octet-stream")),
        )

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            logger.exception("delete object failed", extra={"storage_key": key})
            raise UploadFailed("We couldn't remove that photo. Please try again.") from exc

    def put(self, *, key: str, body: bytes, mime_type: str) -> StoredObject:
        """Write an object directly.

        Used by the demo seed, which has no browser to hand a presigned POST to.
        Application code uploads through `presign_upload` instead - bytes never
        pass through the API in the normal flow.
        """
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=body, ContentType=mime_type)
        except (BotoCoreError, ClientError) as exc:
            logger.exception("put object failed", extra={"storage_key": key})
            raise UploadFailed("We couldn't store that file.") from exc
        return StoredObject(key=key, size=len(body), content_type=mime_type)

    def ensure_bucket(self) -> None:
        """Create the bucket if missing. Development convenience only."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    # ------------------------------------------------------------- helpers

    def _browser_url(self, url: str) -> str:
        """Rewrite the host when the browser reaches storage differently to the API."""
        public = self._settings.s3_public_endpoint_url
        internal = self._settings.s3_endpoint_url
        if public and internal and url.startswith(internal):
            return public.rstrip("/") + url[len(internal.rstrip("/")) :]
        return url


@lru_cache(maxsize=1)
def get_object_storage() -> S3ObjectStorage:
    return S3ObjectStorage(get_settings())


def reset_object_storage() -> None:
    """Test hook, for when settings change between cases."""
    get_object_storage.cache_clear()
