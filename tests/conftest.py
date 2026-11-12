import pytest
from botocore.stub import Stubber
from fastapi.testclient import TestClient

from beam.main import app
from beam.routers import files


@pytest.fixture(autouse=True)
def counted(monkeypatch):
    """Swaps the stats counter for a recorder, so endpoint tests don't need to
    stub its R2 calls. test_stats.py tests the real one."""
    events = []
    monkeypatch.setattr(files, "bump", events.append)
    return events


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
    monkeypatch.setattr(files, "request_bytes", {}, raising=False)
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
