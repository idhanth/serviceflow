import { apiFetchData } from "@/lib/api-client";
import type { PhotoPresign, PhotoType } from "@/lib/types";

export const ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;
export const MAX_PHOTO_BYTES = 10 * 1024 * 1024;
export const MAX_PHOTOS_PER_JOB = 12;

/**
 * Client-side checks are a courtesy, not a boundary: the API validates on
 * presign, the signed S3 policy enforces the type and size ceiling, and the API
 * re-checks the stored object before writing any metadata. This just avoids a
 * pointless round trip.
 */
export function describeRejection(file: File): string | null {
  if (!(ALLOWED_IMAGE_TYPES as readonly string[]).includes(file.type)) {
    return `${file.name} isn't a JPEG, PNG or WebP image.`;
  }
  if (file.size > MAX_PHOTO_BYTES) {
    return `${file.name} is larger than 10 MB.`;
  }
  if (file.size === 0) {
    return `${file.name} is empty.`;
  }
  return null;
}

/** POSTs the form S3 asked for, reporting progress. XHR, because fetch cannot. */
function postToStorage(
  presign: PhotoPresign,
  file: File,
  onProgress: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const [key, value] of Object.entries(presign.fields)) form.append(key, value);
    // The file must be the last field; S3 ignores anything after it.
    form.append("file", file);

    const request = new XMLHttpRequest();
    request.open("POST", presign.url, true);
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress(100);
        resolve();
      } else {
        reject(new Error("Storage rejected the upload."));
      }
    });
    request.addEventListener("error", () => reject(new Error("The upload connection failed.")));
    request.addEventListener("abort", () => reject(new Error("The upload was cancelled.")));
    request.send(form);
  });
}

/**
 * presign -> upload straight to object storage -> finalize.
 * The bytes never pass through the API; only metadata does.
 */
export async function uploadJobPhoto({
  jobId,
  file,
  photoType,
  onProgress,
}: {
  jobId: string;
  file: File;
  photoType: PhotoType;
  onProgress: (percent: number) => void;
}): Promise<void> {
  const presign = await apiFetchData<PhotoPresign>(`jobs/${jobId}/photos/presign`, {
    method: "POST",
    body: JSON.stringify({ mime_type: file.type, file_size: file.size }),
  });

  await postToStorage(presign, file, onProgress);

  await apiFetchData(`jobs/${jobId}/photos`, {
    method: "POST",
    body: JSON.stringify({ storage_key: presign.storage_key, photo_type: photoType }),
  });
}
