import pytest


@pytest.fixture(autouse=True)
def _allow_testclient_host(monkeypatch):
    """Starlette's TestClient sends Host: testserver; real runs only allow local hosts."""
    monkeypatch.setenv("UNSTEP_ALLOWED_HOSTS", "testserver")


SERVICE_KEYS = ("ELASTIC_CLOUD_URL", "ELASTIC_URL", "ELASTIC_API_KEY", "ELASTIC_CLOUD_KEY",
                "MOSS_PROJECT_ID", "MOSS_PROJECT_KEY")


@pytest.fixture(autouse=True)
def _no_real_elastic_or_moss(monkeypatch):
    """Tests use fakes. With real Elastic or Moss keys in the shell or .env, rooms and gateways would open
    real connections: slow, hanging where the network is blocked, and writing test traffic into your
    cluster. Set UNSTEP_LIVE_ELASTIC=1 to run the opt-in live Elastic test."""
    import os

    if os.environ.get("UNSTEP_LIVE_ELASTIC") != "1":
        for name in SERVICE_KEYS:
            monkeypatch.delenv(name, raising=False)
