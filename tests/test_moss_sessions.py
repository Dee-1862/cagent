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
