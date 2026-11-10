// ─────────────────────────────────────────────────────────────────────────────
// This module is the only place the UI touches the network.
//
// A share is up to 10 files, 10 GB in total. One start call declares them all
// and the API signs every part; the browser PUTs the parts straight to R2, one
// file after another, and the API checks and completes each file. File bytes
// never pass through the API.
// ─────────────────────────────────────────────────────────────────────────────

export class UploadError extends Error {
  readonly kind: "too-large" | "limit" | "verification" | "cancelled" | "failed";
  /** The API's HTTP status, when the API answered. */
  readonly status?: number;
  constructor(kind: UploadError["kind"], message: string, status?: number) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

export const MAX_FILES = 10;
export const MAX_SIZE = 10 * 1024 ** 3;

// Baked into the build by Vite, so it's public. Never put secrets in VITE_* vars.
const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** The link people share. Points at the frontend's share page. */
export function shareUrl(shareId: string): string {
  return `${window.location.origin}/f/${shareId}`;
}

/** Why these files can't be one share, or null if they can. The API checks again. */
export function checkShare(files: { size: number }[]): string | null {
  if (files.length > MAX_FILES) return `Beam sends up to ${MAX_FILES} files at a time.`;
  const total = files.reduce((sum, f) => sum + f.size, 0);
  if (total > MAX_SIZE) return "Beam sends up to 10 GB at a time.";
  return null;
}

export type FileStatus = "queued" | "uploading" | "done" | "failed" | "cancelled";
export type FileState = { index: number; filename: string; size: number; loaded: number; status: FileStatus };
export type SharedFile = { index: number; filename: string; size: number };

export type ShareHandle = {
  /** Resolves once the API has accepted the share; rejects (UploadError) if it refused it. */
  started: Promise<{ shareId: string; files: SharedFile[] }>;
  /** Stops one file; the others carry on. */
  cancel: (index: number) => void;
  cancelAll: () => void;
  /** Re-sends a failed file's missing parts with the URLs it was already signed. */
  retry: (index: number) => void;
  /** Discards every unfinished file and stops listening for the tab closing. */
  dispose: () => void;
};

const PARALLEL_PARTS = 4;
const PART_ATTEMPTS = 3;

// The browser can't tell slow from dead, so: a part fails if no bytes move for
// STALL_MS, or if R2 hasn't replied REPLY_MS after the last byte went out.
// API calls have tiny bodies (no progress to watch), so they get a deadline.
const STALL_MS = 30_000;
const REPLY_MS = 30_000;
const API_MS = 20_000;
// complete makes the API call R2 twice, and joining many parts can take seconds
const COMPLETE_MS = 60_000;

type StartResponse = {
  share_id: string;
  part_size: number;
  files: { index: number; filename: string; upload_id: string; part_urls: string[] }[];
};

type Job = {
  uploadId: string;
  partUrls: string[];
  // R2's ETag per part once it's in; a retry only sends the nulls
  etags: (string | null)[];
  sent: number[];
  active: Set<XMLHttpRequest>;
  stopped: boolean;
};

const enc = encodeURIComponent;

/**
 * Upload files as one share. `onChange` gets every file's state on each change.
 * Files go one after another (so finished files are safe sooner); each file's
 * parts go up 4 at a time over XHR (fetch can't report upload progress).
 * `getToken` supplies an unused Turnstile token, which the API checks before starting.
 */
export function startShare(
  files: File[],
  onChange: (states: FileState[]) => void,
  getToken: () => Promise<string>,
): ShareHandle {
  const states: FileState[] = files.map((f, index) => ({
    index,
    filename: f.name,
    size: f.size,
    loaded: 0,
    status: "queued",
  }));
  const emit = () => onChange(states.map((s) => ({ ...s })));
  const jobs: Job[] = [];
  let shareId: string | null = null;
  let partSize = 0;
  const queue: number[] = [];
  let pumping = false;

  const abortUrl = (index: number) =>
    `${API_URL}/uploads/${enc(shareId!)}/${index}/abort?upload_id=${enc(jobs[index].uploadId)}`;
  // Tell the API to discard a file's parts. Best-effort: the API's sweeper is the backstop.
  const abortOnServer = (index: number) => {
    if (shareId && jobs[index]) fetch(abortUrl(index), { method: "POST", keepalive: true }).catch(() => {});
  };
  const unfinished = () => states.filter((s) => s.status !== "done" && s.status !== "cancelled");
  const stopJob = (index: number) => {
    const job = jobs[index];
    if (!job) return;
    job.stopped = true;
    for (const xhr of job.active) xhr.abort();
  };

  // Closing the tab can't run normal requests, so hand the browser beacons instead.
  const onPageHide = () => {
    if (!shareId) return;
    for (const s of unfinished()) if (jobs[s.index]) navigator.sendBeacon(abortUrl(s.index));
  };
  const onBeforeUnload = (e: BeforeUnloadEvent) => {
    if (states.some((s) => s.status === "queued" || s.status === "uploading")) e.preventDefault();
  };
  window.addEventListener("pagehide", onPageHide);
  window.addEventListener("beforeunload", onBeforeUnload);
  const stopListening = () => {
    window.removeEventListener("pagehide", onPageHide);
    window.removeEventListener("beforeunload", onBeforeUnload);
  };

  const uploadOne = async (index: number) => {
    const job = jobs[index];
    const state = states[index];
    job.stopped = false;
    state.status = "uploading";
    emit();
    try {
      const missing = job.etags.flatMap((etag, p) => (etag ? [] : [p]));
      let next = 0;
      const worker = async () => {
        while (next < missing.length && !job.stopped) {
          const p = missing[next++];
          const blob = files[index].slice(p * partSize, (p + 1) * partSize);
          job.etags[p] = await putPartWithRetry(job.partUrls[p], blob, job.active, () => job.stopped, (loaded) => {
            job.sent[p] = loaded;
            state.loaded = job.sent.reduce((a, b) => a + b, 0);
            emit();
          });
        }
      };
      await Promise.all(Array.from({ length: PARALLEL_PARTS }, worker));
      if (job.stopped) throw new UploadError("cancelled", "Upload cancelled");

      try {
        await postJson(
          `/uploads/${enc(shareId!)}/${index}/complete`,
          { upload_id: job.uploadId, parts: job.etags.map((etag, p) => ({ part_number: p + 1, etag })) },
          COMPLETE_MS,
        );
      } catch (err) {
        // A 404 can mean an earlier complete worked but its reply was lost:
        // the upload is gone because it became the file. The listing knows.
        if (!(err instanceof UploadError && err.status === 404)) throw err;
        const info = await getShareInfo(shareId!).catch(() => null);
        if (!info?.files.some((f) => f.index === index)) throw err;
      }
      state.status = "done";
      state.loaded = state.size;
    } catch {
      stopJob(index);
      // cancel() already set "cancelled" and told the API; anything else can be retried
      // (re-read: cancel() can change it while this upload is awaiting)
      if ((state.status as FileStatus) !== "cancelled") state.status = "failed";
    }
    emit();
  };

  // One file at a time, in order, including files queued again by retry.
  const pump = async () => {
    if (pumping) return;
    pumping = true;
    while (queue.length > 0) {
      const index = queue.shift()!;
      if (states[index].status === "queued") await uploadOne(index);
    }
    pumping = false;
  };

  const started = (async () => {
    const problem = checkShare(files);
    if (problem) throw new UploadError("too-large", problem);

    const send = async () => {
      const token = await getToken().catch(() => {
        throw new UploadError("verification", "Couldn't verify this browser");
      });
      return postJson<StartResponse>("/uploads", {
        files: files.map((f) => ({
          filename: f.name,
          size: f.size,
          content_type: f.type || "application/octet-stream",
        })),
        turnstile_token: token,
      });
    };
    // A prepared token can expire right as it's sent; try once more with a fresh one.
    const res = await send().catch((err: unknown) => {
      if (err instanceof UploadError && err.kind === "verification") return send();
      throw err;
    });

    shareId = res.share_id;
    partSize = res.part_size;
    for (const f of res.files) {
      jobs[f.index] = {
        uploadId: f.upload_id,
        partUrls: f.part_urls,
        etags: f.part_urls.map(() => null),
        sent: f.part_urls.map(() => 0),
        active: new Set(),
        stopped: false,
      };
      // the server may have cleaned up the name; show what the recipient will see
      states[f.index].filename = f.filename;
    }
    // files cancelled while the share was starting
    for (const s of states) if (s.status === "cancelled") abortOnServer(s.index);
    emit();
    queue.push(...states.filter((s) => s.status === "queued").map((s) => s.index));
    void pump();
    return { shareId: res.share_id, files: res.files.map((f) => ({ index: f.index, filename: f.filename, size: files[f.index].size })) };
  })();
  started.catch(stopListening);

  const cancel = (index: number) => {
    const state = states[index];
    if (!state || state.status === "done" || state.status === "cancelled") return;
    state.status = "cancelled";
    stopJob(index);
    abortOnServer(index);
    emit();
  };

  return {
    started,
    cancel,
    cancelAll: () => states.forEach((s) => cancel(s.index)),
    retry: (index: number) => {
      const state = states[index];
      if (!state || state.status !== "failed") return;
      state.status = "queued";
      emit();
      queue.push(index);
      void pump();
    },
    dispose: () => {
      for (const s of unfinished()) {
        stopJob(s.index);
        abortOnServer(s.index);
      }
      stopListening();
    },
  };
}

/** fetch, but give up after `ms`; a request on a dead connection otherwise waits forever. */
async function fetchWithTimeout(url: string, init: RequestInit, ms: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (err) {
    if (controller.signal.aborted) throw new UploadError("failed", "Request timed out");
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function postJson<T>(path: string, body: unknown, ms = API_MS): Promise<T> {
  const res = await fetchWithTimeout(
    `${API_URL}${path}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    ms,
  );
  if (res.status === 413) throw new UploadError("too-large", "Share is over 10 GB", 413);
  if (res.status === 403) throw new UploadError("verification", "Couldn't verify this browser", 403);
  if (res.status === 429) throw new UploadError("limit", "Daily upload limit reached", 429);
  if (!res.ok) throw new UploadError("failed", `Request failed (${res.status})`, res.status);
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
    let timer: ReturnType<typeof setTimeout> | undefined;
    let timedOut = false;
    // (re)start the clock: STALL_MS while bytes flow, REPLY_MS once they've all gone
    const arm = (ms: number) => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        timedOut = true;
        xhr.abort();
      }, ms);
    };
    const done = () => {
      clearTimeout(timer);
      active.delete(xhr);
    };
    xhr.upload.onprogress = (e) => {
      onSent(e.loaded);
      arm(e.loaded >= blob.size ? REPLY_MS : STALL_MS);
    };
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
      // a timeout is a failure (so it's retried); anything else is a cancel
      reject(timedOut ? new UploadError("failed", "Part upload timed out") : new UploadError("cancelled", "Upload cancelled"));
    };
    xhr.open("PUT", url);
    xhr.send(blob);
    arm(STALL_MS);
  });
}

/** The finished files in a share, for the share page. null means missing or expired. */
export async function getShareInfo(shareId: string): Promise<{ shareId: string; files: SharedFile[] } | null> {
  const res = await fetchWithTimeout(`${API_URL}/f/${enc(shareId)}/info`, {}, API_MS);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Info request failed (${res.status})`);
  const body = (await res.json()) as { share_id: string; files: SharedFile[] };
  return { shareId: body.share_id, files: body.files };
}

/** Where a file's Download button sends the browser: the API redirects to a presigned R2 URL. */
export function fileDownloadUrl(shareId: string, index: number): string {
  return `${API_URL}/f/${enc(shareId)}/${index}`;
}

export const ABUSE_EMAIL = "abuse@beamshare.app";

export class ReportError extends Error {
  readonly kind: "verification" | "unavailable" | "failed";
  constructor(kind: ReportError["kind"], message: string) {
    super(message);
    this.kind = kind;
  }
}

/** Sends an abuse report about a share. Like uploads, a rejected token gets one retry with a fresh one. */
export async function sendReport(
  shareId: string,
  reason: string,
  email: string,
  getToken: () => Promise<string>,
): Promise<void> {
  const attempt = async () => {
    const token = await getToken().catch(() => {
      throw new ReportError("verification", "Couldn't verify this browser");
    });
    const res = await fetch(`${API_URL}/reports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ share_id: shareId, reason, email: email || null, turnstile_token: token }),
    });
    if (res.status === 403) throw new ReportError("verification", "Couldn't verify this browser");
    // 502: our email service failed, so the reporter should email us directly
    if (res.status === 502) throw new ReportError("unavailable", "Couldn't send the report");
    if (!res.ok) throw new ReportError("failed", `Report failed (${res.status})`);
  };
  await attempt().catch((err: unknown) => {
    if (err instanceof ReportError && err.kind === "verification") return attempt();
    throw err;
  });
}
