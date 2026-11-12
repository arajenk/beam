"""File requests: someone asks for files with a note and hands out a public link;
anyone with that link can send files into the request.

R2 layout, all in the beam bucket so the 1-day lifecycle rule expires it:
    requests/{request_id}/note                                    JSON, the request
    requests/{request_id}/{share_id}/{sender}/{filename}/{index}  one per sent file

The requester also gets an owner key, kept only inside the note object. With the
private switch on, the files are listed and downloadable only with that key.
"""

import json
import secrets
import time

from botocore.exceptions import ClientError
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from beam.routers import files

router = APIRouter()

# a request takes sends for a day; R2 deletes it some time after that
REQUEST_OPEN = 24 * 60 * 60
NOTE_LIMIT = 500
PERSON_NAME_LIMIT = 50


def request_prefix(request_id):
    return f"requests/{request_id}/"


def note_key(request_id):
    return f"{request_prefix(request_id)}note"


class NewRequest(BaseModel):
    note: str = Field(max_length=NOTE_LIMIT)
    name: str | None = Field(default=None, max_length=PERSON_NAME_LIMIT)
    private: bool = False
    turnstile_token: str = ""

    @field_validator("note")
    @classmethod
    def note_not_blank(cls, v):
        v = files.clean_text(v, keep_newlines=True)
        if not v:
            raise ValueError("note is required")
        return v

    @field_validator("name")
    @classmethod
    def name_cleaned(cls, v):
        if v is None:
            return None
        return files.clean_text(v) or None


class Send(files.Start):
    # typed by the sender, so it's only ever a claim; it goes into the key, so it's cleaned
    sender: str = Field(max_length=PERSON_NAME_LIMIT)

    @field_validator("sender")
    @classmethod
    def sender_not_blank(cls, v):
        v = files.clean_text(v)
        if not v:
            raise ValueError("sender is required")
        return v


@router.post("/requests")
def create_request(body: NewRequest, request: Request):
    files.require_turnstile(body.turnstile_token, files.client_ip(request))

    request_id = secrets.token_urlsafe(16)
    owner_key = secrets.token_urlsafe(16)
    stored = {
        "note": body.note,
        "name": body.name,
        "private": body.private,
        "owner_key": owner_key,
        "created_at": time.time(),
    }
    files.s3.put_object(
        Bucket=files.r2_bucket,
        Key=note_key(request_id),
        Body=json.dumps(stored).encode(),
        ContentType="application/json",
    )
    return {"request_id": request_id, "owner_key": owner_key}


def load_request(request_id):
    """The stored request, or 404. Malformed ids never reach R2."""
    if not files.valid_id(request_id):
        raise HTTPException(status_code=404, detail="Request not found")
    try:
        obj = files.s3.get_object(Bucket=files.r2_bucket, Key=note_key(request_id))
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            raise HTTPException(status_code=404, detail="Request not found")
        raise
    return json.loads(obj["Body"].read())


def is_owner(stored, key):
    # constant time, so response timing can't reveal the key a character at a time
    return key is not None and secrets.compare_digest(key.encode(), stored["owner_key"].encode())


def can_view(stored, key):
    return not stored["private"] or is_owner(stored, key)


def is_open(stored):
    return time.time() - stored["created_at"] <= REQUEST_OPEN


def list_sends(request_id, share_id=None):
    """Every finished file in the request (or in one send of it) as
    (share_id, sender, filename, index, size, uploaded_at)."""
    base = request_prefix(request_id)
    found = []
    params = {"Bucket": files.r2_bucket, "Prefix": base if share_id is None else f"{base}{share_id}/"}
    while True:
        listing = files.s3.list_objects_v2(**params)
        for obj in listing.get("Contents", []):
            parts = obj["Key"][len(base):].split("/")
            # the note, or anything else that isn't share/sender/filename/index, is skipped
            if len(parts) != 4 or not parts[3].isdigit():
                continue
            share_id, sender, filename, index = parts
            found.append((share_id, sender, filename, int(index), obj["Size"], obj["LastModified"]))
        if not listing.get("IsTruncated"):
            return found
        params["ContinuationToken"] = listing["NextContinuationToken"]


def list_request(request_id):
    """The request's sends, oldest first, each with its files in index order."""
    sends = {}
    for share_id, sender, filename, index, size, uploaded_at in list_sends(request_id):
        send = sends.setdefault(share_id, {"share_id": share_id, "sender": sender, "files": [], "first": uploaded_at})
        send["first"] = min(send["first"], uploaded_at)
        send["files"].append({"index": index, "filename": filename, "size": size})
    ordered = sorted(sends.values(), key=lambda s: (s["first"], s["share_id"]))
    for send in ordered:
        del send["first"]
        send["files"].sort(key=lambda f: f["index"])
    return ordered


@router.get("/r/{request_id}/info")
def request_info(request_id: str, key: str | None = None):
    stored = load_request(request_id)
    return {
        "request_id": request_id,
        "note": stored["note"],
        "name": stored["name"],
        "private": stored["private"],
        "open": is_open(stored),
        "closes_at": stored["created_at"] + REQUEST_OPEN,
        "is_owner": is_owner(stored, key),
        # None, not [], so the page can tell "hidden from you" from "nothing sent yet"
        "sends": list_request(request_id) if can_view(stored, key) else None,
    }


@router.post("/r/{request_id}/uploads")
def send_to_request(request_id: str, body: Send, request: Request):
    ip = files.client_ip(request)
    files.require_turnstile(body.turnstile_token, ip)
    stored = load_request(request_id)
    if not is_open(stored):
        raise HTTPException(status_code=410, detail="Request closed")

    prefix = request_prefix(request_id)
    sender = body.sender
    return files.open_share(
        body.files,
        ip,
        lambda share_id, index, name: f"{prefix}{share_id}/{sender}/{name}/{index}",
        request_id,
    )


def find_sent(request_id, share_id, index):
    """The in-progress upload for file index of one send, or None."""
    if not (files.valid_id(request_id) and files.valid_id(share_id)):
        return None
    send_prefix = f"{request_prefix(request_id)}{share_id}/"
    # the index is the last part of the key; split on "/" so 1 never matches 11
    return files.find_in_progress(send_prefix, lambda k: k.rsplit("/", 1)[-1] == str(index))


@router.post("/r/{request_id}/uploads/{share_id}/{index}/complete")
def complete_sent(request_id: str, share_id: str, index: int, complete_req: files.Complete, background_tasks: BackgroundTasks):
    key = find_sent(request_id, share_id, index)
    # Nothing in progress: maybe an earlier complete worked and its reply was lost.
    # Senders can't list a private request to check, so answer for them here.
    if key is None and files.valid_id(request_id) and files.valid_id(share_id):
        if any(sent_index == index for _, _, _, sent_index, _, _ in list_sends(request_id, share_id)):
            return {"share_id": share_id, "index": index}
    files.finish_upload(key, complete_req, background_tasks)
    return {"share_id": share_id, "index": index}


@router.post("/r/{request_id}/uploads/{share_id}/{index}/abort", status_code=204)
def abort_sent(request_id: str, share_id: str, index: int, upload_id: str):
    files.cancel_upload(find_sent(request_id, share_id, index), upload_id)


@router.get("/r/{request_id}/{share_id}/{index}")
def download_sent(request_id: str, share_id: str, index: int, background_tasks: BackgroundTasks, key: str | None = None):
    stored = load_request(request_id)
    if not can_view(stored, key):
        raise HTTPException(status_code=403, detail="Only the requester can download these files")
    if not files.valid_id(share_id):
        raise HTTPException(status_code=404, detail="File not found")

    for sent_share, sender, filename, sent_index, _, _ in list_sends(request_id, share_id):
        if sent_share == share_id and sent_index == index:
            key = f"{request_prefix(request_id)}{share_id}/{sender}/{filename}/{index}"
            return files.redirect_to_file(key, filename, background_tasks)
    raise HTTPException(status_code=404, detail="File not found")
