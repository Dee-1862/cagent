"""The Moss connection checklist: warm sessions, a failed client falls back, a blocked push says why."""

import asyncio

from unstep.cockpit import memory as memory_mod
from unstep.cockpit.memory import Doc, LocalMemory, create_memory
from unstep.live.flightlog import FlightLog

COCKPIT = "cockpit"


def test_a_plane_warms_its_flight_session_once_at_start():
    from unstep.cockpit.edge import AudioOut, CockpitEdge
    from unstep.cockpit.stt import FakeManualSTT
    from unstep.cockpit.tts import FakeTTS

    class Warm(LocalMemory):
        def __init__(self):
            super().__init__()
            self.warmed: list[str] = []

        async def warm(self, index):
            self.warmed.append(index)
            return 1.5

    async def go():
        mem = Warm()
        edge = CockpitEdge(memory=mem, tts=FakeTTS(word_s=0.001), audio_out=AudioOut(None),
                           manual_stt_factory=lambda: FakeManualSTT([]))
        await edge.start(connect=False)
        assert mem.warmed == [edge.flight_idx]
        assert edge.warm_ms == 1.5

    asyncio.run(go())


def test_a_client_that_cannot_be_created_falls_back_to_local_memory(monkeypatch):
    class Broken:
        def __init__(self, *a, **k):
            raise RuntimeError("bad key format")

    monkeypatch.setenv("MOSS_PROJECT_ID", "p")
    monkeypatch.setenv("MOSS_PROJECT_KEY", "k")
    monkeypatch.setattr(memory_mod, "MossMemory", Broken)
    assert isinstance(create_memory(), LocalMemory)


def test_a_blocked_cloud_push_is_reported_with_its_reason():
    class Blocked(LocalMemory):
        async def push(self, index, writer):
            raise PermissionError("The project's usage limit has been reached; billing must be updated")

    async def go():
        m = Blocked()
        log = FlightLog(m, "118.700")
        m.register_index("flight-A", COCKPIT)
        await m.add_docs("flight-A", [Doc("x", "hold short", {"type": "clearance"})], COCKPIT)
        await log.archive("A", m, "flight-A", "test")
        assert await log.push() is None and log.push_pending
        status = log.status()
        assert not status["pushed"] and "usage limit" in status["text"]
        assert status["last_error"]["error"] == "PermissionError"

    asyncio.run(go())
