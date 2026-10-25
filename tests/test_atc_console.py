"""Tower access and the presentation contract; no speech services are needed."""

import ast
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from unstep.gateway.sink import MemorySink
from unstep.live.app import create_live_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def console(monkeypatch):
    # Isolate these tests from all local deployment credentials.
    for name in ("UNSTEP_ATC_PASSWORD", "UNSTEP_GATEWAY_TOKEN", "UNSTEP_PILOT_APP_URL", "UNSTEP_PUBLIC_URL", "UNSTEP_ALLOWED_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    app = create_live_app(live=False, sink=MemorySink())
    # Exercise real routes, joins, snapshots and role checks, without starting
    # speech engines or long-lived background workers.
    app.state.room.start = AsyncMock()
    with TestClient(app) as client:
        yield client, app.state.room


def test_atc_page_and_local_assets_are_served(console, monkeypatch):
    client, _ = console
    monkeypatch.setenv("UNSTEP_GATEWAY_TOKEN", "a&b?c")
    response = client.get("/live/atc/")
    assert response.status_code == 200
    assert "What just happened" in response.text
    assert 'type="module"' in response.text
    assert "?token=a%26b%3Fc" in response.text
    assert "__UNSTEP_TOKEN_QUERY__" not in response.text
    for asset in ("atc.js", "atc.css", "reasons.json"):
        assert client.get(f"/live/static/atc/{asset}").status_code == 200
    old = client.get("/live/?token=abc", follow_redirects=False)  # the old seat picker is retired: one way in
    assert old.status_code == 307 and old.headers["location"] == "/live/atc/?token=abc"
    assert client.get("/live/static/live.js").status_code == 404
    assert 'id="projector-seat"' in client.get("/live/atc/").text


def test_join_qr_is_served(console):
    from xml.etree import ElementTree
    from qrcode.image.svg import SvgPathImage
    import qrcode

    client, _ = console
    url = "http://testserver/live/?token=a%26b"
    response = client.get("/live/qr.svg", params={"u": url})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    svg = ElementTree.fromstring(response.content)
    assert svg.tag == "{http://www.w3.org/2000/svg}svg"
    assert svg.find("{http://www.w3.org/2000/svg}path") is not None
    assert response.content == qrcode.make(url, image_factory=SvgPathImage).to_string()


@pytest.mark.parametrize("url", [
    "https://example.com/live/", "http://testserver.example.com/live/",
    "http://testserver@example.com/live/", "//testserver/live/",
    "javascript:alert(1)", "http://[broken/live/", "/live/",
])
def test_join_qr_rejects_foreign_or_invalid_urls(console, url):
    client, _ = console
    assert client.get("/live/qr.svg", params={"u": url}).status_code == 400


@pytest.mark.parametrize("frame", [
    {"type": "auth", "password": "wrong"},
    {"type": "decide", "event_id": "never", "approve": True},
    {"type": "auth", "password": None},
    [],
])
def test_wrong_or_missing_password_closes_before_join(console, monkeypatch, frame):
    client, room = console
    monkeypatch.setenv("UNSTEP_ATC_PASSWORD", "tower-secret")
    with client.websocket_connect("/live/ws/atc") as ws:
        assert ws.receive_json() == {"type": "auth_required"}
        ws.send_json(frame)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4003
        assert "ATC password" in closed.value.reason
        assert "tower-secret" not in closed.value.reason
    room.start.assert_not_awaited()
    assert not room.clients["atc"]


def test_right_password_connects_including_unicode(console, monkeypatch):
    client, room = console
    monkeypatch.setenv("UNSTEP_ATC_PASSWORD", "tøwer-✈")
    with client.websocket_connect("/live/ws/atc") as ws:
        assert ws.receive_json()["type"] == "auth_required"
        ws.send_json({"type": "auth", "password": "tøwer-✈"})
        assert ws.receive_json() == {"type": "auth_status", "password_set": True}
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["you"] == "atc"
        assert "tøwer" not in json.dumps(hello)
    room.start.assert_awaited_once()


def test_unset_password_connects_without_auth_frame(console):
    client, _ = console
    with client.websocket_connect("/live/ws/atc") as ws:
        assert ws.receive_json() == {"type": "auth_status", "password_set": False}
        assert ws.receive_json()["you"] == "atc"


@pytest.mark.parametrize("seat", ["N123AB", "H456", "observer"])
def test_other_seats_do_not_need_atc_password(console, monkeypatch, seat):
    client, _ = console
    monkeypatch.setenv("UNSTEP_ATC_PASSWORD", "tower-secret")
    with client.websocket_connect(f"/live/ws/{seat}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["you"] == seat


def test_password_does_not_bypass_gateway_token(console, monkeypatch):
    client, room = console
    monkeypatch.setenv("UNSTEP_GATEWAY_TOKEN", "room-token")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/live/ws/atc?token=wrong"):
            pass
    room.start.assert_not_awaited()


@pytest.mark.parametrize("seat", ["N123AB", "H456", "observer"])
def test_non_atc_cannot_decide_or_toggle_autonomy(console, seat):
    import asyncio
    from types import SimpleNamespace

    _, room = console
    room.decide = AsyncMock()
    room.policy = SimpleNamespace(enabled=True)

    async def attempt():
        await room.handle(seat, {"type": "decide", "event_id": "x", "approve": True})
        await room.handle(seat, {"type": "autonomy", "on": False})

    asyncio.run(attempt())
    room.decide.assert_not_awaited()
    assert room.policy.enabled


REASONS = json.loads((ROOT / "web/live/atc/reasons.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("check", "meaning"), [
    ("tower_transcript", "original words are unavailable"),
    ("addressed", "different plane"),
    ("fresh", "out of date"),
    ("restrictive", "could let the plane move"),
    ("confidence", "not confident enough"),
    ("hint_agrees", "memory disagrees"),
    ("autonomy_on", "Auto-resend is switched off"),
])
def test_plain_english_reason_for_each_failed_check(check, meaning):
    assert meaning in REASONS[check]
    assert "human must" in REASONS[check]
    assert REASONS[check].endswith(".")


def test_reason_mapping_covers_every_policy_check():
    # Detect newly introduced policy checks without mirroring their names here.
    tree = ast.parse((ROOT / "unstep/ground/policy.py").read_text(encoding="utf-8"))
    check_names = {node.args[0].value for node in ast.walk(tree)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == "Check" and isinstance(node.args[0], ast.Constant)}
    assert set(REASONS) == check_names


@pytest.mark.parametrize("hosted", [False, True])
def test_console_uses_pilot_link_and_its_qr(console, monkeypatch, hosted):
    from urllib.parse import parse_qs, urlsplit
    client, _ = console
    monkeypatch.setenv("UNSTEP_GATEWAY_TOKEN", "room&token")
    if hosted:
        monkeypatch.setenv("UNSTEP_PILOT_APP_URL", "https://pilots.example.com")
        monkeypatch.setenv("UNSTEP_ALLOWED_ORIGINS", "https://pilots.example.com")
        monkeypatch.setenv("UNSTEP_PUBLIC_URL", "https://tower.example.com")
    link = client.get("/live/pilot-link").json()
    assert link["hosted"] is hosted
    parts = urlsplit(link["url"])
    assert parse_qs(parts.query)["token"] == ["room&token"]
    if hosted:
        assert parts.hostname == "pilots.example.com"
        assert parse_qs(parts.query)["hub"] == ["https://tower.example.com"]
    else:
        assert parts.path == "/pilot/"
    assert client.get("/live/qr.svg", params={"u": link["url"]}).status_code == 200
    script = client.get("/live/static/atc/atc.js").text
    assert 'fetch("/live/pilot-link")' in script
    assert 'encodeURIComponent(url)' in script
    assert 'location.origin}/pilot/' in script  # the startup placeholder is the pilot app, not the retired seat picker


def test_console_receives_expanding_fleet(console, monkeypatch):
    from unstep.scenario import FLEET
    client, room = console
    monkeypatch.setenv("UNSTEP_MAX_AIRCRAFT", "6")
    with client.websocket_connect("/live/ws/atc") as ws:
        ws.receive_json()  # auth_status
        hello = ws.receive_json()
        assert len([s for s in hello["stations"] if s["kind"] == "aircraft"]) == 2
        ws.receive_json()  # presence
        for expected in FLEET:
            assert client.post("/live/join").json()["station"] == expected[0]
        updates = [ws.receive_json() for _ in range(4)]
        assert all(update["type"] == "stations" for update in updates)
        fleet = [s for s in updates[-1]["stations"] if s["kind"] == "aircraft"]
        assert [(s["id"], s["spoken"], s["name"]) for s in fleet] == [f[:3] for f in FLEET]


def test_console_live_messages_in_javascript():
    """Exercise actual console handlers without speech services or a browser."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for console message tests")
    source = (ROOT / "web/live/atc/atc.js").read_text(encoding="utf-8")
    harness = r"""
const assert = require('node:assert/strict');
class Element {
  constructor() { this.children = []; this.dataset = {}; this.attrs = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(k,v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener() {}
  querySelectorAll() { return []; }
  getComputedTextLength() { return 200; }
}
const nodes = new Map();
global.document = {
  getElementById: id => { if (!nodes.has(id)) nodes.set(id,new Element()); return nodes.get(id); },
  createElement: () => new Element(), createElementNS: () => new Element(),
  createTextNode: text => ({textContent:text}), querySelectorAll: () => []
};
global.sessionStorage = {getItem: () => null, removeItem() {}};
"""
    checks = r"""
const fleet = Array.from({length:6}, (_,i) => ({id:`plane${i}`,kind:'aircraft',name:`Plane ${i}`,spoken:`Aircraft ${i}`}));
receive({type:'hello',stations:fleet.slice(0,2),keyed:{},traces:[],radio:[],now_ms:Date.now()});
receive({type:'stations',stations:fleet});
for (let count=1;count<=6;count++) {
  receive({type:'presence',connected:Object.fromEntries(fleet.slice(0,count).map(s=>[s.id,1]))});
  assert.equal(nodes.get('map-planes').children.length,count);
  assert.equal(nodes.get('radio').children.length,count+1);
  assert.equal(nodes.get('planes').textContent,`${count} ${count===1?'plane':'planes'} connected`);
}
receive({type:'keyed',keyed:{plane2:100,plane3:110}});
assert.match(nodes.get('map-planes').children[2].attrs.class,/transmitting/);
assert.equal(nodes.get('radio').children[3].children[0].children[0].textContent,'ON AIR');
receive({type:'stepon_live',stations:['plane2','plane3'],since_ms:110});
assert.equal(nodes.get('happened').textContent,'Plane 2 and Plane 3 are talking at the same time. Someone will miss part of this call.');
assert.equal(nodes.get('radio').children[3].children.at(-1).textContent,'TALKED OVER');
receive({type:'keyed',keyed:{}});
assert.doesNotMatch(nodes.get('map-planes').children[2].attrs.class,/transmitting/);
const tx = [{station:'plane2',start_ms:100,end_ms:200},{station:'plane3',start_ms:110,end_ms:200}];
receive({type:'radio',transmissions:tx,overlaps:[]});
assert.equal(state.liveOverlap.size,0);
assert.equal(nodes.get('radio').children[3].children.length,2);
receive({type:'stepon_live',stations:['plane2','plane3'],since_ms:110});
receive({type:'radio',transmissions:tx,overlaps:[{stations:['plane2','plane3'],start_ms:110,end_ms:200}]});
assert.equal(nodes.get('radio').children[3].children.at(-1).textContent,'TALKED OVER');
receive({type:'stepon_live',stations:['plane2','plane3'],since_ms:300});
receive({type:'radio',transmissions:tx,overlaps:[]});
assert.equal(state.liveOverlap.size,2);
receive({type:'presence',connected:{}});
assert.equal(nodes.get('map-planes').children.length,0);
"""
    # stdin, not -e: Windows caps a command line at about 32 KB and atc.js is larger
    result = subprocess.run([node, "-"], input=harness + source.split("// Audio is explicitly")[0] + checks,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
