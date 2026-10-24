"""P4: every plane gets a Moss session by default; the hub's frequency session has one writer."""

import asyncio

from unstep import config
from unstep.cockpit.memory import LocalMemory
from unstep.cockpit.monitor import WRITER, freq_index

from tests.test_live_room import make_room, only_trace, stepped_on, wait_for  # noqa: F401 (fixture)


def test_moss_for_the_whole_fleet_by_default(monkeypatch):
    monkeypatch.delenv("UNSTEP_MOSS_AIRCRAFT", raising=False)
    assert config.moss_aircraft() == 6
    monkeypatch.setenv("UNSTEP_MOSS_AIRCRAFT", "2")
    assert config.moss_aircraft() == 2
    monkeypatch.setenv("UNSTEP_MOSS_AIRCRAFT", "lots")
    assert config.moss_aircraft() == 6


class FailingMoss(LocalMemory):
    backend = "moss"

    async def add_docs(self, index, docs, writer):
        raise ConnectionError("moss unreachable")


def test_frequency_session_is_written_only_by_the_monitor_and_survives_a_moss_failure(make_room):
    async def go():
        room, atc, pilot = await make_room()
        assert room.monitor.memory.backend == "local"  # offline rooms never use Moss
        room.monitor.memory = FailingMoss()
        await stepped_on(room)
        await wait_for(lambda: only_trace(room) is not None)
        mem = room.monitor.memory
        index = freq_index(room.frequency)
        await wait_for(lambda: isinstance(mem, LocalMemory) and mem.indexes.get(index)
                       if (mem := room.monitor.memory) else False)
        assert room.monitor.memory.backend == "local" and room.monitor.memory.owners[index] == WRITER
        doc = next(iter(room.monitor.memory.indexes[index].values()))
        assert "hold short" in doc.text.lower() and doc.metadata["frequency"] == room.frequency
        try:
            await room.monitor.memory.add_docs(index, [], writer="cockpit")
        except PermissionError:
            pass
        else:
            raise AssertionError("a second writer must be refused")
        await room.stop()

    asyncio.run(go())


# ---------------------------------------------------------------- P4 part 2: in-session indexing

from unstep.clock import now_ms  # noqa: E402
from unstep.cockpit.memory import Doc  # noqa: E402
from unstep.cockpit.queries import NOTHING_RECENT, answer_query, classify_intent  # noqa: E402
from unstep.cockpit.seed import COCKPIT  # noqa: E402

FLIGHT = "flight-N123AB"


def heard(mem, doc_id, text, ts, speaker="atc", stepped=False, callsign="N123AB"):
    return mem.add_docs(FLIGHT, [Doc(doc_id, text, {"callsign": callsign, "type": "heard", "speaker": speaker,
                                                    "ts": ts, "stepped_on": "true" if stepped else "false"})],
                        writer=COCKPIT)


def test_recent_answer_cites_the_newest_heard_docs_in_the_window():
    async def go():
        mem = LocalMemory()
        mem.register_index(FLIGHT, COCKPIT)
        now = now_ms()
        await heard(mem, "h-old", "Cessna 1-2-3, taxi via Alpha", now - 120_000)
        await heard(mem, "h-1", "Cessna 1-2-3, hold short [static]", now - 20_000, stepped=True)
        await heard(mem, "h-2", "Cessna 1-2-3, hold short runway 33", now - 5_000)
        await heard(mem, "h-pilot", "Helicopter 4-5-6 request transition", now - 4_000, speaker="H456")
        await heard(mem, "h-other", "Piper 7-8-9, line up and wait", now - 3_000)
        q = await answer_query(mem, FLIGHT, "N123AB", "What did the tower tell me in the last minute?")
        assert q.source_doc_id == f"{FLIGHT}/h-2" and q.moss_ms is not None
        assert "hold short runway 33" in q.answer and "[static]" in q.answer and "stepped on" in q.answer
        assert "taxi via Alpha" not in q.answer  # outside the minute
        assert "Piper" not in q.answer and "Helicopter" not in q.answer  # other aircraft, not tower
        assert q.answer.index("[static]") < q.answer.index("runway 33")  # oldest first
        empty = await answer_query(mem, FLIGHT, "N123AB", "what did the tower say in the last 1 seconds")
        assert empty.answer == NOTHING_RECENT and empty.source_doc_id is None

    asyncio.run(go())
    assert classify_intent("repeat the last clearance") == "last_clearance"


def test_stepped_on_call_is_indexed_as_heard_and_answers_the_pilot(make_room):
    async def go():
        room, atc, pilot = await make_room()
        await stepped_on(room)
        await wait_for(lambda: only_trace(room) is not None)
        edge = room.edges["N123AB"]
        mem = edge.memory

        def heard_docs():
            return [d for d in mem.indexes.get(edge.flight_idx, {}).values() if d.metadata.get("type") == "heard"]

        await wait_for(lambda: heard_docs())
        doc = heard_docs()[0]
        assert doc.metadata["stepped_on"] == "true" and doc.metadata["speaker"] == "atc"
        assert "atc" in doc.metadata["speakers"] and "H456" in doc.metadata["speakers"]
        assert mem.owners[edge.flight_idx] == COCKPIT
        q = await edge.ask("What did the tower tell me in the last minute?")
        assert q.source_doc_id == f"{edge.flight_idx}/{doc.id}" and q.moss_ms is not None
        await room.stop()

    asyncio.run(go())
