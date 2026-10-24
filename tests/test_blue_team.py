"""Regression tests for the red-team findings (blue-team fixes 1-8)."""

import asyncio
from types import SimpleNamespace

import pytest

from unstep.cockpit.edge import AudioOut, CockpitEdge, GatewayLink
from unstep.cockpit.hint import advisory_text, derive_hint, likely_instruction
from unstep.cockpit.memory import Doc, LocalMemory, MossMemory, matches, to_moss_filter
from unstep.cockpit.queries import NO_RECORD, answer_query, classify_intent, record
from unstep.cockpit.seed import COCKPIT, seed
from unstep.cockpit.stt import FakeManualSTT, FakeTurnSTT
from unstep.cockpit.tts import FakeTTS
from unstep.scenario import CALLSIGN, T0


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def mem():
    m = LocalMemory()
    airport, flight = run(seed(m))
    return m, airport, flight


def add_clr(m, flight, doc_id, text, ts):
    run(m.add_docs(flight, [Doc(id=doc_id, text=text, metadata={"callsign": CALLSIGN, "type": "clearance", "ts": ts})],
                   writer=COCKPIT))


# 1. Moss filter format -------------------------------------------------------


def test_moss_filter_translator_uses_field_condition_and_strings():
    flt = {"$and": [{"callsign": {"$eq": "N123AB"}}, {"type": {"$eq": "clearance"}}, {"ts": {"$gte": 5}}]}
    assert to_moss_filter(flt) == {"$and": [
        {"field": "callsign", "condition": {"$eq": "N123AB"}},
        {"field": "type", "condition": {"$eq": "clearance"}},
        {"field": "ts", "condition": {"$gte": "5"}},
    ]}
    assert to_moss_filter({"type": {"$eq": "runway"}}) == {"field": "type", "condition": {"$eq": "runway"}}
    assert to_moss_filter({"type": "advisory"}) == {"field": "type", "condition": {"$eq": "advisory"}}
    assert to_moss_filter({"type": {"$in": ["a", 1]}}) == {"field": "type", "condition": {"$in": ["a", "1"]}}
    assert to_moss_filter({"$or": [{"a": 1}, {"b": {"$lt": 2}}]}) == {"$or": [
        {"field": "a", "condition": {"$eq": "1"}}, {"field": "b", "condition": {"$lt": "2"}}]}
    assert to_moss_filter({"a": 1, "b": 2}) == {"$and": [
        {"field": "a", "condition": {"$eq": "1"}}, {"field": "b", "condition": {"$eq": "2"}}]}
    assert to_moss_filter(None) is None and to_moss_filter({}) is None


def test_local_filter_semantics_unchanged():
    md = {"callsign": "N123AB", "type": "clearance", "ts": 100}
    assert matches(md, {"$and": [{"callsign": {"$eq": "N123AB"}}, {"ts": {"$gte": 50}}]})
    assert not matches(md, {"ts": {"$gte": 101}})


def test_moss_memory_sends_translated_filter():
    seen = {}

    class FakeSession:
        async def query(self, text, options):
            seen["filter"] = options.filter
            return SimpleNamespace(docs=[], time_taken_ms=1.0)

    mm = MossMemory.__new__(MossMemory)
    mm.owners, mm.sessions = {}, {"flight-X": FakeSession()}
    run(mm.query("flight-X", "q", filter={"$and": [{"callsign": {"$eq": "N1"}}, {"ts": {"$gte": 7}}]}))
    assert seen["filter"] == {"$and": [{"field": "callsign", "condition": {"$eq": "N1"}},
                                       {"field": "ts", "condition": {"$gte": "7"}}]}


# 2. Hint only from the newest, recent taxi clearance ---------------------------


def test_hint_never_comes_from_superseded_clearance(mem):
    m, airport, flight = mem
    add_clr(m, flight, "clr-0009", "Cessna 1-2-3, Runway 28L, taxi via Alpha", T0)
    hint = run(derive_hint(m, CALLSIGN, "Cessna 1-2-3 hold [squeal] Bravo", flight, airport, now=T0))
    assert hint.kind == "none" or hint.text == "hold short Runway 28L"
    assert "33" not in (hint.text or "")


def test_hint_needs_recent_clearance(mem):
    m, airport, flight = mem
    stale = run(derive_hint(m, CALLSIGN, "Cessna 1-2-3 [static]", flight, airport, now=T0 + 16 * 60_000))
    assert stale.kind == "none"
    fresh = run(derive_hint(m, CALLSIGN, "Cessna 1-2-3 [static]", flight, airport, now=T0, max_age_ms=60 * 60_000))
    assert fresh.text == "hold short Runway 33"


# 3. Last clearance is newest by ts ----------------------------------------------


def test_last_clearance_is_newest_even_with_no_shared_words(mem):
    m, airport, flight = mem
    add_clr(m, flight, "clr-0010", "Contact tower one one niner point one", T0 + 1000)
    q = run(answer_query(m, flight, CALLSIGN, "what was my last clearance"))
    assert q.source_doc_id.endswith("clr-0010") and "tower" in q.answer


# 4. Say again never reads back a Likely hint ------------------------------------


def test_repeat_last_clearance_is_last_clearance_intent():
    assert classify_intent("Unstep, repeat the last clearance") == "last_clearance"


def test_say_again_never_reads_unapproved_hint(mem):
    m, airport, flight = mem
    run(record(m, flight, CALLSIGN, "adv-1",
               "Advisory. Transmission blocked. Likely hold short Runway 33. Awaiting controller.", "advisory", ts=T0 + 10))
    for question in ("say again", "Unstep, repeat the last clearance", "what was my last clearance"):
        q = run(answer_query(m, flight, CALLSIGN, question))
        assert "Likely" not in q.answer and q.answer.startswith("Advisory.")


def test_say_again_drops_hint_after_newer_clearance(mem):
    m, airport, flight = mem
    run(record(m, flight, CALLSIGN, "adv-1",
               "Advisory. Transmission blocked. Likely hold short Runway 33. Awaiting controller.", "advisory", ts=T0 + 10))
    add_clr(m, flight, "clr-0011", "Cessna 1-2-3, hold short Runway 28L", T0 + 20)
    q = run(answer_query(m, flight, CALLSIGN, "say again"))
    assert q.source_doc_id.endswith("clr-0011") and "Runway 28L" in q.answer and "Likely" not in q.answer


# 5. Runway choice and go around ---------------------------------------------------


def test_likely_instruction_uses_hold_short_runway():
    assert likely_instruction("Runway 33, taxi via Charlie, hold short Runway 28L") == "hold short Runway 28L"
    assert likely_instruction("Taxi via Charlie, cross Runway 28L, Runway 33") is None  # cross is permissive
    assert likely_instruction("Runway 33, taxi via Bravo") == "hold short Runway 33"


def test_go_around_fragment_is_not_hold_short(mem):
    m, airport, flight = mem
    hint = run(derive_hint(m, CALLSIGN, "Cessna 1-2-3 go around [squeal]", flight, airport, now=T0))
    assert hint.kind == "none"


# 6. Permissive fragment variants ---------------------------------------------------


@pytest.mark.parametrize("heard", [
    "Cessna 1-2-3 [squeal] for take off", "Cessna 1-2-3 C-LEARED [squeal]", "Cessna 1-2-3 clear of runway [squeal]",
    "Cessna 1-2-3 depart [squeal]", "Cessna 1-2-3 [squeal] cross", "Cessna 1-2-3 line  up [squeal]",
    "Cessna 1-2-3 TAKEOFF", "Cessna 1-2-3 [squeal] Take-Off",
])
def test_permissive_fragment_variants_give_no_hint(mem, heard):
    m, airport, flight = mem
    assert run(derive_hint(m, CALLSIGN, heard, flight, airport, now=T0)).kind == "none"


# 7. One writer: no silent overwrite, no other aircraft's records ------------------


def test_record_duplicate_id_is_versioned_not_overwritten(mem):
    m, airport, flight = mem
    first = run(record(m, flight, CALLSIGN, "clr-x", "Cessna 1-2-3, hold short Runway 33", "clearance", ts=T0))
    second = run(record(m, flight, CALLSIGN, "clr-x", "Cessna 1-2-3, hold position", "clearance", ts=T0 + 1))
    assert first == "clr-x" and second == "clr-x-v2"
    assert m.indexes[flight]["clr-x"].text == "Cessna 1-2-3, hold short Runway 33"


def test_record_naming_other_aircraft_is_not_used(mem):
    m, airport, flight = mem
    add_clr(m, flight, "clr-0012", "Cessna 4-5-6, Runway 28L, taxi via Alpha", T0)
    hint = run(derive_hint(m, CALLSIGN, "Cessna 1-2-3 [static]", flight, airport, now=T0))
    assert hint.source_doc_id.endswith("clr-0007") and hint.text == "hold short Runway 33"
    q = run(answer_query(m, flight, CALLSIGN, "what was my last clearance"))
    assert q.source_doc_id.endswith("clr-0007")


# 8. Offline: fail safe, open sessions at startup ------------------------------------


class BrokenMemory(LocalMemory):
    async def query(self, *a, **k):
        raise ConnectionError("moss offline")

    async def fetch(self, *a, **k):
        raise ConnectionError("moss offline")


def test_memory_errors_fail_safe(mem):
    m = BrokenMemory()
    hint = run(derive_hint(m, CALLSIGN, "Cessna 1-2-3 [static]", "flight-N123AB", "airport-KUNS"))
    assert hint.kind == "none"
    assert advisory_text(hint) == "Advisory. Transmission blocked. Awaiting controller."
    q = run(answer_query(m, "flight-N123AB", CALLSIGN, "what was my last clearance"))
    assert q.answer == NO_RECORD and q.source_doc_id is None


def test_edge_opens_memory_at_start(tmp_path):
    class OpeningMemory(LocalMemory):
        opened: tuple = ()

        async def open(self, *indexes):
            self.opened = indexes

    memory = OpeningMemory()
    edge = CockpitEdge(link=GatewayLink("ws://127.0.0.1:9", connect_timeout_s=0.2), memory=memory, tts=FakeTTS(),
                       manual_stt_factory=lambda: FakeManualSTT([""]), turn_stt_factory=lambda: FakeTurnSTT([]),
                       audio_out=AudioOut(tmp_path / "out.wav"))

    async def go():
        await edge.start(connect=False)
        await edge.stop()

    run(go())
    assert memory.opened == ("airport-KUNS", f"flight-{CALLSIGN}")
