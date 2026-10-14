from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
import httpx
import os
from beam.routers import files

router = APIRouter()

SITE_URL = "https://beamshare.app"


class Report(BaseModel):
    # same shape as the ids the frontend routes on, so nothing odd ends up in the email subject
    file_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    reason: str = Field(max_length=2000)
    email: EmailStr | None = None
    turnstile_token: str = ""

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("reason is required")
        return v


def size_text(n):
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def describe_file(file_id):
    # name and size let me judge a report without opening the file
    try:
        filename, size = files.lookup_file(file_id)
    except HTTPException:
        return "File: not found (probably expired)"
    return f"File: {filename} ({size_text(size)})"


def send_email(subject, text, reply_to):
    """Sends a plain-text email to me through Resend. Returns False if it didn't go out."""
    key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("REPORT_TO")
    sender = os.environ.get("REPORT_FROM")
    if not (key and to and sender):
        return False

    email = {"from": sender, "to": [to], "subject": subject, "text": text}
    if reply_to:
        email["reply_to"] = reply_to
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}"},
            json=email,
            timeout=10,
        )
    except httpx.HTTPError:
        return False
    return 200 <= r.status_code < 300


@router.post("/reports", status_code=204)
def report(body: Report, request: Request):
    ip = files.client_ip(request)
    if not files.verify_turnstile(body.turnstile_token, ip):
        raise HTTPException(status_code=403, detail="Verification failed")

    text = "\n".join([
        f"Link: {SITE_URL}/f/{body.file_id}",
        describe_file(body.file_id),
        f"Reporter IP: {ip}",
        f"Reporter email: {body.email or 'not given'}",
        "",
        body.reason,
    ])
    if not send_email(f"Beam report: {body.file_id}", text, body.email):
        raise HTTPException(status_code=502, detail="Couldn't send the report")
    return Response(status_code=204)
