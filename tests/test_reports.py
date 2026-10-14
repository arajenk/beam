"""
Spec for abuse reports: POST /reports emails the report through Resend.
Turnstile, the R2 lookup and Resend are all faked, so nothing leaves the machine.
"""

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from beam.main import app
from beam.routers import files, reports

IP = "203.0.113.7"


@pytest.fixture
def client():
    # X-Forwarded-For makes client_ip() see a known address, like Heroku's router
    return TestClient(app, headers={"X-Forwarded-For": IP})


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    """Turnstile accepts "ok", the file exists, Resend is configured and records what it's sent."""
    sent = []

    class FakeResponse:
        status_code = 200

    def fake_post(url, headers, json, timeout):
        sent.append({"url": url, "headers": headers, "json": json})
        return FakeResponse()

    monkeypatch.setattr(files, "verify_turnstile", lambda token, ip: token == "ok")
    monkeypatch.setattr(files, "lookup_file", lambda file_id: ("invoice.exe", 2 * 1024**2))
    monkeypatch.setattr(reports.httpx, "post", fake_post)
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("REPORT_TO", "me@example.com")
    monkeypatch.setenv("REPORT_FROM", "abuse@beamshare.app")
    return sent


def report(client, **overrides):
    body = {"file_id": "abc123", "reason": "This is malware", "turnstile_token": "ok"}
    body.update(overrides)
    return client.post("/reports", json=body)


def test_report_is_emailed_to_me(client, fakes):
    r = report(client)

    assert r.status_code == 204
    assert len(fakes) == 1
    sent = fakes[0]
    assert sent["url"] == "https://api.resend.com/emails"
    assert sent["headers"]["Authorization"] == "Bearer re_test"
    email = sent["json"]
    assert email["from"] == "abuse@beamshare.app"
    assert email["to"] == ["me@example.com"]
    assert "abc123" in email["subject"]
    # plain text only, so a reporter can't inject HTML into the inbox
    assert "html" not in email
    for expected in ["https://beamshare.app/f/abc123", "invoice.exe", "2.0 MB", "This is malware", IP]:
        assert expected in email["text"]


def test_reporter_email_becomes_reply_to(client, fakes):
    report(client, email="reporter@example.com")
    assert fakes[0]["json"]["reply_to"] == "reporter@example.com"


def test_no_reporter_email_means_no_reply_to(client, fakes):
    report(client)
    assert "reply_to" not in fakes[0]["json"]


def test_missing_file_is_still_reported(client, fakes, monkeypatch):
    # usually it expired; the report still reaches me, marked as such
    def gone(file_id):
        raise HTTPException(status_code=404, detail="File not found")

    monkeypatch.setattr(files, "lookup_file", gone)

    assert report(client).status_code == 204
    assert "not found" in fakes[0]["json"]["text"].lower()


def test_bad_turnstile_token_is_403_and_sends_nothing(client, fakes):
    assert report(client, turnstile_token="nope").status_code == 403
    assert fakes == []


@pytest.mark.parametrize("reason", ["", "   ", "x" * 2001])
def test_empty_or_huge_reason_is_rejected(client, fakes, reason):
    assert report(client, reason=reason).status_code == 422
    assert fakes == []


def test_bad_reporter_email_is_rejected(client, fakes):
    assert report(client, email="not-an-email").status_code == 422


def test_odd_file_id_is_rejected(client, fakes):
    assert report(client, file_id="../etc\npasswd").status_code == 422


def test_resend_error_is_502(client, monkeypatch):
    class Failed:
        status_code = 500

    monkeypatch.setattr(reports.httpx, "post", lambda url, headers, json, timeout: Failed())
    assert report(client).status_code == 502


def test_resend_unreachable_is_502(client, monkeypatch):
    def boom(url, headers, json, timeout):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(reports.httpx, "post", boom)
    assert report(client).status_code == 502


def test_resend_not_configured_is_502(client, monkeypatch):
    # missing config shouldn't crash the whole API on startup, only reports fail
    monkeypatch.delenv("RESEND_API_KEY")
    assert report(client).status_code == 502
