"""Moss layer on the local fallback: memory, filters, one-writer rule, local hint, pilot queries."""

import asyncio

import pytest

from unstep.cockpit.hint import advisory_text, classify, derive_hint
from unstep.cockpit.memory import Doc, LocalMemory, create_memory, matches
from unstep.cockpit.queries import NO_RECORD, answer_query, classify_intent, record
from unstep.cockpit.seed import COCKPIT, PREFLIGHT, seed
from unstep.scenario import CALLSIGN, T0


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def mem():
    m = LocalMemory()
    airport, flight = run(seed(m))
    return m, airport, flight


def test_factory_falls_back_without_keys(monkeypatch):
    monkeypatch.delenv("MOSS_PROJECT_ID", raising=False)
    monkeypatch.delenv("MOSS_PROJECT_KEY", raising=False)
    assert create_memory().backend == "local"


def test_filters():
    md = {"callsign": "N123AB", "type": "clearance", "ts": 100}
    assert matches(md, {"callsign": {"$eq": "N123AB"}})
    assert not matches(md, {"callsign": {"$eq": "N999ZZ"}})
    assert matches(md, {"type": {"$in": ["clearance", "advisory"]}})
    assert matches(md, {"$and": [{"ts": {"$gte": 50}}, {"ts": {"$lte": 100}}]})
    assert not matches(md, {"ts": {"$gte": 101}})
    assert matches(md, {"$or": [{"type": "advisory"}, {"ts": {"$lt": 200}}]})


def test_query_filters_and_timing(mem):
    m, airport, flight = mem
    res = run(m.query(flight, "runway 33 taxi", filter={"type": {"$eq": "clearance"}}))
    assert res.docs[0].id == "clr-0007"
    assert res.time_taken_ms >= 0 and res.backend == "local"
    res = run(m.query(airport, "taxiway", filter={"type": {"$eq": "notam"}}))
    assert [d.id for d in res.docs] == ["notam-0012"]


def test_one_writer_per_index(mem):
    m, airport, flight = mem
    with pytest.raises(PermissionError):
        run(m.add_docs(flight, [Doc(id="x", text="hijack")], writer="ground"))
    with pytest.raises(PermissionError):
        run(m.add_docs(airport, [Doc(id="x", text="x")], writer=COCKPIT))
    with pytest.raises(PermissionError):
        m.register_index(flight, "ground")
    m.register_index(airport, PREFLIGHT)  # same owner again is fine


def test_demo_hint_is_restrictive_with_source(mem):
    m, airport, flight = mem
    # `now` pinned to the seed clock: hints only come from a recent clearance.
    hint = run(derive_hint(m, CALLSIGN, "Cessna 1-2-3 [static]", flight, airport, now=T0))
    assert hint.kind == "restrictive"
    assert hint.text == "hold short Runway 33"
    assert hint.source_doc_id == f"{flight}/clr-0007"
    assert "taxi via Bravo" in hint.source_text
    assert hint.moss_ms is not None
    assert advisory_text(hint) == "Advisory. Transmission blocked. Likely hold short Runway 33. Awaiting controller."


def test_permissive_fragment_gives_no_hint(mem):
    m, airport, flight = mem
    hint = run(derive_hint(m, CALLSIGN, "Cessna 1-2-3 cleared [static]", flight, airport))
    assert hint.kind == "none" and hint.text is None
    assert advisory_text(hint) == "Advisory. Transmission blocked. Awaiting controller."


def test_permissive_source_gives_no_hint():
    m = LocalMemory()
    m.register_index("flight-N1", COCKPIT)
    m.register_index("airport-KUNS", PREFLIGHT)
    run(m.add_docs("airport-KUNS", [Doc(id="r", text="Runway 33/15", metadata={"type": "runway"})], writer=PREFLIGHT))
    run(m.add_docs("flight-N1", [Doc(id="c1", text="N1, Runway 33, cleared for takeoff",
                                     metadata={"callsign": "N1", "type": "clearance", "ts": 1})], writer=COCKPIT))
    hint = run(derive_hint(m, "N1", "N1 [static]", "flight-N1", "airport-KUNS"))
    assert hint.kind == "none"


def test_no_source_gives_no_hint():
    m = LocalMemory()
    m.register_index("flight-N1", COCKPIT)
    m.register_index("airport-KUNS", PREFLIGHT)
    hint = run(derive_hint(m, "N1", "N1 [static]", "flight-N1", "airport-KUNS"))
    assert hint.kind == "none" and hint.source_doc_id is None


def test_unknown_runway_gives_no_hint():
    m = LocalMemory()
    m.register_index("flight-N1", COCKPIT)
    m.register_index("airport-KUNS", PREFLIGHT)
    run(m.add_docs("airport-KUNS", [Doc(id="r", text="Runway 28L/10R", metadata={"type": "runway"})], writer=PREFLIGHT))
    run(m.add_docs("flight-N1", [Doc(id="c1", text="N1, Runway 33, taxi via Bravo",
                                     metadata={"callsign": "N1", "type": "clearance", "ts": 1})], writer=COCKPIT))
    assert run(derive_hint(m, "N1", "N1 [static]", "flight-N1", "airport-KUNS")).kind == "none"


def test_stale_clearances_filtered_out(mem):
    m, airport, flight = mem
    hint = run(derive_hint(m, CALLSIGN, "Cessna 1-2-3 [static]", flight, airport, since_ts=T0))
    assert hint.kind == "none"


def test_classify():
    assert classify("hold short Runway 33") == "restrictive"
    assert classify("go around") == "restrictive"
    assert classify("Runway 33, cleared for takeoff") == "permissive"
    assert classify("cross Runway 28L, hold short of 33") == "permissive"
    assert classify("line up and wait") == "permissive"
    assert classify("contact departure") == "unknown"


def test_intents():
    assert classify_intent("Unstep, what was my last clearance?") == "last_clearance"
    assert classify_intent("Unstep, say again") == "say_again"
    assert classify_intent("Unstep, which taxiway?") == "taxi_route"
    assert classify_intent("Unstep, what's the weather?") == "unknown"


def test_queries_answer_with_sources(mem):
    m, airport, flight = mem
    q = run(answer_query(m, flight, CALLSIGN, "Unstep, what was my last clearance?"))
    assert "Runway 33, taxi via Bravo" in q.answer and q.source_doc_id == f"{flight}/clr-0007"
    assert q.moss_ms is not None

    q = run(answer_query(m, flight, CALLSIGN, "Unstep, which taxiway?"))
    assert q.answer == "Advisory. Taxi via Bravo to Runway 33." and q.source_doc_id.endswith("clr-0007")

    # Approved directive becomes the latest clearance.
    run(record(m, flight, CALLSIGN, "dir-evt-0001", "Cessna 1-2-3, hold short Runway 33", "clearance", ts=T0 + 9100))
    q = run(answer_query(m, flight, CALLSIGN, "what was my last clearance"))
    assert "hold short Runway 33" in q.answer and q.source_doc_id.endswith("dir-evt-0001")


def test_say_again_and_unknown(mem):
    m, airport, flight = mem
    # No advisory yet: say again repeats the last approved clearance (blue-team fix 4).
    assert run(answer_query(m, flight, CALLSIGN, "say again")).answer.startswith("Advisory. Last clearance:")
    run(record(m, flight, CALLSIGN, "adv-1", "Advisory. Transmission blocked. Likely hold short Runway 33. Awaiting controller.", "advisory", ts=T0 + 2700))
    q = run(answer_query(m, flight, CALLSIGN, "Unstep, say again"))
    assert q.answer.startswith("Advisory. Transmission blocked") and q.source_doc_id.endswith("adv-1")
    q = run(answer_query(m, flight, CALLSIGN, "Unstep, what's the weather?"))
    assert q.answer == NO_RECORD and q.source_doc_id is None
