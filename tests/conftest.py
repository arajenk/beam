import pytest

from beam.routers import files


@pytest.fixture(autouse=True)
def counted(monkeypatch):
    """Swaps the stats counter for a recorder, so endpoint tests don't need to
    stub its R2 calls. test_stats.py tests the real one."""
    events = []
    monkeypatch.setattr(files, "bump", events.append)
    return events
