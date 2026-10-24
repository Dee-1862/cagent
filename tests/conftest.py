import pytest


@pytest.fixture(autouse=True)
def _allow_testclient_host(monkeypatch):
    """Starlette's TestClient sends Host: testserver; real runs only allow local hosts."""
    monkeypatch.setenv("UNSTEP_ALLOWED_HOSTS", "testserver")
