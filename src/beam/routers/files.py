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
    if start.size > 10 * 1024**3:
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
