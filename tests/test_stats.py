"""
Spec for the all-time counters: one JSON object in a bucket of its own (no
lifecycle rule), bumped after a successful complete or download.
"""

import io
import json

import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber
from fastapi.testclient import TestClient

from beam.main import app
from beam.routers import files
# imported before conftest swaps files.bump for a recorder
from beam.routers.files import bump as real_bump


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def r2():
    with Stubber(files.s3) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()


def body(data):
    raw = json.dumps(data).encode()
    return StreamingBody(io.BytesIO(raw), len(raw))


def expect_get(r2, counts):
    r2.add_response(
        "get_object",
        {"Body": body(counts)},
        {"Bucket": files.STATS_BUCKET, "Key": files.STATS_KEY},
    )


def expect_put(r2, counts):
    r2.add_response(
        "put_object",
        {},
        {"Bucket": files.STATS_BUCKET, "Key": files.STATS_KEY, "Body": json.dumps(counts).encode(), "ContentType": "application/json"},
    )


def test_bump_increments_the_stored_count(r2):
    expect_get(r2, {"uploads": 41, "downloads": 7})
    expect_put(r2, {"uploads": 42, "downloads": 7})
    real_bump("uploads")


def test_first_bump_starts_from_zero(r2):
    r2.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
    expect_put(r2, {"uploads": 0, "downloads": 1})
    real_bump("downloads")


def test_bump_skips_when_r2_errors_instead_of_overwriting(r2):
    # writing {"uploads": 1} here would wipe the real total
    r2.add_client_error("get_object", service_error_code="InternalError", http_status_code=500)
    real_bump("uploads")  # no put queued, and no exception


def test_bump_survives_a_failed_write(r2):
    expect_get(r2, {"uploads": 1, "downloads": 0})
    r2.add_client_error("put_object", service_error_code="InternalError", http_status_code=500)
    real_bump("uploads")


def test_complete_counts_an_upload(client, r2, counted):
    r2.add_response("list_parts", {"Parts": [{"PartNumber": 1, "ETag": '"e1"', "Size": 10}]}, None)
    r2.add_response("complete_multipart_upload", {}, None)
    r = client.post("/uploads/abc123/complete", json={"upload_id": "u", "parts": [{"part_number": 1, "etag": '"e1"'}]})
    assert r.status_code == 200
    assert counted == ["uploads"]


def test_failed_complete_counts_nothing(client, r2, counted):
    r2.add_response("list_parts", {"Parts": [{"PartNumber": 1, "ETag": '"e1"', "Size": 10}]}, None)
    r = client.post("/uploads/abc123/complete", json={"upload_id": "u", "parts": [{"part_number": 1, "etag": '"wrong"'}]})
    assert r.status_code == 400
    assert counted == []


def test_download_counts_a_download(client, r2, counted):
    r2.add_response("head_object", {"Metadata": {"filename": "a.txt"}, "ContentLength": 3}, None)
    r = client.get("/f/abc123", follow_redirects=False)
    assert r.status_code == 307
    assert counted == ["downloads"]


def test_missing_file_download_counts_nothing(client, r2, counted):
    r2.add_client_error("head_object", service_error_code="404", http_status_code=404)
    r = client.get("/f/abc123", follow_redirects=False)
    assert r.status_code == 404
    assert counted == []


def test_info_lookup_is_not_a_download(client, r2, counted):
    r2.add_response("head_object", {"Metadata": {"filename": "a.txt"}, "ContentLength": 3}, None)
    assert client.get("/f/abc123/info").status_code == 200
    assert counted == []
