# ADR 0005 - Object storage, presigned uploads, and in-app notifications

Status: accepted
Date: 2026-08-30

## 1. Storage provider

No AWS credentials existed on the build machine, so development runs **MinIO**, a
user-local S3-compatible server (`~/.local/opt/minio`), started by
`scripts/services.sh` alongside PostgreSQL and Redis.

Production changes two settings and nothing else:

| Setting | Development | Production (AWS S3) |
| --- | --- | --- |
| `S3_ENDPOINT_URL` | `http://127.0.0.1:9000` | *unset* — boto3 resolves AWS |
| credentials | local MinIO root user | IAM role or access key |
| `S3_BUCKET` | `serviceflow-media` | the real bucket |

One `S3ObjectStorage` class serves both. It is the only thing in the codebase
that knows S3 exists; `services/photos.py` talks to the `ObjectStorage`
protocol, so swapping to GCS or R2 would mean one new class and no changes to
business logic.

The MinIO development credentials are committed in `scripts/env.sh` and
`.env.example`. That is deliberate and matches how the PostgreSQL development
password already sits in `docker-compose.yml`: they are local-only fixtures with
no value outside a developer's own machine. `.env` remains gitignored, and
production credentials only ever come from the environment.

## 2. The presign flow

```
  employee                API                     object storage
     |  POST /photos/presign |                            |
     |---------------------->| authorize, validate,       |
     |                       | mint key, sign a POST      |
     |<----------------------| url + policy fields        |
     |                                                    |
     |  multipart POST (the bytes never touch the API)    |
     |--------------------------------------------------->|
     |                                                    |
     |  POST /photos {storage_key, photo_type}            |
     |---------------------->| HEAD the object            |
     |                       |--------------------------->|
     |                       | size + type verified,      |
     |<----------------------| only then INSERT JobPhoto  |
```

**Presigned POST, not PUT.** A POST policy can carry conditions, so the signed
document itself pins the `Content-Type` and a `content-length-range` of
1–10 MB. A client that lies about its size at presign still cannot upload the
bytes: S3 rejects the request. With a presigned PUT the ceiling would exist only
in application code. There is a test that uploads an oversized body and asserts
storage refuses it.

**Metadata is written only after verification.** `finalize_upload` HEADs the
object and takes the size and content type *from what is actually stored*, never
from the client's claim. If the object is absent the request fails with
`UPLOAD_FAILED` and no row is created — so a `JobPhoto` can never advertise a
photo that was not uploaded.

## 3. Object keys

```
organizations/{organization_id}/jobs/{job_id}/photos/{random-hex}.{ext}
```

Generated server-side, always. A client never supplies a key, and `finalize`
re-checks that any key it is handed starts with the prefix for *this*
organization and *this* job — so a key minted for one job cannot be redeemed
against another, and traversal attempts (`organizations/../..`) are refused. The
random component means one job's keys cannot be derived from another's.

The extension comes from a fixed MIME allowlist (JPEG, PNG, WebP); anything else
has no mapping and is refused before a key is minted. There is no code path that
writes an executable.

## 4. Reads: the bucket stays private

Nothing is made world-readable. `GET /jobs/{id}/photos` authorizes the caller,
then returns a **short-lived presigned GET** per photo (15 minutes). Making the
bucket public would have been simpler for the UI and would have meant every
photo URL was permanently, anonymously accessible.

## 5. Photo visibility

The PRD's `JobPhoto` field list has no `visibility` column, unlike `JobNote`.
Rather than invent one, phase 5 takes the simplest reading: **a job's photos are
visible to that job's own customer**, and to staff. They are the record of work
done on that customer's vehicle, which is what PRD 62 shows the customer at the
end of the flow.

Anything not meant for the customer belongs in an `INTERNAL` `JobNote`, which
does have a visibility column and is filtered in exactly one place. If per-photo
visibility is ever needed, it is an additive column plus one filter in
`list_photos` — the authorization boundary is already in the right place.

## 6. Failure and cleanup

| Situation | Behaviour |
| --- | --- |
| Upload never happens | `finalize` HEADs, finds nothing, returns `UPLOAD_FAILED`. No row. |
| Upload lands but is the wrong type or size | Object is deleted, request rejected. |
| Twelve-photo limit reached between presign and finalize | Object deleted, request rejected. |
| Same key finalized twice | Unique constraint on `storage_key`; second attempt is a clean 422. |
| Presigned slot never used | An unreferenced object. Swept by a bucket lifecycle rule in production. |
| Photo deleted | Row first, then object. If the object delete fails it is logged and left — an orphaned object is recoverable, a row pointing at missing bytes is not. |

## 7. Notifications

`Notification` rows are created by `services/notifications.enqueue`, which
**adds to the caller's session and never commits**. The row is therefore written
inside the transaction of the event it describes: if a booking confirmation rolls
back, so does the "your booking is confirmed" notification. There is a test that
forces a mid-transaction failure and asserts no notification survives.

Phase 5 writes `IN_APP` rows only, and they land `PENDING` — which is what the
unread badge counts. Opening one moves it to `READ`.

### The phase 6 seam

`enqueue` already accepts a list of channels and writes one row per channel.
`channel`, `sent_at` and `failed_at` all exist now. Adding email in phase 6 means:

1. passing `EMAIL` alongside `IN_APP` at the call sites;
2. a Celery task that picks up `PENDING` + `EMAIL` rows, sends them, and sets
   `sent_at` or `failed_at`;
3. the same `enqueue` call for `APPOINTMENT_REMINDER`, which is already written
   and simply has no scheduler yet.

No booking or job logic changes, and no migration.

## 8. Search

Plain PostgreSQL `ILIKE` across indexed columns, capped at five hits per record
type (`services/global_search.py`). At this application's scale — hundreds of
customers, thousands of bookings — that is fast and exactly predictable.
Elasticsearch would add an index to keep in sync, a service to operate and a
relevance model to explain, for a problem that does not exist here. Every query
is organization-filtered; a test asserts results never cross tenants.

## 9. What phase 5 deliberately did not build

Celery workers, email delivery, the appointment-reminder scheduler, SSE or
WebSockets, and realtime dashboard updates. The notification badge polls once a
minute; phase 6 replaces that poll with a push and leaves everything else alone.
