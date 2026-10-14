"""
Spec for presigned multipart uploads. R2 is faked with botocore's Stubber, so
these run offline in about a second: `uv run pytest -v`.

How the fake works: each `stubber.add_response(op, response, expected_params)`
queues one R2 call. Your code must make exactly those calls, in that order, with
exactly those params (ANY matches anything). A call that wasn't queued, or a
queued call that never happens, fails the test.

Presigning (`generate_presigned_url`) never talks to R2, so it isn't stubbed;
the `presigned` fixture records those calls instead.
"""

import asyncio
from urllib.parse import parse_qs, quote, urlparse

import pytest
from botocore.stub import ANY, Stubber
from fastapi import Request
from fastapi.testclient import TestClient

from beam.main import app
from beam.routers import files

GiB = 1024**3
MiB = 1024**2
MAX_SIZE = 10 * GiB
PART_SIZE = 64 * MiB
URL_LIFETIME = 6 * 60 * 60


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch):
    """Every test starts with empty counters and records, and a fake Turnstile
    that accepts the token "ok" (the real one would call Cloudflare)."""
    files.ip_bytes.clear()
    files.uploads.clear()
    monkeypatch.setattr(files, "total_bytes", 0)
    checked = []

    def fake_verify(token, ip):
        checked.append(token)
        return token == "ok"

    monkeypatch.setattr(files, "verify_turnstile", fake_verify)
    yield checked
    files.ip_bytes.clear()
    files.uploads.clear()


@pytest.fixture
def r2():
    with Stubber(files.s3) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()


@pytest.fixture
def presigned(monkeypatch):
    """Records every generate_presigned_url call, then signs for real."""
    calls = []
    real = files.s3.generate_presigned_url

    def record(ClientMethod, Params=None, ExpiresIn=3600, HttpMethod=None):
        calls.append({"method": ClientMethod, "params": Params, "expires": ExpiresIn})
        return real(ClientMethod, Params=Params, ExpiresIn=ExpiresIn)

    monkeypatch.setattr(files.s3, "generate_presigned_url", record)
    return calls


def expect_create(r2, filename, content_type, upload_id="upload-123"):
    r2.add_response(
        "create_multipart_upload",
        {"Bucket": "beam", "Key": "anything", "UploadId": upload_id},
        {
            "Bucket": "beam",
            "Key": ANY,
            "ContentType": content_type,
            # same encoding as before: metadata travels as HTTP headers
            "Metadata": {"filename": quote(filename, safe="")},
        },
    )


# ── POST /uploads (start) ────────────────────────────────────────────────────


def test_start_returns_one_url_per_part(client, r2, presigned):
    expect_create(r2, "big.mov", "video/quicktime")

    r = client.post("/uploads", json={"turnstile_token": "ok", "filename": "big.mov", "size": 3 * GiB, "content_type": "video/quicktime"})

    assert r.status_code == 200
    body = r.json()
    assert body["upload_id"] == "upload-123"
    assert body["part_size"] == PART_SIZE
    assert len(body["part_urls"]) == 48  # 3 GiB / 64 MiB
    assert body["file_id"]


def test_part_urls_are_signed_for_exact_sizes(client, r2, presigned):
    # 100 MiB + 1 byte → one full 64 MiB part and a smaller last part
    size = 100 * MiB + 1
    expect_create(r2, "a.zip", "application/zip")

    r = client.post("/uploads", json={"turnstile_token": "ok", "filename": "a.zip", "size": size, "content_type": "application/zip"})

    assert r.status_code == 200
    file_id = r.json()["file_id"]
    assert [c["method"] for c in presigned] == ["upload_part", "upload_part"]
    assert [c["params"]["PartNumber"] for c in presigned] == [1, 2]
    assert [c["params"]["ContentLength"] for c in presigned] == [PART_SIZE, size - PART_SIZE]
    for c in presigned:
        assert c["params"]["Bucket"] == "beam"
        assert c["params"]["Key"] == file_id
        assert c["params"]["UploadId"] == "upload-123"
        assert c["expires"] == URL_LIFETIME


def test_part_urls_make_r2_enforce_content_length(client, r2, presigned):
    expect_create(r2, "a.txt", "text/plain")

    r = client.post("/uploads", json={"turnstile_token": "ok", "filename": "a.txt", "size": 10, "content_type": "text/plain"})

    url = r.json()["part_urls"][0]
    signed_headers = parse_qs(urlparse(url).query)["X-Amz-SignedHeaders"][0].split(";")
    assert "content-length" in signed_headers


def test_small_file_is_a_single_part(client, r2, presigned):
    expect_create(r2, "note.txt", "text/plain")

    r = client.post("/uploads", json={"turnstile_token": "ok", "filename": "note.txt", "size": 10, "content_type": "text/plain"})

    assert len(r.json()["part_urls"]) == 1
    assert presigned[0]["params"]["ContentLength"] == 10


def test_exactly_10_gib_is_allowed(client, r2, presigned):
    expect_create(r2, "max.bin", "application/octet-stream")

    r = client.post("/uploads", json={"turnstile_token": "ok", "filename": "max.bin", "size": MAX_SIZE, "content_type": "application/octet-stream"})

    assert r.status_code == 200
    assert len(r.json()["part_urls"]) == 160


def test_over_10_gib_is_refused_before_touching_r2(client, r2, presigned):
    # nothing queued on r2: any R2 call here fails the test
    r = client.post("/uploads", json={"turnstile_token": "ok", "filename": "huge.bin", "size": MAX_SIZE + 1, "content_type": "application/octet-stream"})

    assert r.status_code == 413
    assert presigned == []


@pytest.mark.parametrize("size", [0, -5])
def test_empty_or_negative_size_is_rejected(client, r2, size):
    r = client.post("/uploads", json={"turnstile_token": "ok", "filename": "x", "size": size, "content_type": "text/plain"})

    assert r.status_code == 422


# ── POST /uploads/{file_id}/complete ─────────────────────────────────────────


def expect_list_parts(r2, parts, file_id="abc123", upload_id="upload-123"):
    r2.add_response(
        "list_parts",
        {"Parts": [{"PartNumber": n, "ETag": etag, "Size": size} for n, etag, size in parts]},
        {"Bucket": "beam", "Key": file_id, "UploadId": upload_id},
    )


def test_complete_joins_the_parts(client, r2):
    expect_list_parts(r2, [(1, '"e1"', PART_SIZE), (2, '"e2"', 5)])
    r2.add_response(
        "complete_multipart_upload",
        {},
        {
            "Bucket": "beam",
            "Key": "abc123",
            "UploadId": "upload-123",
            "MultipartUpload": {"Parts": [{"PartNumber": 1, "ETag": '"e1"'}, {"PartNumber": 2, "ETag": '"e2"'}]},
        },
    )

    r = client.post(
        "/uploads/abc123/complete",
        json={"upload_id": "upload-123", "parts": [{"part_number": 1, "etag": '"e1"'}, {"part_number": 2, "etag": '"e2"'}]},
    )

    assert r.status_code == 200
    assert r.json() == {"file_id": "abc123"}


def test_complete_refuses_when_r2_holds_more_than_10_gib(client, r2):
    # the browser claims 2 parts, but R2's own record is what counts
    expect_list_parts(r2, [(1, '"e1"', 6 * GiB), (2, '"e2"', 5 * GiB)])
    # an oversized upload can never be fixed, so its parts are discarded right away
    r2.add_response(
        "abort_multipart_upload",
        {},
        {"Bucket": "beam", "Key": "abc123", "UploadId": "upload-123"},
    )

    r = client.post(
        "/uploads/abc123/complete",
        json={"upload_id": "upload-123", "parts": [{"part_number": 1, "etag": '"e1"'}, {"part_number": 2, "etag": '"e2"'}]},
    )

    assert r.status_code == 413  # aborted, and complete_multipart_upload was never called


def test_complete_refuses_when_a_part_is_missing(client, r2):
    # browser says it uploaded 2 parts, R2 only has part 1
    expect_list_parts(r2, [(1, '"e1"', PART_SIZE)])

    r = client.post(
        "/uploads/abc123/complete",
        json={"upload_id": "upload-123", "parts": [{"part_number": 1, "etag": '"e1"'}, {"part_number": 2, "etag": '"e2"'}]},
    )

    assert r.status_code == 400


def test_complete_unknown_upload_is_404(client, r2):
    r2.add_client_error("list_parts", service_error_code="NoSuchUpload", http_status_code=404)

    r = client.post("/uploads/abc123/complete", json={"upload_id": "nope", "parts": [{"part_number": 1, "etag": '"e1"'}]})

    assert r.status_code == 404


# ── POST /uploads/{file_id}/abort ────────────────────────────────────────────


def test_abort_discards_the_parts(client, r2):
    r2.add_response(
        "abort_multipart_upload",
        {},
        {"Bucket": "beam", "Key": "abc123", "UploadId": "upload-123"},
    )

    r = client.post("/uploads/abc123/abort", params={"upload_id": "upload-123"})

    assert r.status_code == 204
    assert r.content == b""  # 204 means no body


def test_abort_of_finished_upload_still_succeeds(client, r2):
    # already completed or aborted: too late to cancel, nothing left to do
    r2.add_client_error("abort_multipart_upload", service_error_code="NoSuchUpload", http_status_code=404)

    r = client.post("/uploads/abc123/abort", params={"upload_id": "upload-123"})

    assert r.status_code == 204


# ── the old relay endpoint ───────────────────────────────────────────────────


def test_old_upload_endpoint_is_gone(client):
    r = client.post("/upload")

    assert r.status_code in (404, 405)


# ── abuse limits: Turnstile, holds, settling, sweeping ──────────────────────
#
# Every start holds its declared size against the uploader's IP and the global
# total. Complete settles the hold to the real size; abort and the sweeper
# release it. The record in files.uploads is the ticket: whoever removes it
# adjusts the counters, so a hold is released exactly once.

IP = "testclient"  # what TestClient reports as the client address
PER_IP_LIMIT = 50 * GiB
GLOBAL_LIMIT = 1024 * GiB
SWEEP_AFTER = 7 * 60 * 60


def start_body(size, token="ok"):
    body = {"filename": "a.bin", "size": size, "content_type": "application/octet-stream"}
    if token is not None:
        body["turnstile_token"] = token
    return body


def hold(file_id="abc123", upload_id="upload-123", ip=IP, size=100 * MiB, started_at=None):
    """Put an upload in the state start leaves it in: record written, size held."""
    files.uploads[file_id] = {
        "upload_id": upload_id,
        "ip": ip,
        "size": size,
        "started_at": files.time.time() if started_at is None else started_at,
    }
    files.ip_bytes[ip] = files.ip_bytes.get(ip, 0) + size
    files.total_bytes += size


def test_start_without_token_is_403_before_anything(client, r2, fresh_limits):
    r = client.post("/uploads", json=start_body(10, token=None))

    assert r.status_code == 403
    assert fresh_limits == []  # no point asking Cloudflare about nothing
    assert files.total_bytes == 0


def test_start_with_invalid_token_is_403(client, r2, presigned):
    r = client.post("/uploads", json=start_body(10, token="forged"))

    assert r.status_code == 403
    assert presigned == []
    assert files.total_bytes == 0


def test_start_holds_the_declared_size(client, r2, presigned):
    expect_create(r2, "a.bin", "application/octet-stream")

    r = client.post("/uploads", json=start_body(3 * GiB))

    assert r.status_code == 200
    file_id = r.json()["file_id"]
    assert files.ip_bytes[IP] == 3 * GiB
    assert files.total_bytes == 3 * GiB
    record = files.uploads[file_id]
    assert record["upload_id"] == "upload-123"
    assert record["ip"] == IP
    assert record["size"] == 3 * GiB


def test_start_up_to_the_ip_limit_is_allowed(client, r2, presigned):
    files.ip_bytes[IP] = PER_IP_LIMIT - 10
    files.total_bytes = PER_IP_LIMIT - 10
    expect_create(r2, "a.bin", "application/octet-stream")

    r = client.post("/uploads", json=start_body(10))

    assert r.status_code == 200
    assert files.ip_bytes[IP] == PER_IP_LIMIT


def test_start_over_the_ip_limit_is_429_and_holds_nothing(client, r2, presigned):
    files.ip_bytes[IP] = PER_IP_LIMIT - 10
    files.total_bytes = PER_IP_LIMIT - 10

    r = client.post("/uploads", json=start_body(11))

    assert r.status_code == 429
    assert presigned == []  # nothing queued on r2 either: R2 is never touched
    assert files.ip_bytes[IP] == PER_IP_LIMIT - 10
    assert files.total_bytes == PER_IP_LIMIT - 10


def test_start_over_the_global_cap_is_429(client, r2, presigned):
    # other IPs have used up nearly everything; this IP has used nothing
    files.total_bytes = GLOBAL_LIMIT - 10

    r = client.post("/uploads", json=start_body(11))

    assert r.status_code == 429
    assert IP not in files.ip_bytes
    assert files.total_bytes == GLOBAL_LIMIT - 10


def test_start_releases_the_hold_if_r2_fails(client, r2, presigned):
    r2.add_client_error("create_multipart_upload", service_error_code="InternalError", http_status_code=500)

    with pytest.raises(Exception):
        client.post("/uploads", json=start_body(3 * GiB))

    assert files.total_bytes == 0
    assert IP not in files.ip_bytes
    assert files.uploads == {}


def test_complete_settles_the_hold_to_the_real_size(client, r2):
    # declared 200 MiB, but only 70 MiB actually landed in R2
    hold(size=200 * MiB)
    expect_list_parts(r2, [(1, '"e1"', PART_SIZE), (2, '"e2"', 6 * MiB)])
    r2.add_response("complete_multipart_upload", {}, None)

    r = client.post(
        "/uploads/abc123/complete",
        json={"upload_id": "upload-123", "parts": [{"part_number": 1, "etag": '"e1"'}, {"part_number": 2, "etag": '"e2"'}]},
    )

    assert r.status_code == 200
    assert files.ip_bytes[IP] == 70 * MiB
    assert files.total_bytes == 70 * MiB
    assert "abc123" not in files.uploads  # settled, so the sweeper leaves it alone


def test_complete_413_releases_the_whole_hold(client, r2):
    hold(size=10 * GiB)
    expect_list_parts(r2, [(1, '"e1"', 6 * GiB), (2, '"e2"', 5 * GiB)])
    r2.add_response("abort_multipart_upload", {}, None)

    r = client.post(
        "/uploads/abc123/complete",
        json={"upload_id": "upload-123", "parts": [{"part_number": 1, "etag": '"e1"'}, {"part_number": 2, "etag": '"e2"'}]},
    )

    assert r.status_code == 413
    assert files.total_bytes == 0
    assert files.uploads == {}


def test_complete_mismatch_keeps_the_hold_so_the_client_can_retry(client, r2):
    hold(size=200 * MiB)
    expect_list_parts(r2, [(1, '"e1"', PART_SIZE)])

    r = client.post(
        "/uploads/abc123/complete",
        json={"upload_id": "upload-123", "parts": [{"part_number": 1, "etag": '"e1"'}, {"part_number": 2, "etag": '"e2"'}]},
    )

    assert r.status_code == 400
    assert files.total_bytes == 200 * MiB
    assert "abc123" in files.uploads


def test_abort_releases_the_hold_once(client, r2):
    hold(size=200 * MiB)
    r2.add_response("abort_multipart_upload", {}, None)
    r2.add_client_error("abort_multipart_upload", service_error_code="NoSuchUpload", http_status_code=404)

    first = client.post("/uploads/abc123/abort", params={"upload_id": "upload-123"})
    # the Cancel button and the tab-close beacon can both fire
    second = client.post("/uploads/abc123/abort", params={"upload_id": "upload-123"})

    assert first.status_code == second.status_code == 204
    assert files.total_bytes == 0  # not negative
    assert IP not in files.ip_bytes
    assert files.uploads == {}


def test_abort_with_wrong_upload_id_releases_nothing(client, r2):
    # someone pairs your file_id with a made-up upload_id: R2 says no such upload
    hold(size=200 * MiB)
    r2.add_client_error("abort_multipart_upload", service_error_code="NoSuchUpload", http_status_code=404)

    r = client.post("/uploads/abc123/abort", params={"upload_id": "made-up"})

    assert r.status_code == 204
    assert files.total_bytes == 200 * MiB
    assert "abc123" in files.uploads


def test_sweep_aborts_and_releases_only_old_uploads(r2):
    now = 1_000_000.0
    hold("old", "upload-old", size=5 * GiB, started_at=now - SWEEP_AFTER - 1)
    hold("young", "upload-young", size=1 * GiB, started_at=now - SWEEP_AFTER + 60)
    r2.add_response("abort_multipart_upload", {}, {"Bucket": "beam", "Key": "old", "UploadId": "upload-old"})

    files.sweep(now=now)

    assert set(files.uploads) == {"young"}
    assert files.total_bytes == 1 * GiB
    assert files.ip_bytes[IP] == 1 * GiB


def test_sweep_still_releases_when_r2_already_dropped_the_upload(r2):
    # e.g. R2's own abort rule got there first
    now = 1_000_000.0
    hold(size=5 * GiB, started_at=now - SWEEP_AFTER - 1)
    r2.add_client_error("abort_multipart_upload", service_error_code="NoSuchUpload", http_status_code=404)

    files.sweep(now=now)

    assert files.uploads == {}
    assert files.total_bytes == 0


def test_sweep_keeps_the_hold_if_r2_abort_fails(r2):
    # bytes might still be in R2, so don't give the budget back; the next sweep retries
    now = 1_000_000.0
    hold(size=5 * GiB, started_at=now - SWEEP_AFTER - 1)
    r2.add_client_error("abort_multipart_upload", service_error_code="InternalError", http_status_code=500)

    files.sweep(now=now)

    assert "abc123" in files.uploads
    assert files.total_bytes == 5 * GiB


def test_turnstile_is_verified_with_cloudflare(monkeypatch):
    # undo the autouse fake for this one test and check the real request shape
    monkeypatch.undo()
    sent = {}

    class FakeResponse:
        def json(self):
            return {"success": True}

    def fake_post(url, data, timeout):
        sent.update(url=url, data=data)
        return FakeResponse()

    monkeypatch.setattr(files.httpx, "post", fake_post)

    assert files.verify_turnstile("tok", "1.2.3.4") is True
    assert sent["url"] == "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    assert sent["data"]["secret"] == files.TURNSTILE_SECRET
    assert sent["data"]["response"] == "tok"
    assert sent["data"]["remoteip"] == "1.2.3.4"


def test_turnstile_unreachable_counts_as_not_verified(monkeypatch):
    monkeypatch.undo()

    def boom(url, data, timeout):
        raise files.httpx.ConnectError("down")

    monkeypatch.setattr(files.httpx, "post", boom)

    assert files.verify_turnstile("tok", "1.2.3.4") is False


def make_request(client_host, forwarded_for=None):
    headers = [] if forwarded_for is None else [(b"x-forwarded-for", forwarded_for.encode())]
    return Request({"type": "http", "headers": headers, "client": (client_host, 5000)})


def test_client_ip_is_the_entry_heroku_added():
    assert files.client_ip(make_request("10.0.0.1", "203.0.113.7")) == "203.0.113.7"


def test_client_ip_ignores_entries_the_client_sent():
    # Heroku appends what it saw, so only the last entry is trustworthy
    request = make_request("10.0.0.1", "1.2.3.4, 5.6.7.8, 203.0.113.7")
    assert files.client_ip(request) == "203.0.113.7"


def test_client_ip_without_the_header_is_the_connection():
    # running locally, nothing sits in front of the app
    assert files.client_ip(make_request("127.0.0.1")) == "127.0.0.1"


def test_sweep_loop_runs_repeatedly_and_survives_errors(monkeypatch):
    calls = []

    def fake_sweep():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("R2 unreachable")

    monkeypatch.setattr(files, "sweep", fake_sweep)

    async def run_until_three_calls():
        task = asyncio.create_task(files.sweep_loop(interval=0))
        while len(calls) < 3:
            await asyncio.sleep(0.01)
        task.cancel()

    asyncio.run(asyncio.wait_for(run_until_three_calls(), timeout=5))
    assert len(calls) >= 3
