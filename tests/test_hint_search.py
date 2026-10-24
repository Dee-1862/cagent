"""M3: the garbled fragment the cockpit heard is a Moss search over the plane's own clearances."""

import asyncio

from unstep.cockpit.hint import derive_hint, search_query
from unstep.cockpit.memory import Doc, LocalMemory
from unstep.cockpit.seed import COCKPIT, seed
from unstep.scenario import CALLSIGN, T0

from tests.test_live_room import make_room, only_trace, stepped_on, wait_for  # noqa: F401 (fixture)


def run(coro):
    return asyncio.run(coro)


def test_garbled_fragment_finds_the_taxi_clearance():
    m = LocalMemory()
    airport, flight = run(seed(m, CALLSIGN, t0=T0))
    evidence = {}
    hint = run(derive_hint(m, CALLSIGN, "Cessna 123, short runway 30", flight, airport, now=T0, evidence=evidence))
    assert hint.kind == "restrictive" and hint.text == "hold short Runway 33"
    assert evidence["query"] == "Cessna 123, short runway 30" and evidence["alpha"] == 0.5
    assert evidence["top_hit_id"] == f"{flight}/clr-0007" and evidence["agrees"] is True
    assert evidence["score"] > 0 and evidence["search_ms"] >= 0
    assert hint.moss_ms >= evidence["search_ms"]


def test_an_older_better_match_never_beats_the_newest_clearance():
    m = LocalMemory()
    airport, flight = run(seed(m, CALLSIGN, t0=T0))
    run(m.add_docs(flight, [Doc("clr-old", "Cessna 1-2-3, hold short runway 30, short of runway 30",
                                {"callsign": CALLSIGN, "type": "clearance", "ts": T0 - 600_000})], writer=COCKPIT))
    evidence = {}
    hint = run(derive_hint(m, CALLSIGN, "Cessna 123, short runway 30", flight, airport, now=T0, evidence=evidence))
    assert evidence["top_hit_id"] == f"{flight}/clr-old" and evidence["agrees"] is False
    assert hint.source_doc_id == f"{flight}/clr-0007" and hint.text == "hold short Runway 33"


def test_search_query_drops_noise_markers_and_failures_keep_the_hint():
    assert search_query("Cessna 1-2-3 [static] hold [blocked]") == "Cessna 1-2-3 hold"

    class Flaky(LocalMemory):
        async def query(self, *a, **k):
            raise ConnectionError("moss down")

    m = Flaky()
    airport, flight = run(seed(m, CALLSIGN, t0=T0))
    evidence = {}
    hint = run(derive_hint(m, CALLSIGN, "Cessna 123 short runway 30", flight, airport, now=T0, evidence=evidence))
    assert evidence.get("error") == "search failed" or hint.kind == "none"  # never a crash


def test_console_trace_shows_the_moss_search(make_room):
    async def go():
        room, atc, pilot = await make_room()
        await stepped_on(room)
        await wait_for(lambda: only_trace(room) and any(s["kind"] == "moss_search" for s in only_trace(room)["steps"]))
        step = next(s for s in only_trace(room)["steps"] if s["kind"] == "moss_search")
        assert "Moss searched this plane's session" in step["text"] and step["data"]["query"]
        assert any(t["stage"] == "moss_search" for t in only_trace(room)["timings"])
        await room.stop()

    asyncio.run(go())


def test_a_stale_clearance_says_why_there_is_no_hint():
    m = LocalMemory()
    airport, flight = run(seed(m, CALLSIGN, t0=T0))
    evidence = {}
    hint = run(derive_hint(m, CALLSIGN, "Cessna 123, short runway 30", flight, airport,
                           now=T0 + 60 * 60_000, evidence=evidence))
    assert hint.kind == "none" and evidence["top_hit_id"] == f"{flight}/clr-0007"
    assert "too old to use" in evidence["no_hint"]
