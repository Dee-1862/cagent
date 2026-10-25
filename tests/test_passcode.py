"""The passcode gate: a hosted hub keeps the tower's pages and endpoints behind UNSTEP_ATC_PASSWORD."""

import base64
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from unstep.gateway.sink import MemorySink
from unstep.live.app import create_live_app
from unstep.live.passcode import is_gated, passcode_ok

CODE = "pass:word with 'odd' chars"  # a passcode may hold colons and spaces


def basic(passcode, user="anyone"):
    return {"authorization": "Basic " + base64.b64encode(f"{user}:{passcode}".encode()).decode()}


@pytest.fixture
def hosted(monkeypatch):
    for name in ("UNSTEP_PILOT_APP_URL", "UNSTEP_PUBLIC_URL", "UNSTEP_ALLOWED_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("UNSTEP_ATC_PASSWORD", CODE)
    monkeypatch.setenv("UNSTEP_GATEWAY_TOKEN", "room-code-1234")
    app = create_live_app(live=False, sink=MemorySink())
    app.state.room.start = AsyncMock()
    with TestClient(app) as client:
        yield client


GATED = ["/", "/live/atc/", "/live/atc", "/live/record/", "/demo/", "/live/pilot-link", "/live/addresses", "/live/pi-join",
         "/live/stats", "/live/ask-audit", "/live/reports", "/live/flightlog", "/live/clearance-context/N123AB",
         "/live/geo/airport", "/live/qr.svg?u=http://testserver/pilot/"]
OPEN = ["/health", "/live/stations", "/live/static/atc/reasons.json"]


@pytest.mark.parametrize("path", GATED)
def test_tower_pages_and_endpoints_ask_for_the_passcode(hosted, path):
    answer = hosted.get(path)
    assert answer.status_code == 401
    assert answer.headers["www-authenticate"].startswith("Basic ")
    assert "room-code-1234" not in answer.text  # the challenge shows nothing
    assert hosted.get(path, headers=basic("wrong")).status_code == 401


def test_the_room_code_is_never_given_to_a_stranger(hosted):
    for path in ("/live/atc/", "/live/pilot-link", "/live/record/", "/"):
        assert "room-code-1234" not in hosted.get(path).text
    link = hosted.get("/live/pilot-link", headers=basic(CODE))
    assert link.status_code == 200 and "room-code-1234" in link.json()["url"]  # the tower sees it, after the passcode
    page = hosted.get("/live/atc/", headers=basic(CODE, user=""))  # the user name does not matter
    assert page.status_code == 200 and "room-code-1234" in page.text


@pytest.mark.parametrize("path", OPEN)
def test_what_visitors_and_hosting_need_stays_open(hosted, path):
    assert hosted.get(path).status_code == 200


def test_posts_to_the_tower_endpoints_are_gated_too(hosted):
    assert hosted.post("/live/reports/run").status_code == 401
    assert hosted.post("/live/geo/positions", json={}).status_code == 401
    assert hosted.post("/live/ask-audit", json={"question": "x"}).status_code == 401


def test_joining_a_plane_still_needs_the_room_code_not_the_tower_passcode(hosted):
    assert hosted.post("/live/join").status_code == 403
    assert hosted.post("/live/join", params={"token": "room-code-1234"}).status_code == 200


def test_a_cross_origin_preflight_is_not_blocked(hosted):
    assert hosted.options("/live/pilot-link").status_code != 401


def test_with_no_password_nothing_is_gated(monkeypatch):
    monkeypatch.delenv("UNSTEP_ATC_PASSWORD", raising=False)
    monkeypatch.delenv("unstep_atc_password", raising=False)
    app = create_live_app(live=False, sink=MemorySink())
    app.state.room.start = AsyncMock()
    with TestClient(app) as client:
        assert client.get("/live/atc/").status_code == 200 and client.get("/live/pilot-link").status_code == 200


def test_passcode_parsing_and_the_gated_path_list():
    assert passcode_ok(basic(CODE)["authorization"], CODE)
    assert not passcode_ok(None, CODE) and not passcode_ok("Bearer x", CODE) and not passcode_ok("Basic !!!", CODE)
    assert not passcode_ok(basic("")["authorization"], CODE)
    assert is_gated("/live/atc/") and is_gated("/live/clearance-context/N1") and is_gated("/")
    assert not is_gated("/pilot/") and not is_gated("/live/static/atc/atc.js") and not is_gated("/health")


def test_the_public_tunnel_refuses_to_publish_without_a_passcode(monkeypatch):
    import sys

    from scripts import demo_public

    monkeypatch.delenv("UNSTEP_ATC_PASSWORD", raising=False)
    monkeypatch.setattr(sys, "argv", ["demo_public.py", "--no-browser"])
    with pytest.raises(SystemExit, match="UNSTEP_ATC_PASSWORD"):
        demo_public.main()  # stops before any tunnel or hub is started
