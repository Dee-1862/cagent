"""The console's "change link" and "Add Raspberry Pi" choices: which addresses a phone or a Pi can use."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from unstep.gateway.sink import MemorySink
from unstep.live import addresses
from unstep.live.app import create_live_app


@pytest.fixture
def hub(monkeypatch):
    for name in ("UNSTEP_ATC_PASSWORD", "UNSTEP_GATEWAY_TOKEN", "UNSTEP_PILOT_APP_URL", "UNSTEP_PUBLIC_URL",
                 "UNSTEP_ALLOWED_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setattr(addresses, "lan_addresses", lambda: ["192.168.2.53"])
    monkeypatch.setattr("unstep.live.app.lan_addresses", lambda: ["192.168.2.53"])
    monkeypatch.setattr("unstep.live.app.own_hostnames", lambda public: {"192.168.2.53"} | (
        {public.split("//")[-1].split("/")[0]} if public else set()))
    app = create_live_app(live=False, sink=MemorySink())
    app.state.room.start = AsyncMock()
    with TestClient(app) as client:
        yield client, app


def test_options_say_which_links_phones_can_use(hub):
    client, app = hub
    app.state.bind_host = "127.0.0.1"  # the default: this computer only
    options = {o["id"]: o for o in client.get("/live/addresses").json()["options"]}
    assert options["this"]["url"].startswith("http://localhost") and options["this"]["shareable"] is False
    assert options["lan"]["url"].startswith("http://192.168.2.53") and options["lan"]["shareable"] is False
    assert "--host 0.0.0.0" in options["lan"]["note"]
    app.state.bind_host = "0.0.0.0"
    options = {o["id"]: o for o in client.get("/live/addresses").json()["options"]}
    assert options["lan"]["shareable"] is True and options["lan"]["note"] is None


def test_a_public_link_is_offered_when_one_is_set(hub, monkeypatch):
    client, _ = hub
    monkeypatch.setenv("UNSTEP_PUBLIC_URL", "https://demo.example.org/")
    options = {o["id"]: o for o in client.get("/live/addresses").json()["options"]}
    assert options["public"]["url"] == "https://demo.example.org" and options["public"]["shareable"] is True


def test_the_qr_accepts_this_computers_lan_address_but_not_strangers(hub):
    client, _ = hub
    ok = client.get("/live/qr.svg", params={"u": "http://192.168.2.53:8765/pilot/"})
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/svg+xml"
    for url in ("http://192.168.2.99:8765/pilot/", "https://evil.example.com/pilot/", "http://u:p@192.168.2.53/"):
        assert client.get("/live/qr.svg", params={"u": url}).status_code == 400


def test_the_pilot_link_can_be_switched_to_a_chosen_address(hub):
    client, _ = hub
    assert client.get("/live/pilot-link").json()["url"].endswith("/pilot/")
    chosen = client.get("/live/pilot-link", params={"base": "http://192.168.2.53:8765"}).json()
    assert chosen["url"] == "http://192.168.2.53:8765/pilot/"
    assert client.get("/live/pilot-link", params={"base": "https://evil.example.com"}).status_code == 400


def test_the_pi_button_gets_an_address_and_a_command_without_the_room_code(hub, monkeypatch):
    client, app = hub
    app.state.bind_host = "0.0.0.0"
    plain = client.get("/live/pi-join").json()
    assert plain["hub"] == "http://192.168.2.53:8765" or plain["hub"].startswith("http://192.168.2.53")
    assert plain["command"].startswith("python scripts/pi_plane.py --hub http://192.168.2.53")
    assert plain["needs_token"] is False and plain["shareable"] is True
    monkeypatch.setenv("UNSTEP_GATEWAY_TOKEN", "s3cret-room-code")
    guarded = client.get("/live/pi-join").json()
    assert guarded["needs_token"] is True and "--token <room code>" in guarded["command"]
    assert "s3cret-room-code" not in str(guarded)
    assert client.get("/live/pi-join", params={"base": "https://evil.example.com"}).status_code == 400


def test_lan_addresses_skip_loopback_and_link_local(monkeypatch):
    monkeypatch.undo()

    class FakeSocket:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def connect(self, _): pass
        def getsockname(self): return ("169.254.199.21", 1)

    monkeypatch.setattr(addresses.socket, "socket", lambda *a, **k: FakeSocket())
    monkeypatch.setattr(addresses.socket, "getaddrinfo", lambda *a, **k: [
        (2, 1, 6, "", ("127.0.0.1", 0)), (2, 1, 6, "", ("192.168.2.53", 0)), (2, 1, 6, "", ("8.8.8.8", 0)),
        (2, 1, 6, "", ("192.168.137.1", 0)), (2, 1, 6, "", ("192.168.2.53", 0))])
    assert addresses.lan_addresses() == ["192.168.2.53", "192.168.137.1"]
    assert addresses.reachable_from_lan(None) and addresses.reachable_from_lan("0.0.0.0")
    assert not addresses.reachable_from_lan("127.0.0.1")


def test_the_default_link_uses_the_wifi_address_when_the_console_is_open_on_localhost_and_the_hub_is_open_to_the_lan(hub):
    client, app = hub
    local = {"host": "localhost"}
    app.state.bind_host = "127.0.0.1"  # this computer only: phones could not use a wifi address anyway
    assert client.get("/live/pilot-link", headers=local).json()["url"].startswith("http://localhost")
    app.state.bind_host = "0.0.0.0"
    assert client.get("/live/pilot-link", headers=local).json()["url"] == "http://192.168.2.53:80/pilot/"
    other = client.get("/live/pilot-link").json()["url"]  # opened by a name other than localhost: left alone
    assert other.startswith("http://testserver")


def test_seen_through_the_public_link_only_the_public_link_is_offered(monkeypatch):
    monkeypatch.setenv("UNSTEP_PUBLIC_URL", "https://demo.example.org")
    monkeypatch.setenv("UNSTEP_ALLOWED_HOSTS", "testserver,demo.example.org")
    monkeypatch.setattr("unstep.live.app.lan_addresses", lambda: ["192.168.2.53"])
    monkeypatch.setattr("unstep.live.app.own_hostnames", lambda public: {"192.168.2.53", "demo.example.org"})
    app = create_live_app(live=False, sink=MemorySink())
    app.state.room.start = AsyncMock()
    app.state.bind_host, app.state.bind_port, app.state.scheme = "127.0.0.1", 8790, "http"
    with TestClient(app) as client:
        outside = client.get("/live/addresses", headers={"host": "demo.example.org"}).json()
        assert [o["id"] for o in outside["options"]] == ["public"] and outside["has_public"] is True
        local = client.get("/live/addresses", headers={"host": "localhost"}).json()  # the laptop's own console
        by_id = {}
        for o in local["options"]:
            by_id.setdefault(o["id"], o)
        assert list(by_id) == ["public", "this", "lan"]
        assert by_id["this"]["url"] == "http://localhost:8790"  # the real port and scheme, not the tunnel's 443
        assert by_id["lan"]["url"] == "http://192.168.2.53:8790" and by_id["lan"]["shareable"] is False


def test_without_a_public_link_the_console_is_told_so(hub):
    client, _ = hub
    assert client.get("/live/addresses").json()["has_public"] is False
