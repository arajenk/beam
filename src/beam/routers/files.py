from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from starlette.responses import RedirectResponse
from botocore.exceptions import ClientError
from urllib.parse import quote
import secrets
import boto3
from dotenv import load_dotenv
import os
from pydantic import BaseModel, Field
import math
import threading
import asyncio
import logging
import time
import httpx
import json
import unicodedata

load_dotenv()

router = APIRouter()
logger = logging.getLogger(__name__)

account_id = os.environ["R2_ACCOUNT_ID"]
access_key = os.environ["R2_ACCESS_KEY_ID"]
secret_key = os.environ["R2_SECRET_ACCESS_KEY"]
r2_bucket = "beam"
# all-time counts live in their own bucket, which has no lifecycle rule
STATS_BUCKET = "beam-stats"
STATS_KEY = "counts.json"
# a share is up to MAX_FILES files, MAX_SIZE bytes all together
MAX_FILES = 10
MAX_SIZE = 10 * 1024**3
# the name is part of the R2 key (limit 1024 bytes), so cap it well below that
NAME_LIMIT = 200
PER_IP_LIMIT = 50 * 1024**3
GLOBAL_LIMIT = 1024**4
# part URLs last 6h; the extra hour lets a slow last part still call complete
SWEEP_AFTER = 7 * 60 * 60
# so a hold lives at most SWEEP_AFTER + SWEEP_EVERY (about 8h)
SWEEP_EVERY = 60 * 60
TURNSTILE_SECRET = os.environ["TURNSTILE_SECRET"]

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    region_name="auto",
)

# Upload limits. Kept in memory, so they reset whenever the API restarts
# (about daily on Heroku), and that restart is the daily reset.
# Start holds the declared size; complete settles it to the real size;
# abort and sweep release it. Whoever removes an upload's record adjusts the
# counters, so each hold is settled or released exactly once.
lock = threading.Lock()
ip_bytes: dict[str, int] = {}
total_bytes = 0
# R2 key -> {upload_id, ip, size, started_at}, one per file not yet completed or aborted
uploads: dict[str, dict] = {}


# Held during the R2 read and write, so it's separate from `lock`, which never is.
# One process means no lost counts; a deploy's brief overlap of two dynos can lose a few.
stats_lock = threading.Lock()


def bump(event):
    """Adds 1 to the all-time count for event ("uploads" or "downloads").
    Runs after the response is sent, so a failure only loses this one count."""
    with stats_lock:
        try:
            counts = json.loads(s3.get_object(Bucket=STATS_BUCKET, Key=STATS_KEY)["Body"].read())
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("404", "NoSuchKey"):
                # any other error: skip, rather than overwrite the real total with 1
                logger.exception("stats read failed")
                return
            counts = {"uploads": 0, "downloads": 0}
        counts[event] = counts.get(event, 0) + 1
        try:
            s3.put_object(Bucket=STATS_BUCKET, Key=STATS_KEY, Body=json.dumps(counts).encode(), ContentType="application/json")
        except ClientError:
            logger.exception("stats write failed")


def client_ip(request: Request):
    # on Heroku every request comes through the router, which appends the IP it saw
    # to X-Forwarded-For; earlier entries come from the client and can be faked
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def verify_turnstile(token, ip):
    try:
        r = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": TURNSTILE_SECRET, "response": token, "remoteip": ip},
            timeout=10,
        )
        return r.json().get("success") is True
    except (httpx.HTTPError, ValueError):
        # can't reach Cloudflare: refuse rather than let unverified uploads through
        return False


def reserve(ip, size):
    global total_bytes
    with lock:
        # check and add in one step, or two requests could both pass the check
        if ip_bytes.get(ip, 0) + size > PER_IP_LIMIT or total_bytes + size > GLOBAL_LIMIT:
            return False
        ip_bytes[ip] = ip_bytes.get(ip, 0) + size
        total_bytes += size
        return True


def release(ip, amount):
    global total_bytes
    with lock:
        ip_bytes[ip] = ip_bytes.get(ip, 0) - amount
        if ip_bytes[ip] <= 0:
            del ip_bytes[ip]
        total_bytes -= amount


def take_record(key, upload_id):
    """Removes and returns the upload's record, or None if it's gone or the ids don't match."""
    with lock:
        record = uploads.get(key)
        if record is None or record["upload_id"] != upload_id:
            return None
        return uploads.pop(key)


def clean_name(name):
    """Makes a filename safe to put in a key: no slashes or control characters,
    at most NAME_LIMIT bytes, extension kept. Odd names are fixed, never refused."""
    # Cc: control characters. Cf: invisible formatting, like the right-to-left
    # override that makes "a\u202egpj.exe" display as "aexe.jpg". Zl/Zp: line breaks.
    name = "".join(
        "_" if ch in "/\\" or unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") else ch for ch in name
    ).strip()
    if len(name.encode()) > NAME_LIMIT:
        stem, dot, ext = name.rpartition(".")
        suffix = dot + ext if stem and len(ext) <= 10 else ""
        if not suffix:
            stem = name
        budget = NAME_LIMIT - len(suffix.encode())
        # cutting bytes can split a multi-byte character; drop the broken piece
        name = stem.encode()[:budget].decode(errors="ignore") + suffix
    # "." and ".." would be collapsed out of the URL by browsers, breaking the signature
    if not name.strip("."):
        return "file"
    return name


class Part(BaseModel):
    part_number: int
    etag: str

class FileSpec(BaseModel):
    filename: str
    size: int = Field(gt=0)
    content_type: str

class Start(BaseModel):
    files: list[FileSpec] = Field(min_length=1, max_length=MAX_FILES)
    # missing and invalid are both refused with 403
    turnstile_token: str = ""

class Complete(BaseModel):
    upload_id: str
    parts: list[Part]


PART_SIZE = 64 * 1024 * 1024

def sign_parts(key, upload_id, size):
    part_urls = []
    remaining = size
    for part_number in range(1, math.ceil(size / PART_SIZE) + 1):
        this_size = min(PART_SIZE, remaining)
        part_urls.append(s3.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": r2_bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
                "ContentLength": this_size,
            },
            ExpiresIn=21600,
        ))
        remaining -= this_size
    return part_urls

@router.post('/uploads')
def upload(start: Start, request: Request):
    ip = client_ip(request)
    if not start.turnstile_token or not verify_turnstile(start.turnstile_token, ip):
        raise HTTPException(status_code=403, detail="Verification failed")

    total = sum(spec.size for spec in start.files)
    if total > MAX_SIZE:
        raise HTTPException(status_code=413, detail="Share too large")

    if not reserve(ip, total):
        raise HTTPException(status_code=429, detail="Daily upload limit reached")

    # everything is signed here, so nobody can add a file to this share later
    share_id = secrets.token_urlsafe(16)
    created = []  # (key, upload_id, spec, name)
    try:
        for index, spec in enumerate(start.files):
            name = clean_name(spec.filename)
            key = f"{share_id}/{index}/{name}"
            multipart = s3.create_multipart_upload(Bucket=r2_bucket, Key=key, ContentType=spec.content_type)
            created.append((key, multipart["UploadId"], spec, name))
    except Exception:
        # release first, so a failing undo below can't leak the hold
        release(ip, total)
        # undo the files that did get created; R2's abort rule is the backstop if this fails too
        for key, upload_id, _, _ in created:
            try:
                s3.abort_multipart_upload(Bucket=r2_bucket, Key=key, UploadId=upload_id)
            except Exception:
                pass
        raise

    now = time.time()
    with lock:
        for key, upload_id, spec, _ in created:
            uploads[key] = {"upload_id": upload_id, "ip": ip, "size": spec.size, "started_at": now}

    return {
        "share_id": share_id,
        "part_size": PART_SIZE,
        "files": [
            {
                "index": index,
                "filename": name,
                "upload_id": upload_id,
                "part_urls": sign_parts(key, upload_id, spec.size),
            }
            for index, (key, upload_id, spec, name) in enumerate(created)
        ],
    }

def find_upload(share_id, index):
    """The key of the in-progress upload at share_id/index/, asked of R2 rather
    than memory so it still works after a restart. None if there's no such upload.

    R2 lists upload ids re-encoded, so they can't be compared with the client's.
    Each share_id/index/ only ever gets one upload (start assigns indexes once),
    and R2 itself rejects a key paired with the wrong upload id (NoSuchUpload)."""
    prefix = f"{share_id}/{index}/"
    listing = s3.list_multipart_uploads(Bucket=r2_bucket, Prefix=prefix)
    for u in listing.get("Uploads", []):
        # check the prefix too, rather than trusting R2's filter alone
        if u["Key"].startswith(prefix):
            return u["Key"]
    return None

@router.post('/uploads/{share_id}/{index}/abort', status_code=204)
def abort(share_id: str, index: int, upload_id: str):
    key = find_upload(share_id, index)
    if key is None:
        # already completed or aborted: too late to cancel, so treat it as done
        return

    try:
        s3.abort_multipart_upload(Bucket=r2_bucket, Key=key, UploadId=upload_id)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchUpload"):
            raise

    record = take_record(key, upload_id)
    if record:
        release(record["ip"], record["size"])

@router.post('/uploads/{share_id}/{index}/complete')
def complete(share_id: str, index: int, complete_req: Complete, background_tasks: BackgroundTasks):
    key = find_upload(share_id, index)
    if key is None:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        list_of_parts = s3.list_parts(Bucket=r2_bucket, Key=key, UploadId=complete_req.upload_id)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchUpload"):
            raise HTTPException(status_code=404, detail="File not found")
        raise
    # R2 leaves "Parts" out entirely when nothing has been uploaded yet
    r2_parts = list_of_parts.get("Parts", [])

    # signed part sizes already cap each file at its declared size; this is the backstop
    total_size = 0
    for part in r2_parts:
        total_size += part["Size"]
        if total_size > MAX_SIZE:
            # nothing can fix an oversized upload, so delete the parts now instead of in a day
            s3.abort_multipart_upload(Bucket=r2_bucket, Key=key, UploadId=complete_req.upload_id)
            record = take_record(key, complete_req.upload_id)
            if record:
                release(record["ip"], record["size"])
            raise HTTPException(status_code=413, detail="File too large")

    # the browser's list is a claim; R2's record is what actually got uploaded
    r2_pairs = {(part["PartNumber"], part["ETag"]) for part in r2_parts}
    browser_pairs = {(part.part_number, part.etag) for part in complete_req.parts}
    if r2_pairs != browser_pairs:
        raise HTTPException(status_code=400, detail="Parts don't match")

    # R2 joins parts in the order given, so sort by part number
    sorted_parts = sorted(complete_req.parts, key=lambda part: part.part_number)
    s3.complete_multipart_upload(
        Bucket=r2_bucket,
        Key=key,
        UploadId=complete_req.upload_id,
        MultipartUpload={
            "Parts": [{"PartNumber": part.part_number, "ETag": part.etag} for part in sorted_parts]
        },
    )

    # the file now costs its real size, not what was declared at start
    record = take_record(key, complete_req.upload_id)
    if record:
        release(record["ip"], record["size"] - total_size)

    background_tasks.add_task(bump, "uploads")
    return {"share_id": share_id, "index": index}


def sweep(now=None):
    """Aborts uploads nobody completed or aborted within SWEEP_AFTER and releases their holds."""
    now = time.time() if now is None else now
    with lock:
        stale = [(key, r["upload_id"]) for key, r in uploads.items() if now - r["started_at"] > SWEEP_AFTER]

    for key, upload_id in stale:
        try:
            s3.abort_multipart_upload(Bucket=r2_bucket, Key=key, UploadId=upload_id)
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("404", "NoSuchUpload"):
                # the parts may still be in R2, so keep the hold; the next sweep retries
                continue
        record = take_record(key, upload_id)
        if record:
            release(record["ip"], record["size"])


async def sweep_loop(interval=SWEEP_EVERY):
    """Runs sweep() every interval for as long as the app is up. It must live in the
    web process, since the holds it releases are in this process's memory."""
    while True:
        await asyncio.sleep(interval)
        try:
            # boto3 calls block, so keep them off the event loop
            await asyncio.to_thread(sweep)
        except Exception:
            # one bad run (e.g. R2 unreachable) shouldn't stop sweeping until the next restart
            logger.exception("sweep failed")


def list_share(share_id, index=None):
    """The finished files in a share (or just the one at index), from one R2 listing.
    Unfinished multipart uploads aren't objects yet, so they never show up here."""
    prefix = f"{share_id}/" if index is None else f"{share_id}/{index}/"
    listing = s3.list_objects_v2(Bucket=r2_bucket, Prefix=prefix)
    found = []
    for obj in listing.get("Contents", []):
        _, i, name = obj["Key"].split("/", 2)
        found.append({"index": int(i), "filename": name, "size": obj["Size"], "key": obj["Key"]})
    if not found:
        raise HTTPException(status_code=404, detail="Share not found")
    return sorted(found, key=lambda f: f["index"])

# declared before the per-file route, so "info" isn't taken for an index
@router.get('/f/{share_id}/info')
def info(share_id: str):
    return {
        "share_id": share_id,
        "files": [{"index": f["index"], "filename": f["filename"], "size": f["size"]} for f in list_share(share_id)],
    }

@router.get('/f/{share_id}/{index}')
def download(share_id: str, index: int, background_tasks: BackgroundTasks):
    file = list_share(share_id, index)[0]

    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": r2_bucket,
            "Key": file["key"],
            "ResponseContentDisposition": f"attachment; filename*=UTF-8''{quote(file['filename'], safe='')}",
        },
        ExpiresIn=600,
    )
    background_tasks.add_task(bump, "downloads")
    return RedirectResponse(url)
