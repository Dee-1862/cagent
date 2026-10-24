"""Plane memory goes to one flight log when a flight ends; per-aircraft sessions are never pushed."""

import asyncio

from fastapi.testclient import TestClient

from unstep.cockpit.memory import Doc, LocalMemory
from unstep.cockpit.seed import COCKPIT
from unstep.live import room as room_mod
from unstep.live.app import create_live_app
from unstep.live.flightlog import FlightLog, flight_log_index

from tests.test_live_join import FakeBrowser, room as make_join_room


class SharedClient(LocalMemory):
    """A shared client like the live room's Moss client, offline: one object for every plane."""

    backend = "moss"

    def __init__(self):
        super().__init__()
        self.push_calls = []

    async def push(self, index, writer):
        self.push_calls.append(index)
        return await super().push(index, writer)


def test_copy_on_end_single_push_and_session_dropped():
    async def go():
        shared = SharedClient()
        log = FlightLog(shared, "118.700")
        shared.register_index("flight-N789PA", COCKPIT)
        await shared.add_docs("flight-N789PA", [Doc("clr-1", "Piper 7-8-9, hold short runway 33",
                                                    {"callsign": "N789PA", "type": "clearance", "ts": 1})], COCKPIT)
        rec = await log.archive("N789PA", shared, "flight-N789PA", "phone gone for 20 s")
        assert rec["docs"] == 1 and "flight-N789PA" not in shared.indexes  # the plane's session is freed
        copied = list(shared.indexes[flight_log_index("118.700")].values())[0]
        assert copied.metadata["callsign"] == "N789PA" and copied.metadata["kind"] == "clearance"
        assert copied.metadata["flight_id"] == rec["flight_id"] and copied.metadata["ended_at"]
        assert log.status()["text"] == "Flight log: 0 flights saved to Moss Cloud"  # not pushed yet
        await log.push()
        await log.push()  # nothing new: no second push
        assert shared.push_calls == ["flightlog-118.700"]
        assert log.status()["text"] == "Flight log: 1 flights saved to Moss Cloud"
        found = await log.search("hold short", callsign="N789PA")
        assert found["docs"][0]["callsign"] == "N789PA"

    asyncio.run(go())


def test_failed_push_is_kept_and_retried():
    class Flaky(SharedClient):
        fail = True

        async def push(self, index, writer):
            if self.fail:
                self.fail = False
                raise ConnectionError("moss down")
            return await super().push(index, writer)

    async def go():
        m = Flaky()
        log = FlightLog(m, "118.700")
        m.register_index("flight-A", COCKPIT)
        await m.add_docs("flight-A", [Doc("x", "hold short", {"type": "clearance"})], COCKPIT)
        await log.archive("A", m, "flight-A", "test")
        assert await log.push() is None and log.push_pending
        assert (await log.push())["ok"] and not log.push_pending

    asyncio.run(go())


def test_room_archives_on_seat_free_reset_and_stop_and_never_pushes_a_plane(monkeypatch):
    shared = SharedClient()
    monkeypatch.setattr(room_mod, "create_memory", lambda: shared)

    async def go():
        r = make_join_room(monkeypatch)
        monkeypatch.setattr(room_mod, "create_memory", lambda: shared)
        await r.start()
        r.flight_log = FlightLog(shared, r.frequency)  # offline rooms keep a local log; use the shared fake
        seats = [await r.claim_aircraft() for _ in range(3)]
        walk_up = next(s for s in seats if s.id not in room_mod.TEAM_STATIONS)
        atc = FakeBrowser()
        await r.join("atc", atc)
        await r.free_seat(walk_up.id, "phone gone for 20 s")
        await asyncio.sleep(0.05)
        assert [f["callsign"] for f in r.flight_log.flights] == [walk_up.callsign]
        assert any(m["type"] == "flightlog" for m in atc.messages)
        await r.stop()
        assert {f["callsign"] for f in r.flight_log.flights} >= {"N123AB", "H456"}
        assert shared.push_calls and set(shared.push_calls) == {f"flightlog-{r.frequency}"}

    asyncio.run(go())


def test_flightlog_route(monkeypatch):
    r = make_join_room(monkeypatch)
    with TestClient(create_live_app(live=False, room=r)) as client:
        with client.websocket_connect("/live/ws/observer") as ws:
            ws.receive_json()
        body = client.get("/live/flightlog?q=hold%20short").json()
    assert body["status"]["index"].startswith("flightlog-") and "docs" in body["results"]


def test_moss_down_keeps_the_flight_log_local():
    class Down(SharedClient):
        async def add_docs(self, index, docs, writer):
            if index.startswith("flightlog-"):
                raise ConnectionError("moss down")
            return await super().add_docs(index, docs, writer)

    async def go():
        m = Down()
        log = FlightLog(m, "118.700")
        m.register_index("flight-A", COCKPIT)
        await m.add_docs("flight-A", [Doc("x", "hold short", {"type": "clearance"})], COCKPIT)
        rec = await log.archive("A", m, "flight-A", "test")
        assert rec["docs"] == 1 and log.memory.backend == "local" and log.status()["backend"] == "local"

    asyncio.run(go())
