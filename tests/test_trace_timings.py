"""P1: every event trace carries a timeline on the hub clock, for the console's waterfall.
P2 shows up on it too: Elastic's readback verdict is a trace step and a timing."""

import asyncio

from unstep.clock import now_ms
from unstep.live.radio import Transmission

from tests.test_live_room import clip, make_room, only_trace, stepped_on, wait_for  # noqa: F401 (fixture)


def test_trace_has_a_timeline_from_the_squeal_to_the_elastic_check(make_room):
    async def go():
        room, atc, pilot = await make_room()
        # Live keys first: the tower and the helicopter both press talk.
        await room.handle("atc", {"type": "key", "down": True})
        await room.handle("H456", {"type": "key", "down": True})
        await room.handle("atc", {"type": "key", "down": False})
        await room.handle("H456", {"type": "key", "down": False})
        room.stepons[-1]["since_ms"] = now_ms() - 10_000 + 1300  # same moment as the clips below
        await stepped_on(room)
        await wait_for(lambda: only_trace(room) and only_trace(room)["status"] in ("needs_you", "delivered"))
        if only_trace(room)["status"] == "needs_you":
            await room.decide(only_trace(room)["event_id"], approve=True)
        await wait_for(lambda: only_trace(room)["status"] == "delivered")
        await room.transmit(Transmission("N123AB", now_ms() - 8000, clip("correct_readback.wav"),
                                         text="Hold short runway three three, Cessna one two three"))
        await wait_for(lambda: any(s["kind"] == "percolate" for s in only_trace(room)["steps"]))
        trace = only_trace(room)
        stages = [t["stage"] for t in trace["timings"]]
        for stage in ("call_start", "keys_overlap", "keys_detected", "stepped_on", "call_end", "event_raised",
                      "proposed", "approved", "spoken", "readback", "elastic_check"):
            assert stage in stages, (stage, stages)
        at = {t["stage"]: t["at_ms"] for t in trace["timings"]}
        assert at["call_start"] <= at["stepped_on"] <= at["call_end"] <= at["event_raised"] <= at["proposed"]
        assert at["approved"] <= at["spoken"] and at["readback"] <= at["elastic_check"]
        check = next(t for t in trace["timings"] if t["stage"] == "elastic_check")
        assert check["by"] == "local" and check["ms"] is not None
        step = next(s for s in trace["steps"] if s["kind"] == "percolate")
        assert step["data"]["match"] is True and "agrees with the slot check" in step["text"]
        sent = [m for m in atc.messages if m["type"] == "trace"][-1]["trace"]
        assert sent["timings"] == trace["timings"]  # the console gets it as is
        await room.stop()

    asyncio.run(go())


def test_stt_final_timings_per_hop(make_room):
    async def go():
        from unstep.ground.tower import FakeTowerTranscriber

        room, atc, pilot = await make_room()
        room.tower_transcriber = FakeTowerTranscriber()  # the clip path, timed like the real one
        await stepped_on(room)
        await wait_for(lambda: only_trace(room) and {"cockpit_stt_final", "tower_stt_final"}
                       <= {t["stage"] for t in only_trace(room)["timings"]})
        stages = {t["stage"]: t for t in only_trace(room)["timings"]}
        assert stages["tower_stt_final"]["ms"] >= 0 and stages["tower_stt_final"]["by"] == "cartesia"
        assert stages["cockpit_stt_final"]["ms"] is not None and stages["cockpit_stt_final"]["by"] == "cockpit:N123AB"
        await room.stop()

    asyncio.run(go())


def test_hint_step_names_its_memory_backend_and_elastic_ms_is_rounded(make_room):
    import re

    async def go():
        room, atc, pilot = await make_room()
        await stepped_on(room)
        await wait_for(lambda: only_trace(room) and any(s["kind"] == "hint" for s in only_trace(room)["steps"]))
        hint = next(s for s in only_trace(room)["steps"] if s["kind"] == "hint")
        assert hint["data"]["backend"] == "local"  # the console names Moss only when the event says so
        if only_trace(room)["status"] == "needs_you":
            await room.decide(only_trace(room)["event_id"], approve=True)
        await room.handle("N123AB", {"type": "say", "text": "Hold short runway three three, Cessna one two three."})
        await wait_for(lambda: any(s["kind"] == "percolate" for s in only_trace(room)["steps"]), timeout=30)
        text = next(s for s in only_trace(room)["steps"] if s["kind"] == "percolate")["text"]
        assert not re.search(r"\d+\.\d{3,} ms", text)
        await room.stop()

    asyncio.run(go())
