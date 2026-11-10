"""
Spec for multi-file shares over presigned multipart uploads. R2 is faked with
botocore's Stubber, so these run offline in about a second: `uv run pytest -v`.

A share is up to 10 files, 10 GiB in total, stored as `share_id/index/name`.
One start call declares every file and signs everything; complete, abort and
download are per file; the share page lists whatever finished.

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
from botocore.exceptions import EndpointConnectionError
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

SHARE = "abc123"
KEY = f"{SHARE}/0/a.bin"


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


def f(name="a.bin", size=10, content_type="application/octet-stream"):
    return {"filename": name, "size": size, "content_type": content_type}


def start(client, *specs, token="ok"):
    body = {"files": list(specs)}
    if token is not None:
        body["turnstile_token"] = token
    return client.post("/uploads", json=body)


def expect_create(r2, content_type="application/octet-stream", upload_id="upload-123"):
    r2.add_response(
        "create_multipart_upload",
        {"Bucket": "beam", "Key": "anything", "UploadId": upload_id},
        # the name lives in the key now, so there's no filename metadata
        {"Bucket": "beam", "Key": ANY, "ContentType": content_type},
    )


def expect_find(r2, uploads, index=0, share=SHARE):
    """The in-progress uploads R2 has under share/index/, as (key, upload_id) pairs.
    Like real R2, the listing shows a re-encoded upload id, never the one create returned."""
    r2.add_response(
        "list_multipart_uploads",
        {"Uploads": [{"Key": key, "UploadId": f"listed-{upload_id}-reencoded"} for key, upload_id in uploads]},
        {"Bucket": "beam", "Prefix": f"{share}/{index}/"},
    )


def expect_list_parts(r2, parts, key=KEY, upload_id="upload-123"):
    r2.add_response(
        "list_parts",
        {"Parts": [{"PartNumber": n, "ETag": etag, "Size": size} for n, etag, size in parts]},
        {"Bucket": "beam", "Key": key, "UploadId": upload_id},
    )


def expect_listing(r2, objects, prefix=f"{SHARE}/"):
    """The finished objects R2 has under prefix, as (key, size) pairs."""
    r2.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": key, "Size": size} for key, size in objects]} if objects else {},
        {"Bucket": "beam", "Prefix": prefix},
    )


def complete(client, parts=((1, '"e1"'),), index=0, upload_id="upload-123"):
    return client.post(
        f"/uploads/{SHARE}/{index}/complete",
        json={"upload_id": upload_id, "parts": [{"part_number": n, "etag": e} for n, e in parts]},
    )


def abort(client, index=0, upload_id="upload-123"):
    return client.post(f"/uploads/{SHARE}/{index}/abort", params={"upload_id": upload_id})


# ── POST /uploads (start) ────────────────────────────────────────────────────


def test_start_makes_one_share_with_an_upload_per_file(client, r2, presigned):
    expect_create(r2, "video/quicktime", upload_id="upload-a")
    expect_create(r2, "text/plain", upload_id="upload-b")

    r = start(client, f("big.mov", 3 * GiB, "video/quicktime"), f("notes.txt", 10, "text/plain"))

    assert r.status_code == 200
    body = r.json()
    share_id = body["share_id"]
    assert len(share_id) == 22  # 128 random bits, URL-safe
    assert body["part_size"] == PART_SIZE
    a, b = body["files"]
    assert (a["index"], a["filename"], a["upload_id"], len(a["part_urls"])) == (0, "big.mov", "upload-a", 48)
    assert (b["index"], b["filename"], b["upload_id"], len(b["part_urls"])) == (1, "notes.txt", "upload-b", 1)
    keys = {c["params"]["Key"] for c in presigned}
    assert keys == {f"{share_id}/0/big.mov", f"{share_id}/1/notes.txt"}


def test_part_urls_are_signed_for_exact_sizes(client, r2, presigned):
    # 100 MiB + 1 byte → one full 64 MiB part and a smaller last part
    size = 100 * MiB + 1
    expect_create(r2, "application/zip")

    r = start(client, f("a.zip", size, "application/zip"))

    assert r.status_code == 200
    key = f"{r.json()['share_id']}/0/a.zip"
    assert [c["method"] for c in presigned] == ["upload_part", "upload_part"]
    assert [c["params"]["PartNumber"] for c in presigned] == [1, 2]
    assert [c["params"]["ContentLength"] for c in presigned] == [PART_SIZE, size - PART_SIZE]
    for c in presigned:
        assert c["params"]["Bucket"] == "beam"
        assert c["params"]["Key"] == key
        assert c["params"]["UploadId"] == "upload-123"
        assert c["expires"] == URL_LIFETIME


def test_part_urls_make_r2_enforce_content_length(client, r2, presigned):
    expect_create(r2, "text/plain")

    r = start(client, f("a.txt", 10, "text/plain"))

    url = r.json()["files"][0]["part_urls"][0]
    signed_headers = parse_qs(urlparse(url).query)["X-Amz-SignedHeaders"][0].split(";")
    assert "content-length" in signed_headers


def test_exactly_10_gib_in_total_is_allowed(client, r2, presigned):
    expect_create(r2)
    expect_create(r2)

    r = start(client, f("a.bin", 4 * GiB), f("b.bin", 6 * GiB))

    assert r.status_code == 200
    assert sum(len(x["part_urls"]) for x in r.json()["files"]) == 160


def test_over_10_gib_in_total_is_refused_before_touching_r2(client, r2, presigned):
    # each file is small enough alone; together they're one byte over
    r = start(client, f("a.bin", 4 * GiB), f("b.bin", 6 * GiB + 1))

    assert r.status_code == 413
    assert presigned == []
    assert files.total_bytes == 0


def test_one_file_over_10_gib_is_refused(client, r2, presigned):
    r = start(client, f("huge.bin", MAX_SIZE + 1))

    assert r.status_code == 413


def test_ten_files_are_allowed(client, r2, presigned):
    for _ in range(10):
        expect_create(r2)

    r = start(client, *[f(f"{i}.txt") for i in range(10)])

    assert r.status_code == 200
    assert [x["index"] for x in r.json()["files"]] == list(range(10))


def test_eleven_files_are_refused(client, r2, presigned):
    r = start(client, *[f(f"{i}.txt") for i in range(11)])

    assert r.status_code == 422
    assert presigned == []


def test_a_share_needs_at_least_one_file(client, r2):
    assert start(client).status_code == 422


@pytest.mark.parametrize("size", [0, -5])
def test_empty_or_negative_size_is_rejected(client, r2, size):
    assert start(client, f(size=size)).status_code == 422


def test_same_names_get_their_own_keys(client, r2, presigned):
    expect_create(r2)
    expect_create(r2)

    r = start(client, f("photo.jpg"), f("photo.jpg"))

    share_id = r.json()["share_id"]
    assert {c["params"]["Key"] for c in presigned} == {f"{share_id}/0/photo.jpg", f"{share_id}/1/photo.jpg"}


def test_start_cleans_the_name_that_goes_into_the_key(client, r2, presigned):
    expect_create(r2)

    r = start(client, f("../evil/x.txt"))

    share_id = r.json()["share_id"]
    assert r.json()["files"][0]["filename"] == ".._evil_x.txt"
    assert presigned[0]["params"]["Key"] == f"{share_id}/0/.._evil_x.txt"


# ── filename cleanup ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, clean",
    [
        ("report.pdf", "report.pdf"),
        ("a/b\\c.txt", "a_b_c.txt"),
        ("line\nbreak\x00.txt", "line_break_.txt"),
        ("  spaced.txt  ", "spaced.txt"),
        ("résumé 日本.docx", "résumé 日本.docx"),
        ("", "file"),
        ("   ", "file"),
        # browsers collapse dot segments in URLs, which breaks the signed key
        (".", "file"),
        ("..", "file"),
        ("...", "file"),
        ("..notes.txt", "..notes.txt"),
        # invisible characters that can disguise the extension
        ("a\u202egpj.exe", "a_gpj.exe"),  # right-to-left override: shows as "aexe.jpg"
        ("a\u200bb.txt", "a_b.txt"),  # zero-width space
        ("a\u2028b.txt", "a_b.txt"),  # line separator
    ],
)
def test_clean_name(raw, clean):
    assert files.clean_name(raw) == clean


def test_long_names_are_trimmed_but_keep_their_extension():
    name = files.clean_name("x" * 300 + ".pdf")

    assert len(name.encode()) <= files.NAME_LIMIT
    assert name.endswith(".pdf")


def test_trimming_never_splits_a_character():
    # 3 bytes each in UTF-8; a cut mid-character would leave invalid bytes
    name = files.clean_name("日" * 100 + ".txt")

    assert len(name.encode()) <= files.NAME_LIMIT
    assert name.endswith(".txt")
    assert set(name[:-4]) == {"日"}


def test_a_long_name_without_an_extension_is_just_trimmed():
    name = files.clean_name("y" * 300)

    assert name == "y" * files.NAME_LIMIT


# ── POST /uploads/{share_id}/{index}/complete ────────────────────────────────


def test_complete_joins_the_parts(client, r2):
    expect_find(r2, [(KEY, "upload-123")])
    expect_list_parts(r2, [(1, '"e1"', PART_SIZE), (2, '"e2"', 5)])
    r2.add_response(
        "complete_multipart_upload",
        {},
        {
            "Bucket": "beam",
            "Key": KEY,
            "UploadId": "upload-123",
            "MultipartUpload": {"Parts": [{"PartNumber": 1, "ETag": '"e1"'}, {"PartNumber": 2, "ETag": '"e2"'}]},
        },
    )

    r = complete(client, [(2, '"e2"'), (1, '"e1"')])

    assert r.status_code == 200
    assert r.json() == {"share_id": SHARE, "index": 0}


def test_complete_finds_the_key_even_after_a_restart(client, r2):
    # no record in memory (the dyno restarted mid-upload); R2 still knows the key
    expect_find(r2, [("abc123/3/thesis.pdf", "upload-9")], index=3)
    expect_list_parts(r2, [(1, '"e1"', 5)], key="abc123/3/thesis.pdf", upload_id="upload-9")
    r2.add_response("complete_multipart_upload", {}, None)

    r = complete(client, index=3, upload_id="upload-9")

    assert r.status_code == 200


def test_complete_refuses_when_r2_holds_more_than_10_gib(client, r2):
    expect_find(r2, [(KEY, "upload-123")])
    expect_list_parts(r2, [(1, '"e1"', 6 * GiB), (2, '"e2"', 5 * GiB)])
    # an oversized upload can never be fixed, so its parts are discarded right away
    r2.add_response("abort_multipart_upload", {}, {"Bucket": "beam", "Key": KEY, "UploadId": "upload-123"})

    r = complete(client, [(1, '"e1"'), (2, '"e2"')])

    assert r.status_code == 413  # aborted, and complete_multipart_upload was never called


def test_complete_refuses_when_a_part_is_missing(client, r2):
    expect_find(r2, [(KEY, "upload-123")])
    expect_list_parts(r2, [(1, '"e1"', PART_SIZE)])

    r = complete(client, [(1, '"e1"'), (2, '"e2"')])

    assert r.status_code == 400


def test_complete_unknown_upload_is_404(client, r2):
    expect_find(r2, [])

    assert complete(client).status_code == 404


def test_complete_ignores_an_upload_outside_this_share(client, r2):
    # if R2 ever returned an upload outside the prefix, matching the id alone isn't enough
    expect_find(r2, [("other-share/0/a.bin", "upload-123")])

    assert complete(client).status_code == 404


def test_complete_with_someone_elses_upload_id_is_404(client, r2):
    # an upload exists at this index, but R2 rejects the id the client sent for that key
    expect_find(r2, [(KEY, "upload-123")])
    r2.add_client_error("list_parts", service_error_code="NoSuchUpload", http_status_code=404)

    assert complete(client, upload_id="made-up").status_code == 404


# ── POST /uploads/{share_id}/{index}/abort ───────────────────────────────────


def test_abort_discards_the_parts(client, r2):
    expect_find(r2, [(KEY, "upload-123")])
    r2.add_response("abort_multipart_upload", {}, {"Bucket": "beam", "Key": KEY, "UploadId": "upload-123"})

    r = abort(client)

    assert r.status_code == 204
    assert r.content == b""  # 204 means no body


def test_abort_of_finished_upload_still_succeeds(client, r2):
    # already completed or aborted: nothing in progress, nothing left to do
    expect_find(r2, [])

    assert abort(client).status_code == 204


def test_abort_racing_another_abort_still_succeeds(client, r2):
    expect_find(r2, [(KEY, "upload-123")])
    r2.add_client_error("abort_multipart_upload", service_error_code="NoSuchUpload", http_status_code=404)

    assert abort(client).status_code == 204


# ── GET /f/{share_id}/info and /f/{share_id}/{index} ─────────────────────────


def test_info_lists_the_finished_files_in_order(client, r2):
    # file 1 never finished, so R2 doesn't list it; the share shows the other two
    expect_listing(r2, [("abc123/2/b.txt", 5), ("abc123/0/a b.png", 1234)])

    r = client.get(f"/f/{SHARE}/info")

    assert r.status_code == 200
    assert r.json() == {
        "share_id": SHARE,
        "files": [
            {"index": 0, "filename": "a b.png", "size": 1234},
            {"index": 2, "filename": "b.txt", "size": 5},
        ],
    }


def test_info_of_unknown_share_is_404(client, r2):
    expect_listing(r2, [])

    assert client.get(f"/f/{SHARE}/info").status_code == 404


def test_download_redirects_to_that_one_file(client, r2, presigned):
    expect_listing(r2, [("abc123/1/résumé.pdf", 10)], prefix=f"{SHARE}/1/")

    r = client.get(f"/f/{SHARE}/1", follow_redirects=False)

    assert r.status_code == 307
    (call,) = presigned
    assert call["method"] == "get_object"
    assert call["params"]["Key"] == "abc123/1/résumé.pdf"
    assert call["params"]["ResponseContentDisposition"] == f"attachment; filename*=UTF-8''{quote('résumé.pdf', safe='')}"
    assert call["expires"] == 600


def test_download_of_missing_file_is_404(client, r2):
    expect_listing(r2, [], prefix=f"{SHARE}/4/")

    assert client.get(f"/f/{SHARE}/4", follow_redirects=False).status_code == 404


def test_old_single_file_download_is_gone(client):
    assert client.get(f"/f/{SHARE}", follow_redirects=False).status_code == 404


# ── the old relay endpoint ───────────────────────────────────────────────────


def test_old_upload_endpoint_is_gone(client):
    r = client.post("/upload")

    assert r.status_code in (404, 405)


# ── abuse limits: Turnstile, holds, settling, sweeping ──────────────────────
#
# Every start holds the share's declared total against the uploader's IP and
# the global total, with one record per file. Complete settles a file's hold to
# its real size; abort and the sweeper release it. The record in files.uploads
# is the ticket: whoever removes it adjusts the counters, so a hold is released
# exactly once.

IP = "testclient"  # what TestClient reports as the client address
PER_IP_LIMIT = 50 * GiB
GLOBAL_LIMIT = 1024 * GiB
SWEEP_AFTER = 7 * 60 * 60


def hold(key=KEY, upload_id="upload-123", ip=IP, size=100 * MiB, started_at=None):
    """Put a file in the state start leaves it in: record written, size held."""
    files.uploads[key] = {
        "upload_id": upload_id,
        "ip": ip,
        "size": size,
        "started_at": files.time.time() if started_at is None else started_at,
    }
    files.ip_bytes[ip] = files.ip_bytes.get(ip, 0) + size
    files.total_bytes += size


def test_start_without_token_is_403_before_anything(client, r2, fresh_limits):
    r = start(client, f(), token=None)

    assert r.status_code == 403
    assert fresh_limits == []  # no point asking Cloudflare about nothing
    assert files.total_bytes == 0


def test_start_with_invalid_token_is_403(client, r2, presigned):
    r = start(client, f(), token="forged")

    assert r.status_code == 403
    assert presigned == []
    assert files.total_bytes == 0


def test_start_holds_the_declared_total_with_a_record_per_file(client, r2, presigned):
    expect_create(r2, upload_id="upload-a")
    expect_create(r2, upload_id="upload-b")

    r = start(client, f("a.bin", 3 * GiB), f("b.bin", 1 * GiB))

    assert r.status_code == 200
    share_id = r.json()["share_id"]
    assert files.ip_bytes[IP] == 4 * GiB
    assert files.total_bytes == 4 * GiB
    a = files.uploads[f"{share_id}/0/a.bin"]
    b = files.uploads[f"{share_id}/1/b.bin"]
    assert (a["upload_id"], a["ip"], a["size"]) == ("upload-a", IP, 3 * GiB)
    assert (b["upload_id"], b["ip"], b["size"]) == ("upload-b", IP, 1 * GiB)


def test_start_up_to_the_ip_limit_is_allowed(client, r2, presigned):
    files.ip_bytes[IP] = PER_IP_LIMIT - 10
    files.total_bytes = PER_IP_LIMIT - 10
    expect_create(r2)

    r = start(client, f(size=10))

    assert r.status_code == 200
    assert files.ip_bytes[IP] == PER_IP_LIMIT


def test_start_over_the_ip_limit_is_429_and_holds_nothing(client, r2, presigned):
    files.ip_bytes[IP] = PER_IP_LIMIT - 10
    files.total_bytes = PER_IP_LIMIT - 10

    r = start(client, f(size=5), f(size=6))

    assert r.status_code == 429
    assert presigned == []  # nothing queued on r2 either: R2 is never touched
    assert files.ip_bytes[IP] == PER_IP_LIMIT - 10
    assert files.total_bytes == PER_IP_LIMIT - 10


def test_start_over_the_global_cap_is_429(client, r2, presigned):
    # other IPs have used up nearly everything; this IP has used nothing
    files.total_bytes = GLOBAL_LIMIT - 10

    r = start(client, f(size=11))

    assert r.status_code == 429
    assert IP not in files.ip_bytes
    assert files.total_bytes == GLOBAL_LIMIT - 10


def test_start_cleans_up_if_r2_fails_partway(client, r2, presigned):
    # the first file's upload was created, the second's failed
    expect_create(r2, upload_id="upload-a")
    r2.add_client_error("create_multipart_upload", service_error_code="InternalError", http_status_code=500)
    r2.add_response("abort_multipart_upload", {}, {"Bucket": "beam", "Key": ANY, "UploadId": "upload-a"})

    with pytest.raises(Exception):
        start(client, f("a.bin", 3 * GiB), f("b.bin", 1 * GiB))

    assert files.total_bytes == 0
    assert IP not in files.ip_bytes
    assert files.uploads == {}


def test_start_releases_the_hold_even_if_cleanup_fails(client, r2, presigned, monkeypatch):
    # R2 drops the connection: the second create fails, and so does the undo of the first
    expect_create(r2, upload_id="upload-a")
    r2.add_client_error("create_multipart_upload", service_error_code="InternalError", http_status_code=500)

    def unreachable(**kwargs):
        raise EndpointConnectionError(endpoint_url="https://r2.example")

    monkeypatch.setattr(files.s3, "abort_multipart_upload", unreachable)

    with pytest.raises(Exception):
        start(client, f("a.bin", 3 * GiB), f("b.bin", 1 * GiB))

    assert files.total_bytes == 0
    assert IP not in files.ip_bytes


def test_complete_settles_the_hold_to_the_real_size(client, r2):
    # declared 200 MiB, but only 70 MiB actually landed in R2
    hold(size=200 * MiB)
    expect_find(r2, [(KEY, "upload-123")])
    expect_list_parts(r2, [(1, '"e1"', PART_SIZE), (2, '"e2"', 6 * MiB)])
    r2.add_response("complete_multipart_upload", {}, None)

    r = complete(client, [(1, '"e1"'), (2, '"e2"')])

    assert r.status_code == 200
    assert files.ip_bytes[IP] == 70 * MiB
    assert files.total_bytes == 70 * MiB
    assert KEY not in files.uploads  # settled, so the sweeper leaves it alone


def test_completing_one_file_leaves_the_others_held(client, r2):
    hold(size=200 * MiB)
    hold(key="abc123/1/b.bin", upload_id="upload-b", size=1 * GiB)
    expect_find(r2, [(KEY, "upload-123")])
    expect_list_parts(r2, [(1, '"e1"', 200 * MiB)])
    r2.add_response("complete_multipart_upload", {}, None)

    assert complete(client).status_code == 200
    assert files.total_bytes == 200 * MiB + 1 * GiB
    assert set(files.uploads) == {"abc123/1/b.bin"}


def test_complete_413_releases_the_whole_hold(client, r2):
    hold(size=10 * GiB)
    expect_find(r2, [(KEY, "upload-123")])
    expect_list_parts(r2, [(1, '"e1"', 6 * GiB), (2, '"e2"', 5 * GiB)])
    r2.add_response("abort_multipart_upload", {}, None)

    r = complete(client, [(1, '"e1"'), (2, '"e2"')])

    assert r.status_code == 413
    assert files.total_bytes == 0
    assert files.uploads == {}


def test_complete_mismatch_keeps_the_hold_so_the_client_can_retry(client, r2):
    hold(size=200 * MiB)
    expect_find(r2, [(KEY, "upload-123")])
    expect_list_parts(r2, [(1, '"e1"', PART_SIZE)])

    r = complete(client, [(1, '"e1"'), (2, '"e2"')])

    assert r.status_code == 400
    assert files.total_bytes == 200 * MiB
    assert KEY in files.uploads


def test_abort_releases_the_hold_once(client, r2):
    hold(size=200 * MiB)
    expect_find(r2, [(KEY, "upload-123")])
    r2.add_response("abort_multipart_upload", {}, None)
    # the second time, R2 no longer has the upload
    expect_find(r2, [])

    first = abort(client)
    # the Cancel button and the tab-close beacon can both fire
    second = abort(client)

    assert first.status_code == second.status_code == 204
    assert files.total_bytes == 0  # not negative
    assert IP not in files.ip_bytes
    assert files.uploads == {}


def test_abort_with_wrong_upload_id_releases_nothing(client, r2):
    # someone pairs your share and index with a made-up upload_id; R2 refuses the pair
    hold(size=200 * MiB)
    expect_find(r2, [(KEY, "upload-123")])
    r2.add_client_error("abort_multipart_upload", service_error_code="NoSuchUpload", http_status_code=404)

    r = abort(client, upload_id="made-up")

    assert r.status_code == 204
    assert files.total_bytes == 200 * MiB
    assert KEY in files.uploads


def test_sweep_aborts_and_releases_only_old_uploads(r2):
    now = 1_000_000.0
    hold("old/0/a", "upload-old", size=5 * GiB, started_at=now - SWEEP_AFTER - 1)
    hold("young/0/a", "upload-young", size=1 * GiB, started_at=now - SWEEP_AFTER + 60)
    r2.add_response("abort_multipart_upload", {}, {"Bucket": "beam", "Key": "old/0/a", "UploadId": "upload-old"})

    files.sweep(now=now)

    assert set(files.uploads) == {"young/0/a"}
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

    assert KEY in files.uploads
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
