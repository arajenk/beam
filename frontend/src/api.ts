// ─────────────────────────────────────────────────────────────────────────────
// This module is the only place the UI touches the network.
//
// Uploads currently go through the API's POST /upload, so the server relays the
// bytes to R2. Presigned uploads will replace the body of uploadFile() later;
// the UI depends only on the types below.
// ─────────────────────────────────────────────────────────────────────────────

export type UploadProgress = { loaded: number; total: number };

export type UploadResult = { fileId: string; filename: string; size: number };

export type FileInfo = { fileId: string; filename: string; size: number };

export type UploadHandle = {
  promise: Promise<UploadResult>;
  cancel: () => void;
};

export class UploadError extends Error {
  readonly kind: "too-large" | "cancelled" | "failed";
  constructor(kind: UploadError["kind"], message: string) {
    super(message);
    this.kind = kind;
  }
}

export const MAX_SIZE = 10 * 1024 ** 3;

// Baked into the build by Vite, so it's public. Never put secrets in VITE_* vars.
const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** The link people share. Points at the frontend's download page. */
export function shareUrl(fileId: string): string {
  return `${window.location.origin}/f/${fileId}`;
}

/**
 * Upload one file, reporting progress. Cancel aborts it.
 * XHR rather than fetch, because fetch can't report upload progress.
 * Progress covers browser → API only; the API still has to send it on to R2.
 */
export function uploadFile(
  file: File,
  onProgress: (p: UploadProgress) => void,
): UploadHandle {
  if (file.size > MAX_SIZE) {
    return {
      promise: Promise.reject(new UploadError("too-large", "File is over 10 GB")),
      cancel: () => {},
    };
  }

  const xhr = new XMLHttpRequest();

  const promise = new Promise<UploadResult>((resolve, reject) => {
    xhr.upload.onprogress = (e) => {
      onProgress({ loaded: e.loaded, total: e.lengthComputable ? e.total : file.size });
    };
    xhr.onload = () => {
      if (xhr.status === 413) {
        reject(new UploadError("too-large", "File is over 10 GB"));
      } else if (xhr.status >= 200 && xhr.status < 300) {
        const body = JSON.parse(xhr.responseText) as { file_id: string; filename: string | null };
        resolve({ fileId: body.file_id, filename: body.filename ?? file.name, size: file.size });
      } else {
        reject(new UploadError("failed", `Upload failed (${xhr.status})`));
      }
    };
    // Network failures, and responses the browser hid because of CORS, both land here.
    xhr.onerror = () => reject(new UploadError("failed", "Upload failed"));
    xhr.onabort = () => reject(new UploadError("cancelled", "Upload cancelled"));

    const form = new FormData();
    form.append("file", file);
    xhr.open("POST", `${API_URL}/upload`);
    xhr.send(form);
  });

  return { promise, cancel: () => xhr.abort() };
}

/** Name and size for the download page. null means missing or expired. */
export async function getFileInfo(fileId: string): Promise<FileInfo | null> {
  const res = await fetch(`${API_URL}/f/${encodeURIComponent(fileId)}/info`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Info request failed (${res.status})`);
  const body = (await res.json()) as { file_id: string; filename: string; size: number };
  return { fileId: body.file_id, filename: body.filename, size: body.size };
}

/** Where the Download button sends the browser: the API redirects to a presigned R2 URL. */
export function downloadUrl(fileId: string): string {
  return `${API_URL}/f/${encodeURIComponent(fileId)}`;
}
