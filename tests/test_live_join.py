"""Live room for a crowd: pilots join on demand, keys are shared live, phones sync their clocks."""

import asyncio

from fastapi.testclient import TestClient

from unstep.cockpit.memory import LocalMemory
from unstep.cockpit.phraseology import callsigns_match, spoken_callsign
from unstep.cockpit.seed import flight_docs
from unstep.cockpit.tts import FakeTTS
from unstep.gateway.server import create_app
from unstep.gateway.sink import MemorySink
from unstep.live import room as room_mod
from unstep.live.app import create_live_app
from unstep.live.room import LiveRoom
from unstep.scenario import FLEET


class FakeBrowser:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)

    def of(self, kind):
        return [m for m in self.messages if m.get("type") == kind]


def room(monkeypatch, **kw):
    monkeypatch.setattr(room_mod, "create_memory", LocalMemory)
    return LiveRoom(create_app(MemorySink()).state.gateway, live=False, tts_factory=lambda v: FakeTTS(),
                    advisory_tts=FakeTTS(), **kw)


def test_fleet_callsigns_never_match_each_other():
    for a, *_ in FLEET:
        for b, *_ in FLEET:
            assert callsigns_match(a, b) == (a == b), (a, b)
    assert spoken_callsign("N789PA") == "Piper 7-8-9"
    assert callsigns_match("Piper 7-8-9", "N789PA")
    assert all(d.text.startswith("Piper 7-8-9,") for d in flight_docs("N789PA"))


def test_join_fills_free_seats_then_adds_aircraft(monkeypatch):
    async def go():
        r = room(monkeypatch)
        await r.start()
        atc = FakeBrowser()
        await r.join("atc", atc)
        first = await r.claim_aircraft()
        second = await r.claim_aircraft()  # first is claimed, not yet connected
        assert (first.id, second.id) == ("N123AB", "H456")
        await r.join(first.id, FakeBrowser())
        third = await r.claim_aircraft()
        assert third.id == "N789PA" and third.spoken == "Piper 7-8-9"
        assert "N789PA" in r.edges and "N789PA" in r.stations  # a cockpit agent of its own
        await asyncio.sleep(0.05)
        update = atc.of("stations")[-1]
        assert "N789PA" in [s["id"] for s in update["stations"]]
        assert any(n["id"] == "cockpit:N789PA" for n in update["graph"])
        await r.stop()

    asyncio.run(go())


def test_join_stops_at_the_fleet_limit(monkeypatch):
    monkeypatch.setenv("UNSTEP_MAX_AIRCRAFT", "2")

    async def go():
        r = room(monkeypatch)
        assert (await r.claim_aircraft()).id == "N123AB"
        assert (await r.claim_aircraft()).id == "H456"
        assert await r.claim_aircraft() is None

    asyncio.run(go())


def test_two_keys_down_is_a_live_stepped_on_alert(monkeypatch):
    async def go():
        r = room(monkeypatch)
        pilot = FakeBrowser()
        await r.join("N123AB", pilot)
        await r.handle("atc", {"type": "key", "down": True})
        await r.handle("H456", {"type": "key", "down": True})
        await asyncio.sleep(0.05)
        keyed = pilot.of("keyed")
        assert keyed[-1]["keyed"].keys() == {"atc", "H456"}
        alert = pilot.of("stepon_live")
        assert len(alert) == 1 and alert[0]["stations"] == ["H456", "atc"]
        assert alert[0]["uplink_ms"] >= 0
        r.leave("N123AB", pilot)
        r.clients["H456"].add(object())
        r.leave("H456", next(iter(r.clients["H456"])))  # last H456 browser gone: key released
        assert "H456" not in r.key_since and "H456" not in r.keyed

    asyncio.run(go())


def test_hosted_pilot_app_can_join_with_clock_sync(monkeypatch):
    monkeypatch.setattr(room_mod, "create_memory", LocalMemory)
    monkeypatch.delenv("UNSTEP_GATEWAY_TOKEN", raising=False)
    monkeypatch.setenv("UNSTEP_ALLOWED_ORIGINS", "https://*.vercel.app")
    client = TestClient(create_live_app(live=False, sink=MemorySink()))
    origin = {"origin": "https://unstep-pilot.vercel.app"}
    r = client.post("/live/join", headers=origin)
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == origin["origin"]
    seat = r.json()
    assert seat["station"] == "N123AB" and seat["spoken"] == "Cessna 1-2-3"
    with client.websocket_connect(f"/live/ws/{seat['station']}", headers=origin) as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "ping", "t0": 123})
        while (m := ws.receive_json())["type"] != "pong":
            pass
        assert m["t0"] == 123 and m["t1"] > 0
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/live/ws/H456", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()


def test_join_needs_the_room_token_when_set(monkeypatch):
    monkeypatch.setattr(room_mod, "create_memory", LocalMemory)
    monkeypatch.setenv("UNSTEP_GATEWAY_TOKEN", "s3cret")
    client = TestClient(create_live_app(live=False, sink=MemorySink()))
    assert client.post("/live/join").status_code == 403
    assert client.post("/live/join?token=s3cret").status_code == 200
