// ─────────────────────────────────────────────────────────────────────────────
// This module is the only place the UI touches the network.
//
// Uploads are presigned multipart: the API starts the upload and signs one URL
// per part, the browser PUTs the parts straight to R2, then the API checks
// them and completes. File bytes never pass through the API.
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

const PARALLEL_PARTS = 4;
const PART_ATTEMPTS = 3;

type StartResponse = { file_id: string; upload_id: string; part_size: number; part_urls: string[] };
type CompletedPart = { part_number: number; etag: string };

/**
 * Upload one file, reporting progress. Cancel aborts it.
 * Parts go up in parallel over XHR (fetch can't report upload progress).
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

  const active = new Set<XMLHttpRequest>();
  let cancelled = false;
  // Set on cancel or on the first failure, so the other parts stop too.
  let stopped = false;
  const isStopped = () => stopped;
  let upload: { fileId: string; uploadId: string } | null = null;

  const abortUrl = () =>
    upload &&
    `${API_URL}/uploads/${encodeURIComponent(upload.fileId)}/abort?upload_id=${encodeURIComponent(upload.uploadId)}`;

  // Tell the API to discard the parts. Best-effort: R2's 7-day abort rule is the backstop.
  const abortOnServer = () => {
    const url = abortUrl();
    if (url) fetch(url, { method: "POST", keepalive: true }).catch(() => {});
  };

  // Closing the tab can't run normal requests, so hand the browser a beacon instead.
  const onPageHide = () => {
    const url = abortUrl();
    if (url) navigator.sendBeacon(url);
  };
  const onBeforeUnload = (e: BeforeUnloadEvent) => e.preventDefault();
  window.addEventListener("pagehide", onPageHide);
  window.addEventListener("beforeunload", onBeforeUnload);
  const stopListening = () => {
    window.removeEventListener("pagehide", onPageHide);
    window.removeEventListener("beforeunload", onBeforeUnload);
  };

  const run = async (): Promise<UploadResult> => {
    const start = await postJson<StartResponse>("/uploads", {
      filename: file.name,
      size: file.size,
      content_type: file.type || "application/octet-stream",
    });
    upload = { fileId: start.file_id, uploadId: start.upload_id };
    if (cancelled) throw new UploadError("cancelled", "Upload cancelled");

    // Bytes sent per part; summed for the progress bar. Reset when a part retries.
    const sent = new Array<number>(start.part_urls.length).fill(0);
    const report = () => onProgress({ loaded: sent.reduce((a, b) => a + b, 0), total: file.size });

    const completed: CompletedPart[] = [];
    let next = 0;
    const worker = async () => {
      while (next < start.part_urls.length && !stopped) {
        const i = next++;
        const blob = file.slice(i * start.part_size, (i + 1) * start.part_size);
        const etag = await putPartWithRetry(start.part_urls[i], blob, active, isStopped, (loaded) => {
          sent[i] = loaded;
          report();
        });
        completed.push({ part_number: i + 1, etag });
      }
    };
    await Promise.all(Array.from({ length: PARALLEL_PARTS }, worker));
    if (stopped) throw new UploadError("cancelled", "Upload cancelled");

    completed.sort((a, b) => a.part_number - b.part_number);
    await postJson(`/uploads/${encodeURIComponent(start.file_id)}/complete`, {
      upload_id: start.upload_id,
      parts: completed,
    });
    return { fileId: start.file_id, filename: file.name, size: file.size };
  };

  const promise = run()
    .catch((err: unknown) => {
      stopped = true;
      for (const xhr of active) xhr.abort();
      // runs once for both cancel and failure, after the upload id is known
      abortOnServer();
      if (cancelled) throw new UploadError("cancelled", "Upload cancelled");
      throw err instanceof UploadError ? err : new UploadError("failed", "Upload failed");
    })
    .finally(stopListening);

  return {
    promise,
    cancel: () => {
      if (cancelled) return;
      cancelled = true;
      stopped = true;
      for (const xhr of active) xhr.abort();
    },
  };
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 413) throw new UploadError("too-large", "File is over 10 GB");
  if (!res.ok) throw new UploadError("failed", `Request failed (${res.status})`);
  return (await res.json()) as T;
}

async function putPartWithRetry(
  url: string,
  blob: Blob,
  active: Set<XMLHttpRequest>,
  isStopped: () => boolean,
  onSent: (loaded: number) => void,
): Promise<string> {
  for (let attempt = 1; ; attempt++) {
    if (isStopped()) throw new UploadError("cancelled", "Upload cancelled");
    try {
      return await putPart(url, blob, active, onSent);
    } catch (err) {
      onSent(0);
      const aborted = err instanceof UploadError && err.kind === "cancelled";
      if (aborted || attempt >= PART_ATTEMPTS) throw err;
      await new Promise((r) => setTimeout(r, 1000 * attempt));
    }
  }
}

/** PUT one part to its presigned R2 URL and return the ETag R2 sends back. */
function putPart(
  url: string,
  blob: Blob,
  active: Set<XMLHttpRequest>,
  onSent: (loaded: number) => void,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    active.add(xhr);
    const done = () => active.delete(xhr);
    xhr.upload.onprogress = (e) => onSent(e.loaded);
    xhr.onload = () => {
      done();
      // null here usually means the bucket's CORS policy doesn't expose ETag
      const etag = xhr.getResponseHeader("ETag");
      if (xhr.status >= 200 && xhr.status < 300 && etag) resolve(etag);
      else reject(new UploadError("failed", `Part upload failed (${xhr.status})`));
    };
    xhr.onerror = () => {
      done();
      reject(new UploadError("failed", "Part upload failed"));
    };
    xhr.onabort = () => {
      done();
      reject(new UploadError("cancelled", "Upload cancelled"));
    };
    xhr.open("PUT", url);
    xhr.send(blob);
  });
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
