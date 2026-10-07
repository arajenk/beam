from fastapi import APIRouter, UploadFile, HTTPException
from starlette.responses import RedirectResponse
from botocore.exceptions import ClientError
from urllib.parse import quote, unquote
import secrets
import boto3
from dotenv import load_dotenv
import os

load_dotenv()
class UploadTooLarge(Exception):
    pass

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

@router.post('/upload')
async def upload(file: UploadFile):
    try:
        file_id = await save_file(file)
    except UploadTooLarge:
        raise HTTPException(status_code=413, detail="File is too large")

    return {
        "file_id": file_id,
        "filename": file.filename,
    }

async def save_file(file):
    MAX_SIZE = 10 * 1024 * 1024 * 1024

    if file.size is not None and file.size > MAX_SIZE:
        raise UploadTooLarge

    file_id = secrets.token_hex(6)

    # metadata is sent as HTTP headers, so encode non-ASCII filenames
    s3.upload_fileobj(
        file.file,
        r2_bucket,
        file_id,
        ExtraArgs={"Metadata": {"filename": quote(file.filename or "", safe="")}},
    )

    return file_id

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
