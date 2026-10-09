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

from urllib.parse import parse_qs, quote, urlparse

import pytest
from botocore.stub import ANY, Stubber
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

    r = client.post("/uploads", json={"filename": "big.mov", "size": 3 * GiB, "content_type": "video/quicktime"})

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

    r = client.post("/uploads", json={"filename": "a.zip", "size": size, "content_type": "application/zip"})

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

    r = client.post("/uploads", json={"filename": "a.txt", "size": 10, "content_type": "text/plain"})

    url = r.json()["part_urls"][0]
    signed_headers = parse_qs(urlparse(url).query)["X-Amz-SignedHeaders"][0].split(";")
    assert "content-length" in signed_headers


def test_small_file_is_a_single_part(client, r2, presigned):
    expect_create(r2, "note.txt", "text/plain")

    r = client.post("/uploads", json={"filename": "note.txt", "size": 10, "content_type": "text/plain"})

    assert len(r.json()["part_urls"]) == 1
    assert presigned[0]["params"]["ContentLength"] == 10


def test_exactly_10_gib_is_allowed(client, r2, presigned):
    expect_create(r2, "max.bin", "application/octet-stream")

    r = client.post("/uploads", json={"filename": "max.bin", "size": MAX_SIZE, "content_type": "application/octet-stream"})

    assert r.status_code == 200
    assert len(r.json()["part_urls"]) == 160


def test_over_10_gib_is_refused_before_touching_r2(client, r2, presigned):
    # nothing queued on r2: any R2 call here fails the test
    r = client.post("/uploads", json={"filename": "huge.bin", "size": MAX_SIZE + 1, "content_type": "application/octet-stream"})

    assert r.status_code == 413
    assert presigned == []


@pytest.mark.parametrize("size", [0, -5])
def test_empty_or_negative_size_is_rejected(client, r2, size):
    r = client.post("/uploads", json={"filename": "x", "size": size, "content_type": "text/plain"})

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

    r = client.post(
        "/uploads/abc123/complete",
        json={"upload_id": "upload-123", "parts": [{"part_number": 1, "etag": '"e1"'}, {"part_number": 2, "etag": '"e2"'}]},
    )

    assert r.status_code == 413  # and complete_multipart_upload was never called


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


# ── the old relay endpoint ───────────────────────────────────────────────────


def test_old_upload_endpoint_is_gone(client):
    r = client.post("/upload")

    assert r.status_code in (404, 405)
