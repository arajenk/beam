// Spec for the multi-file upload logic in api.ts. The network is faked:
// `fetch` answers the API calls, FakeXHR stands in for the part PUTs to R2.
// Run with `npm test`.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  checkShare,
  createRequest,
  fileDownloadUrl,
  getRequestInfo,
  getShareInfo,
  requestFileUrl,
  requestPageUrl,
  requestTarget,
  sendReport,
  startShare,
  UploadError,
  type FileState,
  type UploadTarget,
} from "./api";

const API = "http://localhost:8000";
const MiB = 1024 ** 2;
const GiB = 1024 ** 3;

type Call = { method: string; url: string; body?: unknown };
let calls: Call[];
let xhrs: FakeXHR[];
// decides how each PUT ends; default: succeed with an ETag named after the URL
// hang: nothing moves; trickle: slow but steady, done after 100 s; sent-hang: all bytes go, no reply
let onPut: (xhr: FakeXHR) => "ok" | "fail" | "hang" | "trickle" | "sent-hang";
// API calls that never answer (until their signal aborts them)
let hangs: (url: string) => boolean;
let startResponse: (body: { files: { filename: string; size: number }[] }) => Response;
let listeners: Record<string, ((e: unknown) => void)[]>;
let beacons: string[];

class FakeXHR {
  url = "";
  status = 0;
  aborted = false;
  upload: { onprogress: ((e: { loaded: number }) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  private etag: string | null = null;
  open(_method: string, url: string) {
    this.url = url;
  }
  send(blob: Blob) {
    xhrs.push(this);
    calls.push({ method: "PUT", url: this.url });
    const outcome = onPut(this);
    if (outcome === "hang") return;
    if (outcome === "sent-hang") {
      queueMicrotask(() => this.upload.onprogress?.({ loaded: blob.size }));
      return;
    }
    if (outcome === "trickle") {
      for (let step = 1; step <= 10; step++) {
        setTimeout(() => {
          if (this.aborted) return;
          this.upload.onprogress?.({ loaded: Math.floor((blob.size * step) / 11) });
          if (step === 10) {
            this.upload.onprogress?.({ loaded: blob.size });
            this.status = 200;
            this.etag = `"etag-${this.url}"`;
            this.onload?.();
          }
        }, step * 10_000);
      }
      return;
    }
    queueMicrotask(() => {
      if (this.aborted) return;
      if (outcome === "ok") {
        this.upload.onprogress?.({ loaded: blob.size });
        this.status = 200;
        this.etag = `"etag-${this.url}"`;
        this.onload?.();
      } else {
        this.onerror?.();
      }
    });
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
  getResponseHeader(name: string) {
    return name === "ETag" ? this.etag : null;
  }
}

/** The API's start response for these files: part URLs named share/index/part. */
function signedFor(body: { files: { filename: string; size: number }[] }, partSize = 64 * MiB) {
  return Response.json({
    share_id: "SHARE",
    part_size: partSize,
    files: body.files.map((f, index) => ({
      index,
      filename: f.filename,
      upload_id: `up-${index}`,
      part_urls: Array.from({ length: Math.ceil(f.size / partSize) }, (_, p) => `https://r2/SHARE/${index}/${p + 1}`),
    })),
  });
}

beforeEach(() => {
  calls = [];
  xhrs = [];
  beacons = [];
  listeners = {};
  onPut = () => "ok";
  hangs = () => false;
  startResponse = (body) => signedFor(body);
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  vi.stubGlobal("window", {
    location: { origin: "https://beamshare.app" },
    addEventListener: (type: string, fn: (e: unknown) => void) => (listeners[type] ??= []).push(fn),
    removeEventListener: (type: string, fn: (e: unknown) => void) =>
      (listeners[type] = (listeners[type] ?? []).filter((f) => f !== fn)),
  });
  vi.stubGlobal("navigator", { sendBeacon: (url: string) => beacons.push(url) });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(init.body as string) : undefined;
      calls.push({ method: init?.method ?? "GET", url, body });
      if (hangs(url)) {
        return new Promise<Response>((_, reject) =>
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))),
        );
      }
      if (url === `${API}/uploads` || url === `${API}/r/REQ/uploads`) return startResponse(body);
      if (url.endsWith("/complete")) return Response.json({});
      if (url.includes("/abort") || url.endsWith("/reports")) return new Response(null, { status: 204 });
      return new Response(null, { status: 404 });
    }),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const file = (name: string, size: number) => new File([new Uint8Array(size)], name, { type: "text/plain" });
const token = () => Promise.resolve("tok");

/** Starts a share and resolves once every file has settled (done, failed or cancelled). */
function run(files: File[], target?: UploadTarget) {
  let latest: FileState[] = [];
  let resolveSettled: (s: FileState[]) => void = () => {};
  const settled = new Promise<FileState[]>((r) => (resolveSettled = r));
  const handle = startShare(
    files,
    (states) => {
      latest = states;
      if (states.every((s) => s.status === "done" || s.status === "failed" || s.status === "cancelled")) {
        resolveSettled(states);
      }
    },
    token,
    target,
  );
  return { handle, settled, latest: () => latest };
}

const statuses = (states: FileState[]) => states.map((s) => s.status);
const puts = () => calls.filter((c) => c.method === "PUT").map((c) => c.url);
const posts = () => calls.filter((c) => c.method === "POST").map((c) => c.url.replace(API, ""));

describe("checkShare", () => {
  it("accepts up to 10 files and 10 GB in total", () => {
    expect(checkShare(Array.from({ length: 10 }, () => ({ size: GiB })))).toBeNull();
  });

  it("refuses an 11th file", () => {
    expect(checkShare(Array.from({ length: 11 }, () => ({ size: 1 })))).toMatch(/10 files/);
  });

  it("refuses more than 10 GB in total", () => {
    expect(checkShare([{ size: 5 * GiB }, { size: 5 * GiB + 1 }])).toMatch(/10 GB/);
  });
});

describe("startShare", () => {
  it("declares every file in one start call", async () => {
    const { handle, settled } = run([file("a.txt", 5), file("b.txt", 3)]);

    const started = await handle.started;
    await settled;

    expect(started.shareId).toBe("SHARE");
    const start = calls.filter((c) => c.url === `${API}/uploads`);
    expect(start).toHaveLength(1);
    expect(start[0].body).toEqual({
      files: [
        { filename: "a.txt", size: 5, content_type: "text/plain" },
        { filename: "b.txt", size: 3, content_type: "text/plain" },
      ],
      turnstile_token: "tok",
    });
  });

  it("uploads files one after another, completing each before the next starts", async () => {
    const { settled } = run([file("a.txt", 5), file("b.txt", 3)]);

    expect(statuses(await settled)).toEqual(["done", "done"]);
    expect(calls.filter((c) => c.url !== `${API}/uploads`).map((c) => c.url.replace(API, ""))).toEqual([
      "https://r2/SHARE/0/1",
      "/uploads/SHARE/0/complete",
      "https://r2/SHARE/1/1",
      "/uploads/SHARE/1/complete",
    ]);
  });

  it("completes a file with its parts in order", async () => {
    startResponse = (body) => signedFor(body, 2);
    const { settled } = run([file("a.txt", 5)]);

    await settled;

    const complete = calls.find((c) => c.url.endsWith("/complete"));
    expect(complete?.body).toEqual({
      upload_id: "up-0",
      parts: [1, 2, 3].map((n) => ({ part_number: n, etag: `"etag-https://r2/SHARE/0/${n}"` })),
    });
  });

  it("reports progress per file", async () => {
    const { settled } = run([file("a.txt", 5), file("b.txt", 3)]);

    const states = await settled;

    expect(states.map((s) => [s.loaded, s.size])).toEqual([
      [5, 5],
      [3, 3],
    ]);
  });

  it("cancelling the uploading file keeps the rest going", async () => {
    onPut = (xhr) => (xhr.url.includes("/0/") ? "hang" : "ok");
    const { handle, settled } = run([file("a.txt", 5), file("b.txt", 3)]);
    await vi.waitFor(() => expect(xhrs).toHaveLength(1));

    handle.cancel(0);

    expect(statuses(await settled)).toEqual(["cancelled", "done"]);
    expect(xhrs[0].aborted).toBe(true);
    expect(posts()).toContain("/uploads/SHARE/0/abort?upload_id=up-0");
    expect(posts()).not.toContain("/uploads/SHARE/0/complete");
  });

  it("cancelling a queued file means it's never sent", async () => {
    onPut = (xhr) => (xhr.url.includes("/0/") ? "hang" : "ok");
    const { handle, latest } = run([file("a.txt", 5), file("b.txt", 3)]);
    await vi.waitFor(() => expect(xhrs).toHaveLength(1));

    handle.cancel(1);
    onPut = () => "ok";
    xhrs[0].abort(); // the stuck part gives up, so file 0 fails
    await vi.waitFor(() => expect(statuses(latest())[0]).toBe("failed"));
    handle.retry(0);

    await vi.waitFor(() => expect(statuses(latest())).toEqual(["done", "cancelled"]));
    expect(puts().some((u) => u.includes("/1/"))).toBe(false);
    expect(posts()).toContain("/uploads/SHARE/1/abort?upload_id=up-1");
  });

  it("a file that keeps failing is marked failed and the next file still uploads", async () => {
    vi.useFakeTimers();
    onPut = (xhr) => (xhr.url.includes("/0/") ? "fail" : "ok");
    const { settled } = run([file("a.txt", 5), file("b.txt", 3)]);

    await vi.runAllTimersAsync();

    expect(statuses(await settled)).toEqual(["failed", "done"]);
    expect(puts().filter((u) => u.includes("/0/"))).toHaveLength(3); // 3 attempts
    // a failed file isn't aborted: it can still be retried
    expect(posts()).not.toContain("/uploads/SHARE/0/abort?upload_id=up-0");
  });

  it("retry re-sends only the parts that didn't make it", async () => {
    vi.useFakeTimers();
    startResponse = (body) => signedFor(body, 2);
    onPut = (xhr) => (xhr.url.endsWith("/0/3") ? "fail" : "ok");
    const { handle, latest } = run([file("a.txt", 5)]);
    await vi.runAllTimersAsync();
    expect(statuses(latest())).toEqual(["failed"]);
    calls = [];

    onPut = () => "ok";
    handle.retry(0);
    await vi.runAllTimersAsync();

    expect(statuses(latest())).toEqual(["done"]);
    expect(puts()).toEqual(["https://r2/SHARE/0/3"]);
    expect(latest()[0].loaded).toBe(5);
  });

  it("cancel all stops everything that isn't done", async () => {
    onPut = (xhr) => (xhr.url.includes("/1/") ? "hang" : "ok");
    const { handle, settled } = run([file("a.txt", 5), file("b.txt", 3), file("c.txt", 2)]);
    await vi.waitFor(() => expect(xhrs).toHaveLength(2));

    handle.cancelAll();

    expect(statuses(await settled)).toEqual(["done", "cancelled", "cancelled"]);
    expect(posts()).toContain("/uploads/SHARE/1/abort?upload_id=up-1");
    expect(posts()).toContain("/uploads/SHARE/2/abort?upload_id=up-2");
    expect(posts()).not.toContain("/uploads/SHARE/0/abort?upload_id=up-0");
  });

  it("closing the tab sends an abort beacon for each unfinished file", async () => {
    onPut = (xhr) => (xhr.url.includes("/1/") ? "hang" : "ok");
    const { handle } = run([file("a.txt", 5), file("b.txt", 3), file("c.txt", 2)]);
    await handle.started;
    await vi.waitFor(() => expect(xhrs).toHaveLength(2));

    listeners.pagehide.forEach((fn) => fn({}));

    expect(beacons).toEqual([
      `${API}/uploads/SHARE/1/abort?upload_id=up-1`,
      `${API}/uploads/SHARE/2/abort?upload_id=up-2`,
    ]);
  });

  it.each([
    [413, "too-large"],
    [429, "limit"],
  ])("a %i on start rejects the whole share as %s", async (status, kind) => {
    startResponse = () => new Response(null, { status });
    const { handle } = run([file("a.txt", 5)]);

    await expect(handle.started).rejects.toMatchObject({ kind });
    expect(puts()).toEqual([]);
  });

  it("a rejected Turnstile token is retried once with a fresh one", async () => {
    let starts = 0;
    startResponse = (body) => (++starts === 1 ? new Response(null, { status: 403 }) : signedFor(body));
    const { handle, settled } = run([file("a.txt", 5)]);

    await handle.started;

    expect(statuses(await settled)).toEqual(["done"]);
    expect(starts).toBe(2);
  });

  it("refuses a share over the limits without calling the API", async () => {
    const { handle } = run(Array.from({ length: 11 }, (_, i) => file(`${i}.txt`, 1)));

    await expect(handle.started).rejects.toBeInstanceOf(UploadError);
    expect(calls).toEqual([]);
  });
});

describe("timeouts", () => {
  beforeEach(() => vi.useFakeTimers());

  it("a part with no progress for 30 s counts as failed", async () => {
    onPut = () => "hang";
    const { latest } = run([file("a.txt", 5)]);

    await vi.advanceTimersByTimeAsync(29_000);
    expect(statuses(latest())).toEqual(["uploading"]);
    await vi.runAllTimersAsync();

    expect(statuses(latest())).toEqual(["failed"]);
    expect(puts()).toHaveLength(3); // each attempt stalled
    expect(xhrs.every((x) => x.aborted)).toBe(true);
  });

  it("a slow part that keeps moving is never cut off", async () => {
    onPut = () => "trickle"; // 100 s in total, progress every 10 s
    const { latest } = run([file("a.txt", 5)]);

    await vi.runAllTimersAsync();

    expect(statuses(latest())).toEqual(["done"]);
    expect(puts()).toHaveLength(1);
  });

  it("a part fully sent with no reply for 30 s counts as failed", async () => {
    onPut = () => "sent-hang";
    const { latest } = run([file("a.txt", 5)]);

    await vi.advanceTimersByTimeAsync(29_000);
    expect(statuses(latest())).toEqual(["uploading"]);
    await vi.runAllTimersAsync();

    expect(statuses(latest())).toEqual(["failed"]);
  });

  it("a start that never answers fails after 20 s", async () => {
    hangs = (url) => url === `${API}/uploads`;
    const { handle } = run([file("a.txt", 5)]);
    const outcome = handle.started.then(
      () => "resolved",
      (err: UploadError) => err.kind,
    );

    await vi.advanceTimersByTimeAsync(19_000);
    await vi.runAllTimersAsync();

    expect(await outcome).toBe("failed");
  });

  it("a complete that never answers fails the file after 60 s", async () => {
    hangs = (url) => url.endsWith("/complete");
    const { latest } = run([file("a.txt", 5)]);

    await vi.advanceTimersByTimeAsync(59_000);
    expect(statuses(latest())).toEqual(["uploading"]);
    await vi.advanceTimersByTimeAsync(2_000);

    expect(statuses(latest())).toEqual(["failed"]);
  });

  it("a complete whose reply was lost ends as done once the file shows up in the share", async () => {
    // first complete went through on the server but the reply never arrived
    hangs = (url) => url.endsWith("/complete");
    const { handle, latest } = run([file("a.txt", 5)]);
    await vi.advanceTimersByTimeAsync(61_000);
    expect(statuses(latest())).toEqual(["failed"]);

    // so retrying finds no upload left (404), but the listing has the file
    hangs = () => false;
    vi.mocked(fetch).mockImplementation(async (url) => {
      calls.push({ method: "?", url: String(url) });
      if (String(url).endsWith("/complete")) return new Response(null, { status: 404 });
      if (String(url).endsWith("/info"))
        return Response.json({ share_id: "SHARE", files: [{ index: 0, filename: "a.txt", size: 5 }] });
      return new Response(null, { status: 204 });
    });
    handle.retry(0);
    await vi.runAllTimersAsync();

    expect(statuses(latest())).toEqual(["done"]);
  });

  it("a 404 on complete with the file not in the share stays failed", async () => {
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const u = String(url);
      calls.push({ method: init?.method ?? "GET", url: u });
      if (u === `${API}/uploads`) return signedFor(JSON.parse(init!.body as string));
      if (u.endsWith("/complete")) return new Response(null, { status: 404 });
      if (u.endsWith("/info")) return new Response(null, { status: 404 });
      return new Response(null, { status: 204 });
    });
    const { latest } = run([file("a.txt", 5)]);

    await vi.runAllTimersAsync();

    expect(statuses(latest())).toEqual(["failed"]);
  });

  it("share info that never answers fails after 20 s", async () => {
    hangs = () => true;
    const outcome = getShareInfo("S").then(
      () => "resolved",
      () => "rejected",
    );

    await vi.advanceTimersByTimeAsync(21_000);

    expect(await outcome).toBe("rejected");
  });
});

describe("share page calls", () => {
  it("getShareInfo maps the listing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ share_id: "S", files: [{ index: 2, filename: "b.txt", size: 3 }] })),
    );

    expect(await getShareInfo("S")).toEqual({ shareId: "S", files: [{ index: 2, filename: "b.txt", size: 3 }] });
  });

  it("getShareInfo of a missing share is null", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 404 })));

    expect(await getShareInfo("S")).toBeNull();
  });

  it("fileDownloadUrl points at the API's per-file redirect", () => {
    expect(fileDownloadUrl("S", 3)).toBe(`${API}/f/S/3`);
  });

  it("sendReport sends the share id", async () => {
    await sendReport("SHARE", "malware", "", token);

    expect(calls[0].body).toEqual({
      share_id: "SHARE",
      reason: "malware",
      email: null,
      turnstile_token: "tok",
      kind: "share",
    });
  });

  it("sendReport can report a file request", async () => {
    await sendReport("REQ", "phishing", "", token, "request");

    expect(calls[0].body).toMatchObject({ share_id: "REQ", kind: "request" });
  });
});

describe("sending into a file request", () => {
  it("starts at the request's upload route with the sender's name", async () => {
    const { handle, settled } = run([file("a.txt", 5)], requestTarget("REQ", "Alex"));

    await handle.started;
    await settled;

    const start = calls.find((c) => c.url === `${API}/r/REQ/uploads`);
    expect(start?.body).toEqual({
      sender: "Alex",
      files: [{ filename: "a.txt", size: 5, content_type: "text/plain" }],
      turnstile_token: "tok",
    });
    expect(calls.some((c) => c.url === `${API}/uploads`)).toBe(false);
  });

  it("completes each file at the request's routes", async () => {
    const { settled } = run([file("a.txt", 5), file("b.txt", 3)], requestTarget("REQ", "Alex"));

    expect(statuses(await settled)).toEqual(["done", "done"]);
    expect(posts()).toEqual(["/r/REQ/uploads", "/r/REQ/uploads/SHARE/0/complete", "/r/REQ/uploads/SHARE/1/complete"]);
  });

  it("cancels and beacons at the request's routes", async () => {
    onPut = (xhr) => (xhr.url.includes("/1/") ? "hang" : "ok");
    const { handle } = run([file("a.txt", 5), file("b.txt", 3)], requestTarget("REQ", "Alex"));
    await vi.waitFor(() => expect(xhrs).toHaveLength(2));

    listeners.pagehide.forEach((fn) => fn({}));
    handle.cancel(1);

    expect(beacons).toEqual([`${API}/r/REQ/uploads/SHARE/1/abort?upload_id=up-1`]);
    expect(posts()).toContain("/r/REQ/uploads/SHARE/1/abort?upload_id=up-1");
  });

  it.each([
    [410, "closed"],
    [404, "missing"],
  ])("a %i on start rejects the send as %s", async (status, kind) => {
    startResponse = () => new Response(null, { status });
    const { handle } = run([file("a.txt", 5)], requestTarget("REQ", "Alex"));

    await expect(handle.started).rejects.toMatchObject({ kind });
    expect(puts()).toEqual([]);
  });

  it("a 404 on complete stays failed without reading the listing", async () => {
    // the API itself answers repeated completes, and a sender may not be allowed to list
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const u = String(url);
      calls.push({ method: init?.method ?? "GET", url: u });
      if (u === `${API}/r/REQ/uploads`) return signedFor(JSON.parse(init!.body as string));
      if (u.endsWith("/complete")) return new Response(null, { status: 404 });
      return new Response(null, { status: 204 });
    });
    const { settled } = run([file("a.txt", 5)], requestTarget("REQ", "Alex"));

    expect(statuses(await settled)).toEqual(["failed"]);
    expect(calls.some((c) => c.url.includes("/info"))).toBe(false);
  });
});

describe("file request calls", () => {
  it("createRequest sends the note, name and switch and returns both ids", async () => {
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      calls.push({ method: init?.method ?? "GET", url: String(url), body: JSON.parse(init!.body as string) });
      return Response.json({ request_id: "REQ", owner_key: "KEY" });
    });

    const made = await createRequest({ note: "slides pls", name: "Ara", private: true }, token);

    expect(made).toEqual({ requestId: "REQ", ownerKey: "KEY" });
    expect(calls).toEqual([
      {
        method: "POST",
        url: `${API}/requests`,
        body: { note: "slides pls", name: "Ara", private: true, turnstile_token: "tok" },
      },
    ]);
  });

  it("createRequest sends a blank name as none", async () => {
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      calls.push({ method: "POST", url: String(url), body: JSON.parse(init!.body as string) });
      return Response.json({ request_id: "REQ", owner_key: "KEY" });
    });

    await createRequest({ note: "hi", name: "   ", private: false }, token);

    expect(calls[0].body).toMatchObject({ name: null });
  });

  it("createRequest retries a rejected Turnstile token once", async () => {
    let tries = 0;
    vi.mocked(fetch).mockImplementation(async () =>
      ++tries === 1 ? new Response(null, { status: 403 }) : Response.json({ request_id: "REQ", owner_key: "KEY" }),
    );

    expect(await createRequest({ note: "hi", name: "", private: false }, token)).toEqual({
      requestId: "REQ",
      ownerKey: "KEY",
    });
    expect(tries).toBe(2);
  });

  it("getRequestInfo passes the owner key and maps the answer", async () => {
    vi.mocked(fetch).mockImplementation(async (url) => {
      calls.push({ method: "GET", url: String(url) });
      return Response.json({
        request_id: "REQ",
        note: "slides pls",
        name: null,
        private: true,
        open: false,
        closes_at: 1700000000,
        is_owner: true,
        sends: [{ share_id: "S1", sender: "Alex", files: [{ index: 0, filename: "a.txt", size: 5 }] }],
      });
    });

    const info = await getRequestInfo("REQ", "K/Y");

    expect(calls[0].url).toBe(`${API}/r/REQ/info?key=K%2FY`);
    expect(info).toEqual({
      requestId: "REQ",
      note: "slides pls",
      name: null,
      private: true,
      open: false,
      closesAt: 1700000000,
      isOwner: true,
      sends: [{ shareId: "S1", sender: "Alex", files: [{ index: 0, filename: "a.txt", size: 5 }] }],
    });
  });

  it("getRequestInfo keeps hidden files as null and leaves the key off when there isn't one", async () => {
    vi.mocked(fetch).mockImplementation(async (url) => {
      calls.push({ method: "GET", url: String(url) });
      return Response.json({
        request_id: "REQ", note: "n", name: "Ara", private: true, open: true, closes_at: 1, is_owner: false, sends: null,
      });
    });

    const info = await getRequestInfo("REQ");

    expect(calls[0].url).toBe(`${API}/r/REQ/info`);
    expect(info?.sends).toBeNull();
  });

  it("getRequestInfo of a missing request is null", async () => {
    vi.mocked(fetch).mockImplementation(async () => new Response(null, { status: 404 }));

    expect(await getRequestInfo("REQ")).toBeNull();
  });

  it("requestFileUrl points at the request's download redirect, with the key if given", () => {
    expect(requestFileUrl("REQ", "S1", 2)).toBe(`${API}/r/REQ/S1/2`);
    expect(requestFileUrl("REQ", "S1", 2, "KEY")).toBe(`${API}/r/REQ/S1/2?key=KEY`);
  });

  it("requestPageUrl is the public link, or the owner link with the key", () => {
    expect(requestPageUrl("REQ")).toBe("https://beamshare.app/r/REQ");
    expect(requestPageUrl("REQ", "KEY")).toBe("https://beamshare.app/r/REQ/KEY");
  });
});
