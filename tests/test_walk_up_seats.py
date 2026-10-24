"""R22: walk-up pilots get seats that free themselves, a presenter reset, and a friendly full-room answer."""

import asyncio

from fastapi.testclient import TestClient

from unstep.live import room as room_mod
from unstep.live.app import create_live_app

from tests.test_live_join import FakeBrowser, room as make_join_room


def test_a_walk_up_seat_is_freed_when_the_phone_is_gone(monkeypatch):
    monkeypatch.setattr(room_mod, "SEAT_FREE_S", 0.05)
    r = make_join_room(monkeypatch)

    async def go():
        await r.start()
        seats = [await r.claim_aircraft() for _ in range(3)]
        walk_up = next(s for s in seats if s.id not in room_mod.TEAM_STATIONS)
        phone, team_phone, atc = FakeBrowser(), FakeBrowser(), FakeBrowser()
        await r.join(walk_up.id, phone)
        await r.join("N123AB", team_phone)
        await r.join("atc", atc)
        assert walk_up.callsign in r.edges
        r.leave(walk_up.id, phone)
        r.leave("N123AB", team_phone)
        await asyncio.sleep(0.3)
        assert walk_up.id not in r.stations and walk_up.callsign not in r.edges
        assert "N123AB" in r.stations and "N123AB" in r.edges  # team planes are never freed
        assert any(m["type"] == "stations" and walk_up.id not in [s["id"] for s in m["stations"]]
                   for m in atc.messages)
        again = await r.claim_aircraft()  # the plane goes back to the fleet
        assert again is not None
        await r.stop()

    asyncio.run(go())


def test_presenter_reset_frees_walk_ups_and_clears_the_room(monkeypatch):
    r = make_join_room(monkeypatch)

    async def go():
        await r.start()
        seats = [await r.claim_aircraft() for _ in range(3)]
        walk_up = next(s for s in seats if s.id not in room_mod.TEAM_STATIONS)
        phone, atc = FakeBrowser(), FakeBrowser()
        await r.join(walk_up.id, phone)
        await r.join("atc", atc)
        r.traces["evt-1"] = {"event_id": "evt-1", "callsign": "N123AB", "status": "delivered", "steps": []}
        r.radio_log.append({"type": "radio"})
        await r.handle(walk_up.id, {"type": "reset"})  # only the controller seat may reset
        assert walk_up.id in r.stations and r.traces
        await r.handle("atc", {"type": "reset"})
        assert walk_up.id not in r.stations and not r.traces and not r.radio_log
        assert {"N123AB", "H456"} <= set(r.stations) and r.reset_at > 0
        assert any(m["type"] == "seat_freed" for m in phone.messages)
        await asyncio.sleep(0.05)
        assert any(m["type"] == "room_reset" for m in atc.messages)
        await r.stop()

    asyncio.run(go())


def test_full_room_gets_a_friendly_answer(monkeypatch):
    monkeypatch.setenv("UNSTEP_MAX_AIRCRAFT", "2")
    r = make_join_room(monkeypatch)
    with TestClient(create_live_app(live=False, room=r)) as client:
        assert client.post("/live/join").status_code == 200
        assert client.post("/live/join").status_code == 200
        full = client.post("/live/join")
        assert full.status_code == 409
        assert full.json() == {"error": "All 2 planes are taken. Watch on the projector.", "full": True}
