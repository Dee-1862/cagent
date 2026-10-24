"""M-2: ordering, grouping and our own score floor in the memory layer, and their uses."""

import asyncio

from unstep.clock import now_ms
from unstep.cockpit.hint import derive_hint
from unstep.cockpit.memory import Doc, LocalMemory, above_floor, group_docs, order_docs
from unstep.cockpit.queries import answer_query, classify_intent
from unstep.cockpit.seed import COCKPIT, seed
from unstep.scenario import CALLSIGN, T0

from tests.test_live_room import make_room, only_trace, stepped_on, wait_for  # noqa: F401 (fixture)


def run(coro):
    return asyncio.run(coro)


def test_order_docs_compares_numbers_as_numbers_and_puts_missing_last():
    docs = [Doc("a", "x", {"ts": "9"}), Doc("b", "x", {"ts": "100"}), Doc("c", "x", {"ts": "10"}), Doc("d", "x", {})]
    assert [d.id for d in order_docs(docs, "ts", ascending=False)] == ["b", "c", "a", "d"]  # text order would be c, b, a
    assert [d.id for d in order_docs(docs, "ts", ascending=True, limit=2)] == ["a", "c"]
    assert [d.id for d in order_docs(docs, None)] == ["a", "b", "c", "d"]


def test_group_docs_makes_one_unit_per_parent_in_order():
    docs = [Doc("1", "tower said hold short", {"ts": "10", "exchange": "e1"}),
            Doc("2", "pilot read back", {"ts": "20", "exchange": "e1"}),
            Doc("3", "taxi", {"ts": "5"})]
    units = group_docs(docs, "exchange", "ts")
    assert [u.id for u in units] == ["exchange:e1", "3"]  # newest unit first
    assert units[0].text == "tower said hold short | pilot read back" and units[0].metadata["members"] == ["1", "2"]


def test_floor_is_ours_and_applies_to_scores():
    docs = [Doc("a", "x", {}, score=0.9), Doc("b", "x", {}, score=0.2)]
    assert [d.id for d in above_floor(docs, 0.25)] == ["a"] and above_floor(docs, None) == docs

    async def go():
        m = LocalMemory()
        m.register_index("f", COCKPIT)
        await m.add_docs("f", [Doc("x", "hold short runway thirty three", {})], COCKPIT)
        weak = await m.query("f", "banana runway", top_k=3, alpha=0.5)
        floor = weak.docs[0].score + 0.01
        assert (await m.query("f", "banana runway", alpha=0.5, min_score=floor)).docs == []

    run(go())


def test_hint_evidence_says_when_the_best_match_is_below_the_floor(monkeypatch):
    m = LocalMemory()
    airport, flight = run(seed(m, CALLSIGN, t0=T0))
    monkeypatch.setenv("UNSTEP_MOSS_MIN_SCORE", "0.99")
    evidence = {}
    hint = run(derive_hint(m, CALLSIGN, "Cessna 123, short runway 30", flight, airport, now=T0, evidence=evidence))
    assert evidence["below_floor"] is True and evidence["floor"] == 0.99 and "top_hit_id" not in evidence
    assert hint.kind == "restrictive"  # the hint rule is unchanged: only the evidence is gated
    monkeypatch.setenv("UNSTEP_MOSS_MIN_SCORE", "0.1")
    evidence = {}
    run(derive_hint(m, CALLSIGN, "Cessna 123, short runway 30", flight, airport, now=T0, evidence=evidence))
    assert evidence.get("top_hit_id") and not evidence.get("below_floor")


def test_whole_exchange_answer_reads_the_exchange_as_one_ordered_unit():
    assert classify_intent("What was the whole exchange?") == "exchange"

    async def go():
        m = LocalMemory()
        m.register_index("flight-N1", COCKPIT)
        now = now_ms()
        rows = [("h1", "Cessna 1-2-3 [static]", "heard", now - 5000, "evt-1"),
                ("adv", "Likely hold short runway 33. Awaiting controller.", "advisory", now - 4000, "evt-1"),
                ("clr", "Cessna 1-2-3, hold short runway 33", "clearance", now - 3000, "evt-1"),
                ("rb", "Hold short runway 33, Cessna 1-2-3", "readback", now - 2000, "evt-1"),
                ("old", "Cessna 1-2-3, taxi via Bravo", "clearance", now - 90_000, "evt-0")]
        await m.add_docs("flight-N1", [Doc(i, t, {"callsign": "N1", "type": k, "ts": ts, "exchange": e})
                                       for i, t, k, ts, e in rows], COCKPIT)
        q = await answer_query(m, "flight-N1", "N1", "What was the whole exchange?")
        text = q.answer
        assert text.index("heard") < text.index("Unstep said") < text.index("approved") < text.index("pilot read back")
        assert "taxi via Bravo" not in text and "Likely" not in text  # only the newest exchange; the guess is dropped
        assert q.source_doc_id == "flight-N1/rb" and q.moss_ms is not None

    run(go())


def test_room_stamps_exchange_on_what_the_plane_holds(make_room):
    async def go():
        room, atc, pilot = await make_room()
        await stepped_on(room)
        await wait_for(lambda: only_trace(room) is not None)
        edge = room.edges["N123AB"]
        await wait_for(lambda: any(d.metadata.get("exchange") for d in edge.memory.indexes[edge.flight_idx].values()))
        q = await edge.ask("What was the whole exchange?")
        assert "heard" in q.answer or "Unstep said" in q.answer
        await room.stop()

    asyncio.run(go())


def test_moss_backend_asks_for_a_sort_but_does_not_trust_it_and_survives_a_refusal():
    from types import SimpleNamespace

    from unstep.cockpit.memory import MossMemory

    calls = []

    class Session:
        async def get_docs(self, options):
            calls.append(options)
            if getattr(options, "sort_by", None) and Session.refuse:
                raise RuntimeError("sort_by not supported here")
            return [SimpleNamespace(id=i, text=t, metadata={"ts": ts, "callsign": "N1"})
                    for i, t, ts in [("a", "old", "9"), ("b", "new", "100"), ("c", "mid", "10")]]  # unsorted

    mem = object.__new__(MossMemory)
    mem.client, mem.sessions, mem.owners = None, {"flight-N1": Session()}, {}
    for refuse in (False, True):
        Session.refuse = refuse
        got = run(mem.fetch("flight-N1", filter={"callsign": {"$eq": "N1"}}, sort_by="ts", ascending=False, limit=2))
        assert [d.id for d in got.docs] == ["b", "c"]  # numeric, newest first, cut to 2: our ordering, not Moss's
    assert getattr(calls[0], "sort_by", None) == "ts" and getattr(calls[-1], "sort_by", None) in (None, "")
