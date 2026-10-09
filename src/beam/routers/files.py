from fastapi import APIRouter, HTTPException
from starlette.responses import RedirectResponse
from botocore.exceptions import ClientError
from urllib.parse import quote, unquote
import secrets
import boto3
from dotenv import load_dotenv
import os
from pydantic import BaseModel, Field
import math

load_dotenv()

router = APIRouter()

account_id = os.environ["R2_ACCOUNT_ID"]
access_key = os.environ["R2_ACCESS_KEY_ID"]
secret_key = os.environ["R2_SECRET_ACCESS_KEY"]
r2_bucket = "beam"
MAX_SIZE = 10 * 1024**3

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    region_name="auto",
)

class Part(BaseModel):
    part_number: int
    etag: str

class Start(BaseModel):
    filename: str
    size: int = Field(gt=0)
    content_type: str

class Complete(BaseModel):
    upload_id: str
    parts: list[Part]

@router.post('/uploads')
def upload(start: Start):
    if start.size > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File too large")
    
    file_id = secrets.token_hex(6)

    multipart = s3.create_multipart_upload(
        Bucket=r2_bucket, 
        Key=file_id, 
        ContentType=start.content_type, 
        Metadata={"filename": quote(start.filename, safe="")})
    
    upload_id = multipart["UploadId"]
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

    return {"file_id": file_id}


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
