"""Question inference and persistent airport lifecycle, with no live SDK calls."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from unstep.cockpit.edge import AudioOut, CockpitEdge
from unstep.cockpit.inference import Answer, FakeAnswerer, MossInferenceAnswerer, create_answerer
from unstep.cockpit.memory import Doc, LocalMemory, MossMemory
from unstep.cockpit.queries import NO_RECORD, answer_query, record
from unstep.cockpit.seed import COCKPIT, PREFLIGHT, airport_docs, seed
from unstep.cockpit.stt import FakeManualSTT, FakeTurnSTT
from unstep.cockpit.tts import FakeTTS
from unstep.contracts import AuditRecord
from unstep.scenario import CALLSIGN, T0, approved_directive


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def memory():
    mem = LocalMemory()
    airport, flight = run(seed(mem))
    run(record(mem, flight, CALLSIGN, "approved", "Cessna 1-2-3, hold short Runway 33",
               "clearance", ts=T0 + 100))
    return mem, airport, flight


def ask(memory, answerer, question="Unstep, what runway was I told to stop at?", **kwargs):
    mem, airport, flight = memory
    return run(answer_query(mem, flight, CALLSIGN, question, airport_index=airport,
                            answerer=answerer, **kwargs))


@pytest.mark.parametrize("question", ["last clearance", "say again", "which taxiway"])
def test_matched_intents_never_call_llm(memory, question):
    answerer = SimpleNamespace(answer=AsyncMock(side_effect=AssertionError("LLM called")))
    assert ask(memory, answerer, question).source_doc_id
    answerer.answer.assert_not_called()


def test_grounded_quote_and_citation(memory):
    answerer = SimpleNamespace(answer=AsyncMock(return_value=Answer('Recorded: "HOLD SHORT Runway 33"', 165)))
    metrics = {}
    result = ask(memory, answerer, metrics=metrics)
    assert result.answer == 'Recorded: "HOLD SHORT Runway 33"'
    assert result.source_doc_id == f"{memory[2]}/approved"
    assert metrics == {"llm_first_token_ms": 165}
    records = answerer.answer.call_args.args[1]
    assert records[0].id == result.source_doc_id
    assert len([d for d in records if d.id.startswith(memory[2])]) == 3
    assert any(d.id.startswith(memory[1]) for d in records)


@pytest.mark.parametrize("text", [
    'Recorded: "Cleared for takeoff Runway 33"',
    'Hold short Runway 33',
    'Recorded: "Runway 33"',
    'You were not told to stop; "hold short Runway 33"',
    'Recorded: "hold short Runway 33"; cleared for takeoff.',
    'Recorded: "hold short Runway 33 and cleared for takeoff"',
])
def test_hallucinated_or_unquoted_answer_rejected(memory, text):
    answerer = SimpleNamespace(answer=AsyncMock(return_value=Answer(text)))
    result = ask(memory, answerer)
    assert result.answer == NO_RECORD and result.source_doc_id is None


def test_no_record_passthrough(memory):
    answerer = SimpleNamespace(answer=AsyncMock(return_value=Answer("No record found.")))
    result = ask(memory, answerer)
    assert result.answer == "No record found." and result.source_doc_id is None


def test_error_fallback(memory):
    answerer = SimpleNamespace(answer=AsyncMock(side_effect=ConnectionError("offline")))
    assert ask(memory, answerer).answer == NO_RECORD


def test_timeout_cancels_answerer(memory):
    cancelled = []

    async def slow(*args):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)

    assert ask(memory, SimpleNamespace(answer=slow)).answer == NO_RECORD
    assert cancelled == [True]


def test_no_keys_no_llm(memory, monkeypatch):
    monkeypatch.delenv("MOSS_PROJECT_ID", raising=False)
    monkeypatch.delenv("MOSS_PROJECT_KEY", raising=False)
    constructor = AsyncMock(side_effect=AssertionError("constructed without keys"))
    monkeypatch.setattr("unstep.cockpit.inference.MossInferenceAnswerer", constructor)
    assert create_answerer() is None
    assert ask(memory, None).answer == NO_RECORD
    constructor.assert_not_called()


def test_retrieval_excludes_other_aircraft_and_hints(memory):
    mem, airport, flight = memory
    run(mem.add_docs(flight, [
        Doc("other", "N999ZZ, hold short Runway 28L", {"callsign": "N999ZZ", "type": "clearance", "ts": T0 + 500}),
        Doc("bad-label", "Cessna 4-5-6, hold short Runway 28L", {"callsign": CALLSIGN, "type": "clearance", "ts": T0 + 500}),
        Doc("hint", "Likely hold short Runway 28L", {"callsign": CALLSIGN, "type": "advisory", "ts": T0 + 500}),
    ], writer=COCKPIT))
    answerer = SimpleNamespace(answer=AsyncMock(return_value=Answer('"hold short Runway 28L"')))
    assert ask(memory, answerer).answer == NO_RECORD
    ids = {d.id for d in answerer.answer.call_args.args[1]}
    assert not ids & {f"{flight}/{i}" for i in ("other", "bad-label", "hint")}


def test_airport_quote_cites_airport(memory):
    answerer = SimpleNamespace(answer=AsyncMock(return_value=Answer('Recorded: "Taxiway Alpha closed between A3 and A4 for construction"')))
    result = ask(memory, answerer, "Is Taxiway Alpha closed for construction?")
    assert result.source_doc_id == f"{memory[1]}/notam-0012"


def test_edge_hint_readback_never_consult_llm_but_query_does():
    async def go():
        answerer = SimpleNamespace(answer=AsyncMock(wraps=FakeAnswerer().answer))
        edge = CockpitEdge(memory=LocalMemory(), tts=FakeTTS(), answerer=answerer,
                           audio_out=AudioOut(path=None),
                           turn_stt_factory=lambda: FakeTurnSTT(["Hold short runway three three, Cessna 1-2-3"]))
        await edge.start(connect=False)
        from unstep.cockpit.overlap import OverlapWindow
        await edge._on_blocked(FakeManualSTT(["Cessna 1-2-3 [static]"]),
                               [OverlapWindow(start=T0 + 1, end=T0 + 2)], T0, T0 + 3)
        await edge._on_approved(approved_directive())
        answerer.answer.assert_not_called()
        q = await edge.ask("Unstep, what runway was I told to stop at?")
        assert q.source_doc_id.endswith("clr-evt-0001")
        assert edge.latency["llm_first_token_ms"] == [0.0]
        assert any(isinstance(m, AuditRecord) and m.payload.get("llm_first_token_ms") == 0.0
                   for m in edge.outbox)
        await edge.stop()

    run(go())


def test_streaming_request_uses_only_local_context_and_times_first_token():
    seen, closed = {}, []

    async def chunks():
        try:
            yield {"choices": []}
            yield {"choices": [{"delta": {"content": 'Recorded: "'}}]}
            yield {"choices": [{"delta": {"content": 'hold short Runway 33"'}}]}
        finally:
            closed.append(True)

    async def create(**kwargs):
        seen.update(kwargs)
        return chunks()

    answerer = MossInferenceAnswerer.__new__(MossInferenceAnswerer)
    answerer.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = run(answerer.answer("Where?", [Doc("flight-X/c1", "hold short Runway 33")]))
    assert result.first_token_ms >= 0 and closed == [True]
    assert seen["indexes"] == [] and seen["stream"] is True and seen["cache"] is False
    assert seen["model"] == "moss"
    assert json.loads(seen["messages"][1]["content"])["records"][0]["id"] == "flight-X/c1"


def test_airport_loaded_not_seeded_and_cannot_be_written():
    session = SimpleNamespace(add_docs=AsyncMock(return_value=(3, 0)))
    client = SimpleNamespace(load_index=AsyncMock(), session=AsyncMock(return_value=session),
                             query=AsyncMock(return_value=SimpleNamespace(docs=[], time_taken_ms=1)))
    memory = MossMemory.__new__(MossMemory)
    memory.owners, memory.sessions, memory.client = {}, {}, client

    async def go():
        edge = CockpitEdge(memory=memory, answerer=FakeAnswerer(), tts=FakeTTS(), audio_out=AudioOut(path=None))
        await edge.start(connect=False)
        await memory.query(edge.airport_idx, "runway")
        for owner in (PREFLIGHT, COCKPIT):
            with pytest.raises(PermissionError):
                await memory.add_docs(edge.airport_idx, airport_docs(), writer=owner)
            with pytest.raises(PermissionError):
                await memory.push(edge.airport_idx, writer=owner)
        await edge.stop()

    run(go())
    client.load_index.assert_awaited_once_with("airport-KUNS")
    client.session.assert_awaited_once_with(f"flight-{CALLSIGN}")
    session.add_docs.assert_awaited_once()
    client.query.assert_awaited_once()


def test_ingestion_is_idempotent_and_updates_seed():
    from scripts.ingest_airport import ingest

    class Client:
        def __init__(self):
            self.docs, self.creates = {}, 0

        async def list_indexes(self):
            return [SimpleNamespace(name="airport-KUNS")] if self.creates else []

        async def create_index(self, index, docs):
            self.creates += 1
            self.docs.update({d.id: d for d in docs})

        async def add_docs(self, index, docs, options):
            assert options.upsert
            self.docs.update({d.id: d for d in docs})

    client = Client()
    run(ingest(client))
    client.docs["notam-0012"] = None
    run(ingest(client))
    assert client.creates == 1 and len(client.docs) == len(airport_docs())
    assert client.docs["notam-0012"].text.startswith("NOTAM:")


def test_ingestion_skips_without_keys(monkeypatch, capsys):
    from scripts.ingest_airport import main

    monkeypatch.delenv("MOSS_PROJECT_ID", raising=False)
    monkeypatch.delenv("MOSS_PROJECT_KEY", raising=False)
    assert run(main()) == 0
    assert "skipped" in capsys.readouterr().out


def test_airport_quote_is_labeled_not_a_clearance():
    import asyncio
    from unstep.cockpit.inference import Answer
    from unstep.cockpit.memory import LocalMemory, airport_index, flight_index
    from unstep.cockpit.queries import answer_query
    from unstep.cockpit.seed import seed

    class QuoteAirport:
        async def answer(self, question, records):
            doc = next(r for r in records if r.id.startswith(airport_index("KUNS")))
            return Answer(f'"{doc.text}"', 1.0)

    async def go():
        mem = LocalMemory()
        await seed(mem)
        q = await answer_query(mem, flight_index("N123AB"), "N123AB", "Unstep, anything about the hold short line?",
                               airport_index=airport_index("KUNS"), answerer=QuoteAirport())
        assert q.answer.startswith("Airport information, not a clearance:")
        assert q.source_doc_id.startswith(airport_index("KUNS"))

    asyncio.run(go())


def test_empty_question_gets_say_again_and_never_reaches_the_llm():
    import asyncio
    from unstep.cockpit.memory import LocalMemory, flight_index
    from unstep.cockpit.queries import SAY_AGAIN, answer_query

    class Boom:
        async def answer(self, question, records):
            raise AssertionError("the LLM must not be asked an empty question")

    q = asyncio.run(answer_query(LocalMemory(), flight_index("N123AB"), "N123AB", "  ", answerer=Boom()))
    assert q.answer == SAY_AGAIN and q.source_doc_id is None
