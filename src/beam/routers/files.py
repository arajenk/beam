from fastapi import APIRouter, HTTPException, Request
from starlette.responses import RedirectResponse
from botocore.exceptions import ClientError
from urllib.parse import quote, unquote
import secrets
import boto3
from dotenv import load_dotenv
import os
from pydantic import BaseModel, Field
import math
import threading
import time
import httpx

load_dotenv()

router = APIRouter()

account_id = os.environ["R2_ACCOUNT_ID"]
access_key = os.environ["R2_ACCESS_KEY_ID"]
secret_key = os.environ["R2_SECRET_ACCESS_KEY"]
r2_bucket = "beam"
MAX_SIZE = 10 * 1024**3
PER_IP_LIMIT = 50 * 1024**3
GLOBAL_LIMIT = 1024**4
# part URLs last 6h; the extra hour lets a slow last part still call complete
SWEEP_AFTER = 7 * 60 * 60
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
# file_id -> {upload_id, ip, size, started_at}, for uploads not yet completed or aborted
uploads: dict[str, dict] = {}


def client_ip(request: Request):
    # behind Heroku's router this becomes the last X-Forwarded-For entry (deploy step)
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


def take_record(file_id, upload_id):
    """Removes and returns the upload's record, or None if it's gone or the ids don't match."""
    with lock:
        record = uploads.get(file_id)
        if record is None or record["upload_id"] != upload_id:
            return None
        return uploads.pop(file_id)


class Part(BaseModel):
    part_number: int
    etag: str

class Start(BaseModel):
    filename: str
    size: int = Field(gt=0)
    content_type: str
    # missing and invalid are both refused with 403
    turnstile_token: str = ""

class Complete(BaseModel):
    upload_id: str
    parts: list[Part]

@router.post('/uploads')
def upload(start: Start, request: Request):
    ip = client_ip(request)
    if not start.turnstile_token or not verify_turnstile(start.turnstile_token, ip):
        raise HTTPException(status_code=403, detail="Verification failed")

    if start.size > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    if not reserve(ip, start.size):
        raise HTTPException(status_code=429, detail="Daily upload limit reached")

    file_id = secrets.token_hex(6)

    try:
        multipart = s3.create_multipart_upload(
            Bucket=r2_bucket, 
            Key=file_id, 
            ContentType=start.content_type, 
            Metadata={"filename": quote(start.filename, safe="")})
    except Exception:
        # nothing was created in R2, so give the hold back
        release(ip, start.size)
        raise

    upload_id = multipart["UploadId"]
    with lock:
        uploads[file_id] = {"upload_id": upload_id, "ip": ip, "size": start.size, "started_at": time.time()}

    part_size = 64 * 1024 * 1024
    part_count = math.ceil(start.size / part_size)
    remaining = start.size
    part_urls = []

    for part_number in range(1, part_count+1):
        this_size = min(part_size, remaining)
        url = s3.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": r2_bucket,
                    "Key": file_id,
                    "UploadId": upload_id,
                    "PartNumber": part_number,
                    "ContentLength": this_size
                },
                ExpiresIn=21600,
            )
        part_urls.append(url)
        remaining = remaining - this_size

    return {
        "file_id": file_id,
        "upload_id": upload_id,
        "part_size": part_size,
        "part_urls": part_urls
    }

@router.post('/uploads/{file_id}/abort', status_code=204)
def abort(file_id: str, upload_id: str):

    try:
        s3.abort_multipart_upload(
            Bucket=r2_bucket, 
            Key=file_id,
            UploadId=upload_id
        )
    except ClientError as e:
        # already completed or aborted: too late to cancel, so treat it as done
        if e.response["Error"]["Code"] not in ("404", "NoSuchUpload"):
            raise

    record = take_record(file_id, upload_id)
    if record:
        release(record["ip"], record["size"])

@router.post('/uploads/{file_id}/complete')
def complete(file_id: str, complete_req: Complete):
    try:
        list_of_parts = s3.list_parts(Bucket=r2_bucket, Key=file_id, UploadId=complete_req.upload_id)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchUpload"):
            raise HTTPException(status_code=404, detail="File not found")
        raise
    # R2 leaves "Parts" out entirely when nothing has been uploaded yet
    r2_parts = list_of_parts.get("Parts", [])

    total_size = 0
    for part in r2_parts:
        total_size += part["Size"]
        if total_size > MAX_SIZE:
            # nothing can fix an oversized upload, so delete the parts now instead of in 7 days
            s3.abort_multipart_upload(Bucket=r2_bucket, Key=file_id, UploadId=complete_req.upload_id)
            record = take_record(file_id, complete_req.upload_id)
            if record:
                release(record["ip"], record["size"])
            raise HTTPException(status_code=413, detail="File too large")

    # the browser's list is a claim; R2's record is what actually got uploaded
    r2_pairs = set()
    for part in r2_parts:
        r2_pairs.add((part["PartNumber"], part["ETag"]))

    browser_pairs = set()
    for part in complete_req.parts:
        browser_pairs.add((part.part_number, part.etag))

    if r2_pairs != browser_pairs:
        raise HTTPException(status_code=400, detail="Parts don't match")

    # R2 joins parts in the order given, so sort by part number
    sorted_parts = sorted(complete_req.parts, key=lambda part: part.part_number)
    s3.complete_multipart_upload(
        Bucket=r2_bucket,
        Key=file_id,
        UploadId=complete_req.upload_id,
        MultipartUpload={
            "Parts": [{"PartNumber": part.part_number, "ETag": part.etag} for part in sorted_parts]
        },
    )

    # the file now costs its real size, not what was declared at start
    record = take_record(file_id, complete_req.upload_id)
    if record:
        release(record["ip"], record["size"] - total_size)

    return {"file_id": file_id}


def sweep(now=None):
    """Aborts uploads nobody completed or aborted within SWEEP_AFTER and releases their holds."""
    now = time.time() if now is None else now
    with lock:
        stale = [(file_id, r["upload_id"]) for file_id, r in uploads.items() if now - r["started_at"] > SWEEP_AFTER]

    for file_id, upload_id in stale:
        try:
            s3.abort_multipart_upload(Bucket=r2_bucket, Key=file_id, UploadId=upload_id)
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("404", "NoSuchUpload"):
                # the parts may still be in R2, so keep the hold; the next sweep retries
                continue
        record = take_record(file_id, upload_id)
        if record:
            release(record["ip"], record["size"])


def lookup_file(file_id):
    try:
        head = s3.head_object(Bucket=r2_bucket, Key=file_id)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            raise HTTPException(status_code=404, detail="File not found")
        raise

    # objects uploaded before filename metadata existed fall back to the id
    filename = unquote(head["Metadata"].get("filename", "")) or file_id
    return filename, head["ContentLength"]

@router.get('/f/{file_id}/info')
def info(file_id: str):
    filename, size = lookup_file(file_id)
    return {
        "file_id": file_id,
        "filename": filename,
        "size": size,
    }

@router.get('/f/{file_id}')
def download(file_id: str):
    filename, _ = lookup_file(file_id)

    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": r2_bucket,
            "Key": file_id,
            "ResponseContentDisposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
        },
        ExpiresIn=600,
    )
    return RedirectResponse(url)
