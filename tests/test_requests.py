"""
Spec for file requests. A requester writes a note, gets a public link to hand
out and an owner key to keep. People with the public link send files into the
request; who can see those files depends on the request's private switch.

R2 layout:
    requests/{request_id}/note                                  JSON, the request itself
    requests/{request_id}/{share_id}/{sender}/{filename}/{index} one per sent file

Same fakes as test_uploads.py (see its docstring): R2 via Stubber, Turnstile
accepts "ok".
"""

import io
import json
import time
from datetime import datetime, timezone
from urllib.parse import quote

import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY

from beam.routers import files

GiB = 1024**3
MiB = 1024**2
DAY = 24 * 60 * 60

REQ = "req456req456req456req4"
OWNER = "own789own789own789own7"
SHARE = "shr000shr000shr000shr0"
SHARE2 = "shr111shr111shr111shr1"
PREFIX = f"requests/{REQ}/"
NOTE_KEY = f"{PREFIX}note"
IP = "testclient"


def note(private=False, created_at=None, name="Ara", text="Send me your slides"):
    return {
        "note": text,
        "name": name,
        "private": private,
        "owner_key": OWNER,
        "created_at": time.time() - 60 if created_at is None else created_at,
    }


def expect_note(r2, body):
    data = json.dumps(body).encode()
    r2.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(data), len(data)), "ContentLength": len(data)},
        {"Bucket": "beam", "Key": NOTE_KEY},
    )


def expect_no_note(r2):
    r2.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)


def expect_listing(r2, objects, prefix=PREFIX, token=None, next_token=None):
    """objects: (key, size, uploaded_at) triples."""
    response = {"Contents": [{"Key": k, "Size": s, "LastModified": t} for k, s, t in objects]} if objects else {}
    if next_token:
        response.update(IsTruncated=True, NextContinuationToken=next_token)
    params = {"Bucket": "beam", "Prefix": prefix}
    if token:
        params["ContinuationToken"] = token
    r2.add_response("list_objects_v2", response, params)


def expect_create(r2, upload_id="upload-123"):
    r2.add_response(
        "create_multipart_upload",
        {"Bucket": "beam", "Key": "anything", "UploadId": upload_id},
        {"Bucket": "beam", "Key": ANY, "ContentType": "application/octet-stream"},
    )


def f(name="a.bin", size=10):
    return {"filename": name, "size": size, "content_type": "application/octet-stream"}


def create(client, **overrides):
    body = {"note": "Send me your slides", "name": "Ara", "private": False, "turnstile_token": "ok"}
    body.update(overrides)
    return client.post("/requests", json={k: v for k, v in body.items() if v is not None})


def send(client, *specs, sender="Alex", token="ok"):
    body = {"files": list(specs), "turnstile_token": token}
    if sender is not None:
        body["sender"] = sender
    return client.post(f"/r/{REQ}/uploads", json=body)


@pytest.fixture
def put_params():
    """Records the params of every put_object, while the Stubber still checks the call."""
    seen = []

    def record(params, **kwargs):
        seen.append(dict(params))

    files.s3.meta.events.register("before-parameter-build.s3.PutObject", record)
    yield seen
    files.s3.meta.events.unregister("before-parameter-build.s3.PutObject", record)


def expect_put(r2):
    r2.add_response("put_object", {}, {"Bucket": "beam", "Key": ANY, "Body": ANY, "ContentType": "application/json"})


# ── POST /requests (create) ──────────────────────────────────────────────────


def test_create_stores_the_request_and_returns_both_ids(client, r2, put_params):
    expect_put(r2)
    before = time.time()

    r = create(client, note="Send me your slides", name="Ara", private=True)

    assert r.status_code == 200
    body = r.json()
    request_id, owner_key = body["request_id"], body["owner_key"]
    assert len(request_id) == len(owner_key) == 22
    assert request_id != owner_key
    (put,) = put_params
    assert put["Key"] == f"requests/{request_id}/note"
    stored = json.loads(put["Body"])
    assert stored["note"] == "Send me your slides"
    assert stored["name"] == "Ara"
    assert stored["private"] is True
    assert stored["owner_key"] == owner_key
    assert before <= stored["created_at"] <= time.time()


def test_private_defaults_to_off_and_name_is_optional(client, r2, put_params):
    expect_put(r2)

    r = client.post("/requests", json={"note": "hi", "turnstile_token": "ok"})

    assert r.status_code == 200
    stored = json.loads(put_params[0]["Body"])
    assert stored["private"] is False
    assert stored["name"] is None


def test_create_without_a_valid_token_is_403_and_stores_nothing(client, r2):
    assert create(client, turnstile_token="forged").status_code == 403


@pytest.mark.parametrize("text", ["", "   ", "x" * 501])
def test_note_must_be_present_and_short(client, r2, text):
    assert create(client, note=text).status_code == 422


def test_note_of_500_characters_is_allowed(client, r2):
    expect_put(r2)
    assert create(client, note="x" * 500).status_code == 200


def test_requester_name_over_50_characters_is_refused(client, r2):
    assert create(client, name="x" * 51).status_code == 422


def test_requester_name_loses_invisible_characters(client, r2, put_params):
    # right-to-left override and friends could make the name display as something else
    expect_put(r2)

    create(client, name="  Ara‮jen  ")

    assert json.loads(put_params[0]["Body"])["name"] == "Ara_jen"


def test_note_keeps_line_breaks_but_loses_invisible_characters(client, r2, put_params):
    expect_put(r2)

    create(client, note="line one\nline‮ two")

    assert json.loads(put_params[0]["Body"])["note"] == "line one\nline_ two"


# ── GET /r/{request_id}/info ─────────────────────────────────────────────────

AT1 = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)
AT2 = datetime(2026, 11, 11, 11, 0, tzinfo=timezone.utc)

TWO_SENDS = [
    (NOTE_KEY, 120, AT1),
    # Sam sent later, but R2 lists keys alphabetically, so Sam's share comes first here
    (f"{PREFIX}{SHARE2}/Sam/c.pdf/0", 30, AT2),
    (f"{PREFIX}{SHARE}/Alex/b.txt/1", 20, AT1),
    (f"{PREFIX}{SHARE}/Alex/a b.png/0", 10, AT1),
]

GROUPED = [
    {"share_id": SHARE, "sender": "Alex", "files": [
        {"index": 0, "filename": "a b.png", "size": 10},
        {"index": 1, "filename": "b.txt", "size": 20},
    ]},
    {"share_id": SHARE2, "sender": "Sam", "files": [
        {"index": 0, "filename": "c.pdf", "size": 30},
    ]},
]


def test_public_request_shows_everyone_the_files_grouped_by_send(client, r2):
    created = time.time() - 60
    expect_note(r2, note(created_at=created))
    expect_listing(r2, TWO_SENDS)

    r = client.get(f"/r/{REQ}/info")

    assert r.status_code == 200
    assert r.json() == {
        "request_id": REQ,
        "note": "Send me your slides",
        "name": "Ara",
        "private": False,
        "open": True,
        "closes_at": created + DAY,
        "is_owner": False,
        "sends": GROUPED,
    }


def test_info_never_returns_the_owner_key(client, r2):
    expect_note(r2, note())
    expect_listing(r2, [])

    assert OWNER not in client.get(f"/r/{REQ}/info").text


def test_private_request_hides_files_from_the_public_link(client, r2):
    # no listing is queued: the files must not even be looked up
    expect_note(r2, note(private=True))

    r = client.get(f"/r/{REQ}/info")

    assert r.status_code == 200
    assert r.json()["sends"] is None
    assert r.json()["is_owner"] is False
    assert r.json()["note"] == "Send me your slides"


def test_private_request_with_a_wrong_key_still_hides_files(client, r2):
    expect_note(r2, note(private=True))

    r = client.get(f"/r/{REQ}/info", params={"key": "wrongwrongwrongwrongwr"})

    assert r.json()["sends"] is None
    assert r.json()["is_owner"] is False


def test_private_request_shows_files_to_the_owner(client, r2):
    expect_note(r2, note(private=True))
    expect_listing(r2, TWO_SENDS)

    r = client.get(f"/r/{REQ}/info", params={"key": OWNER})

    assert r.json()["sends"] == GROUPED
    assert r.json()["is_owner"] is True


def test_owner_is_recognised_on_a_public_request_too(client, r2):
    expect_note(r2, note())
    expect_listing(r2, [])

    assert client.get(f"/r/{REQ}/info", params={"key": OWNER}).json()["is_owner"] is True


def test_request_over_a_day_old_is_closed(client, r2):
    expect_note(r2, note(created_at=time.time() - DAY - 1))
    expect_listing(r2, [])

    assert client.get(f"/r/{REQ}/info").json()["open"] is False


def test_info_reads_every_page_of_the_listing(client, r2):
    # R2 returns at most 1000 keys per call
    expect_note(r2, note())
    expect_listing(r2, TWO_SENDS[:2], next_token="page2")
    expect_listing(r2, TWO_SENDS[2:], token="page2")

    assert client.get(f"/r/{REQ}/info").json()["sends"] == GROUPED


def test_unknown_request_is_404(client, r2):
    expect_no_note(r2)

    assert client.get(f"/r/{REQ}/info").status_code == 404


@pytest.mark.parametrize("bad", ["short", "x" * 23, "a.b" * 7 + "c"])
def test_malformed_request_id_is_404_without_asking_r2(client, r2, bad):
    assert client.get(f"/r/{bad}/info").status_code == 404


# ── POST /r/{request_id}/uploads (send) ──────────────────────────────────────


def test_send_makes_a_share_inside_the_request(client, r2, presigned):
    expect_note(r2, note())
    expect_create(r2, upload_id="upload-a")
    expect_create(r2, upload_id="upload-b")

    r = send(client, f("a.bin", 3 * GiB), f("notes.txt", 10), sender="Alex")

    assert r.status_code == 200
    body = r.json()
    share_id = body["share_id"]
    assert len(share_id) == 22
    a, b = body["files"]
    assert (a["index"], a["filename"], a["upload_id"], len(a["part_urls"])) == (0, "a.bin", "upload-a", 48)
    assert (b["index"], b["filename"], b["upload_id"]) == (1, "notes.txt", "upload-b")
    keys = {c["params"]["Key"] for c in presigned}
    assert keys == {f"{PREFIX}{share_id}/Alex/a.bin/0", f"{PREFIX}{share_id}/Alex/notes.txt/1"}


def test_send_holds_bytes_against_the_request_too(client, r2, presigned):
    expect_note(r2, note())
    expect_create(r2)

    r = send(client, f(size=200 * MiB))

    share_id = r.json()["share_id"]
    assert files.request_bytes[REQ] == 200 * MiB
    assert files.ip_bytes[IP] == 200 * MiB
    assert files.uploads[f"{PREFIX}{share_id}/Alex/a.bin/0"]["request"] == REQ


def test_private_request_still_accepts_sends_without_the_key(client, r2, presigned):
    expect_note(r2, note(private=True))
    expect_create(r2)

    assert send(client, f()).status_code == 200


@pytest.mark.parametrize("sender", [None, "", "   "])
def test_sender_name_is_required(client, r2, sender):
    assert send(client, f(), sender=sender).status_code == 422


def test_sender_name_over_50_characters_is_refused(client, r2):
    assert send(client, f(), sender="x" * 51).status_code == 422


def test_sender_name_is_cleaned_before_it_goes_into_the_key(client, r2, presigned):
    expect_note(r2, note())
    expect_create(r2)

    r = send(client, f(), sender=" A/l‮ex ")

    share_id = r.json()["share_id"]
    assert presigned[0]["params"]["Key"] == f"{PREFIX}{share_id}/A_l_ex/a.bin/0"


def test_send_without_a_valid_token_is_403_before_reading_the_request(client, r2):
    assert send(client, f(), token="forged").status_code == 403


def test_send_to_unknown_request_is_404(client, r2):
    expect_no_note(r2)

    assert send(client, f()).status_code == 404


def test_send_to_a_closed_request_is_410_and_holds_nothing(client, r2, presigned):
    expect_note(r2, note(created_at=time.time() - DAY - 1))

    r = send(client, f())

    assert r.status_code == 410
    assert presigned == []
    assert files.total_bytes == 0


def test_one_send_is_still_capped_at_10_gib(client, r2):
    expect_note(r2, note())

    assert send(client, f("a", 4 * GiB), f("b", 6 * GiB + 1)).status_code == 413


def test_one_send_is_still_capped_at_10_files(client, r2):
    assert send(client, *[f(f"{i}") for i in range(11)]).status_code == 422


def test_send_up_to_25_gib_in_the_request_is_allowed(client, r2, presigned):
    files.request_bytes[REQ] = 25 * GiB - 10
    expect_note(r2, note())
    expect_create(r2)

    assert send(client, f(size=10)).status_code == 200
    assert files.request_bytes[REQ] == 25 * GiB


def test_send_over_25_gib_in_the_request_is_429_and_holds_nothing(client, r2, presigned):
    files.request_bytes[REQ] = 25 * GiB - 10
    expect_note(r2, note())

    r = send(client, f(size=11))

    assert r.status_code == 429
    assert presigned == []
    assert files.request_bytes[REQ] == 25 * GiB - 10
    assert IP not in files.ip_bytes
    assert files.total_bytes == 0


def test_the_request_cap_doesnt_touch_other_requests(client, r2, presigned):
    files.request_bytes["other-request"] = 25 * GiB
    expect_note(r2, note())
    expect_create(r2)

    assert send(client, f(size=10)).status_code == 200


# ── complete and abort inside a request ──────────────────────────────────────

SEND_PREFIX = f"{PREFIX}{SHARE}/"
KEY0 = f"{SEND_PREFIX}Alex/a.bin/0"
KEY1 = f"{SEND_PREFIX}Alex/b.bin/1"


def hold(key=KEY1, upload_id="upload-b", size=200 * MiB):
    files.uploads[key] = {"upload_id": upload_id, "ip": IP, "size": size, "started_at": time.time(), "request": REQ}
    files.ip_bytes[IP] = files.ip_bytes.get(IP, 0) + size
    files.total_bytes += size
    files.request_bytes[REQ] = files.request_bytes.get(REQ, 0) + size


def expect_find(r2, keys):
    r2.add_response(
        "list_multipart_uploads",
        {"Uploads": [{"Key": k, "UploadId": "listed-reencoded"} for k in keys]},
        {"Bucket": "beam", "Prefix": SEND_PREFIX},
    )


def complete(client, index=1, upload_id="upload-b", parts=((1, '"e1"'),)):
    return client.post(
        f"/r/{REQ}/uploads/{SHARE}/{index}/complete",
        json={"upload_id": upload_id, "parts": [{"part_number": n, "etag": e} for n, e in parts]},
    )


def test_complete_finds_the_file_by_its_index_and_settles_every_hold(client, r2, counted):
    hold(size=200 * MiB)
    expect_find(r2, [KEY0, KEY1])
    r2.add_response(
        "list_parts",
        {"Parts": [{"PartNumber": 1, "ETag": '"e1"', "Size": 70 * MiB}]},
        {"Bucket": "beam", "Key": KEY1, "UploadId": "upload-b"},
    )
    r2.add_response("complete_multipart_upload", {}, {"Bucket": "beam", "Key": KEY1, "UploadId": "upload-b", "MultipartUpload": ANY})

    r = complete(client)

    assert r.status_code == 200
    assert files.request_bytes[REQ] == 70 * MiB
    assert files.ip_bytes[IP] == 70 * MiB
    assert files.total_bytes == 70 * MiB
    assert counted == ["uploads"]


def test_complete_of_an_index_that_isnt_there_is_404(client, r2):
    # index 1 must not match a key ending in /11 or a filename like "1"
    expect_find(r2, [f"{SEND_PREFIX}Alex/1/11"])
    expect_send_listing(r2, [f"{SEND_PREFIX}Alex/1/11"])

    assert complete(client, index=1).status_code == 404


def test_abort_releases_the_request_hold(client, r2):
    hold(size=200 * MiB)
    expect_find(r2, [KEY1])
    r2.add_response("abort_multipart_upload", {}, {"Bucket": "beam", "Key": KEY1, "UploadId": "upload-b"})

    r = client.post(f"/r/{REQ}/uploads/{SHARE}/1/abort", params={"upload_id": "upload-b"})

    assert r.status_code == 204
    assert REQ not in files.request_bytes
    assert files.total_bytes == 0


def test_sweep_releases_the_request_hold(r2):
    hold(size=5 * GiB)
    files.uploads[KEY1]["started_at"] = 0
    r2.add_response("abort_multipart_upload", {}, {"Bucket": "beam", "Key": KEY1, "UploadId": "upload-b"})

    files.sweep(now=8 * 60 * 60)

    assert REQ not in files.request_bytes
    assert files.total_bytes == 0


def test_repeated_complete_of_a_finished_file_succeeds(client, r2, counted):
    # the first complete worked but its reply was lost; on a private request the
    # sender can't read the listing to find out, so the API answers for it
    expect_find(r2, [])
    expect_send_listing(r2, [KEY0, KEY1])

    r = complete(client, index=1)

    assert r.status_code == 200
    assert r.json() == {"share_id": SHARE, "index": 1}
    assert counted == []  # already counted the first time


def test_complete_of_a_file_that_never_finished_is_still_404(client, r2):
    expect_find(r2, [])
    expect_send_listing(r2, [KEY0])

    assert complete(client, index=1).status_code == 404


def test_complete_with_a_malformed_share_id_is_404(client, r2):
    r = client.post(f"/r/{REQ}/uploads/short/1/complete", json={"upload_id": "u", "parts": []})

    assert r.status_code == 404


# ── GET /r/{request_id}/{share_id}/{index} (download) ────────────────────────


def expect_send_listing(r2, keys):
    r2.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": k, "Size": 10, "LastModified": AT1} for k in keys]},
        {"Bucket": "beam", "Prefix": SEND_PREFIX},
    )


def test_download_from_a_public_request(client, r2, presigned, counted):
    expect_note(r2, note())
    expect_send_listing(r2, [f"{SEND_PREFIX}Alex/résumé.pdf/0", KEY1])

    r = client.get(f"/r/{REQ}/{SHARE}/1", follow_redirects=False)

    assert r.status_code == 307
    (call,) = presigned
    assert call["params"]["Key"] == KEY1
    assert call["params"]["ResponseContentDisposition"] == f"attachment; filename*=UTF-8''{quote('b.bin', safe='')}"
    assert call["expires"] == 600
    assert counted == ["downloads"]


def test_download_from_a_private_request_needs_the_owner_key(client, r2, presigned):
    expect_note(r2, note(private=True))

    r = client.get(f"/r/{REQ}/{SHARE}/1", follow_redirects=False)

    assert r.status_code == 403
    assert presigned == []


def test_owner_can_download_from_a_private_request(client, r2, presigned):
    expect_note(r2, note(private=True))
    expect_send_listing(r2, [KEY1])

    r = client.get(f"/r/{REQ}/{SHARE}/1", params={"key": OWNER}, follow_redirects=False)

    assert r.status_code == 307


def test_download_of_a_missing_file_is_404(client, r2):
    expect_note(r2, note())
    expect_send_listing(r2, [KEY0])

    assert client.get(f"/r/{REQ}/{SHARE}/1", follow_redirects=False).status_code == 404
