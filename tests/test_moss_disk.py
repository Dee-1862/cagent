"""MM1: a plane's memory is saved to disk in the background and restored at start, with fakes (no cloud)."""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from unstep.cockpit.memory import Doc, LocalMemory, MossMemory, flight_index
from unstep.cockpit.queries import record
from unstep.cockpit.seed import COCKPIT, seed
from unstep.scenario import CALLSIGN, T0

FLIGHT = flight_index(CALLSIGN)


def clearance(i="c1", text="Cessna 1-2-3, hold short runway 33"):
    return Doc(i, text, {"callsign": CALLSIGN, "type": "clearance", "ts": 1})


def make(tmp_path, interval=0.05):
    mem = LocalMemory(disk_dir=tmp_path)
    mem.save_interval_s = interval
    mem.register_index(FLIGHT, COCKPIT)
    return mem


def test_debounce_many_adds_make_few_saves_and_the_last_one_is_on_disk(tmp_path):
    async def go():
        mem = make(tmp_path, interval=0.2)
        for i in range(20):
            await mem.add_docs(FLIGHT, [clearance(f"c{i}")], COCKPIT)
        await asyncio.sleep(0.6)
        assert mem.saves <= 3, mem.saves  # first at once, then at most one per interval
        await mem.add_docs(FLIGHT, [clearance("last")], COCKPIT)
        await asyncio.sleep(0.5)
        fresh = LocalMemory(disk_dir=tmp_path)
        assert await fresh.load_snapshot(FLIGHT) == 21

    asyncio.run(go())


def test_default_interval_is_one_second():
    assert LocalMemory.save_interval_s == 1.0 and MossMemory.save_interval_s == 1.0


def test_only_clearances_readbacks_and_advisories_trigger_a_save(tmp_path):
    async def go():
        mem = make(tmp_path)
        await mem.add_docs(FLIGHT, [Doc("h1", "static", {"type": "heard"})], COCKPIT)
        await asyncio.sleep(0.15)
        assert mem.saves == 0
        await mem.add_docs(FLIGHT, [Doc("r1", "hold short", {"type": "readback"})], COCKPIT)
        await asyncio.sleep(0.15)
        assert mem.saves == 1

    asyncio.run(go())


def test_save_is_in_the_background_not_on_the_add(tmp_path):
    async def go():
        mem = make(tmp_path, interval=0.3)
        await mem.add_docs(FLIGHT, [clearance()], COCKPIT)
        assert mem.saves == 0  # add_docs returned before any save finished
        await mem.flush_saves()
        assert mem.saves == 1

    asyncio.run(go())


def test_a_failed_save_does_not_raise_and_later_saves_still_work(tmp_path):
    async def go():
        mem = make(tmp_path)
        real = mem._write_snapshot
        calls = []

        async def broken(index):
            calls.append(index)
            raise OSError("disk full")

        mem._write_snapshot = broken
        assert await mem.add_docs(FLIGHT, [clearance()], COCKPIT) == 1  # the radio path is untouched
        await mem.flush_saves()
        assert calls and mem.saves == 0
        mem._write_snapshot = real
        await mem.add_docs(FLIGHT, [clearance("c2")], COCKPIT)
        await mem.flush_saves()
        assert mem.saves == 1

    asyncio.run(go())


def test_a_missing_or_damaged_file_is_fine(tmp_path):
    async def go():
        mem = make(tmp_path)
        assert await mem.load_snapshot(FLIGHT) is None  # nothing saved yet
        (tmp_path / f"{FLIGHT}.json").write_text("{not json", encoding="utf-8")
        assert await mem.load_snapshot(FLIGHT) is None  # damaged: logged, starts fresh
        _, flight = await seed(mem, CALLSIGN, t0=T0)
        assert len((await mem.fetch(flight)).docs) == 3

    asyncio.run(go())


def test_load_before_seed_keeps_the_saved_docs_and_adds_no_duplicates(tmp_path):
    async def go():
        first = make(tmp_path)
        _, flight = await seed(first, CALLSIGN, t0=T0)
        await record(first, flight, CALLSIGN, "clr-new", "Cessna 1-2-3, hold short runway 33", "clearance", ts=T0)
        await first.flush_saves()

        second = LocalMemory(disk_dir=tmp_path)
        restored = await second.load_snapshot(flight)
        assert restored == 4 and second.last_load_ms is not None
        await seed(second, CALLSIGN, t0=T0 + 999_000, skip_existing=bool(restored))
        docs = (await second.fetch(flight)).docs
        assert sorted(d.id for d in docs) == sorted(["clr-0005", "clr-0006", "clr-0007", "clr-new"])
        seeded_ts = {d.id: d.metadata["ts"] for d in docs}
        assert seeded_ts["clr-0007"] == T0 - 3 * 60_000  # the restored copy was kept, not re-seeded

    asyncio.run(go())


def test_the_edge_restores_on_start_and_saves_on_stop(tmp_path):
    from tests.test_edge import make_edge

    async def go():
        edge, _ = make_edge("ws://127.0.0.1:1", tmp_path)
        edge.memory = LocalMemory(disk_dir=tmp_path / "moss")
        await edge.start(connect=False)
        assert edge.restored_docs is None  # first start: nothing on board yet
        await record(edge.memory, edge.flight_idx, edge.callsign, "clr-x", "Cessna 1-2-3, hold short runway 33",
                     "clearance")
        await edge.stop()  # flushes the last save

        again, _ = make_edge("ws://127.0.0.1:1", tmp_path)
        again.memory = LocalMemory(disk_dir=tmp_path / "moss")
        await again.start(connect=False)
        assert again.restored_docs == 4 and again.load_ms is not None
        ids = [d.id for d in (await again.memory.fetch(again.flight_idx)).docs]
        assert len(ids) == len(set(ids)) == 4 and "clr-x" in ids

    asyncio.run(go())


# ---- MossMemory with a fake SDK: the calls are the ones the installed SDK documents -------------


class FakeSession:
    def __init__(self, name):
        self.name, self.docs, self.saved_to, self.loaded_from, self.fail = name, {}, [], [], False

    async def add_docs(self, infos):
        for d in infos:
            self.docs[d.id] = d
        return len(infos), 0

    async def save_to_disk(self, cache_path=None):
        if self.fail:
            raise RuntimeError("boom")
        self.saved_to.append(cache_path)

    async def load_from_disk(self, cache_path=None, *, rebuild_legacy=True):
        self.loaded_from.append(cache_path)
        return 7


class FakeClient:
    sessions: list = []

    def __init__(self, *a, **k):
        pass

    async def session(self, name, model_id=None, *, auto_load_on_init=True):
        s = FakeSession(name)
        s.auto_load_on_init = auto_load_on_init
        FakeClient.sessions.append(s)
        return s


@pytest.fixture
def fake_moss(monkeypatch):
    import moss

    FakeClient.sessions = []
    monkeypatch.setattr(moss, "MossClient", FakeClient)


def test_moss_saves_with_the_sdk_call_and_loads_without_a_cloud_download(fake_moss, tmp_path):
    async def go():
        mem = MossMemory("p", "k", disk_dir=tmp_path)
        mem.save_interval_s = 0.05
        mem.register_index(FLIGHT, COCKPIT)
        assert await mem.load_snapshot(FLIGHT) is None  # no snapshot yet: no load, no session opened
        await mem.add_docs(FLIGHT, [clearance()], COCKPIT)
        await mem.flush_saves()
        assert FakeClient.sessions[0].saved_to == [str(tmp_path)] and mem.saves == 1

        (tmp_path / FLIGHT).mkdir()  # what save_to_disk leaves behind: <cache_path>/<session name>/
        again = MossMemory("p", "k", disk_dir=tmp_path)
        assert await again.load_snapshot(FLIGHT) == 7
        restored = FakeClient.sessions[-1]
        assert restored.auto_load_on_init is False and restored.loaded_from == [str(tmp_path)]

        FakeClient.sessions[0].fail = True
        await mem.add_docs(FLIGHT, [clearance("c2")], COCKPIT)
        await mem.flush_saves()  # a failing SDK save only logs
        assert mem.saves == 1

    asyncio.run(go())


def test_moss_disk_can_be_turned_off(fake_moss, monkeypatch):
    monkeypatch.setenv("UNSTEP_MOSS_DISK", "off")
    assert MossMemory("p", "k").disk_dir is None


def test_the_live_check_dry_run_restarts_from_disk():
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("moss_live_check_disk", root / "scripts" / "moss_live_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["moss_live_check_disk"] = mod
    spec.loader.exec_module(mod)
    lines = []
    assert asyncio.run(mod.main_async(True, False, out=lines.append)) == 0
    text = "\n".join(lines)
    assert "after a restart from disk: 4 docs loaded" in text and "duplicates: 0" in text
    assert "hold short runway 33" in text.split("what was my last clearance?")[1].lower()


def test_a_freed_seat_deletes_the_on_board_copy_but_a_hub_stop_keeps_it(tmp_path):
    import asyncio

    from unstep.cockpit.memory import Doc, LocalMemory
    from unstep.live.flightlog import FlightLog

    async def go(reason):
        mem = LocalMemory(disk_dir=str(tmp_path / reason.replace(" ", "")))
        mem.save_interval_s = 0
        log = FlightLog(mem, "118.700")
        mem.register_index("flight-A", "cockpit")
        await mem.add_docs("flight-A", [Doc("x", "hold short 33", {"type": "clearance"})], "cockpit")
        await mem.flush_saves()
        assert mem.has_snapshot("flight-A")
        await log.archive("A", mem, "flight-A", reason)
        return mem.has_snapshot("flight-A")

    assert asyncio.run(go("hub stopped")) is True  # the plane is still flying: it restarts with its memory
    assert asyncio.run(go("phone gone for 20 s")) is False  # the next pilot starts clean


def test_a_save_cancelled_by_stop_cannot_overwrite_the_final_one(tmp_path):
    """A slow earlier write whose thread finishes after the final one must not win (seen as 3 docs instead of 4 on
    Windows). The earlier write runs in a thread, which a cancelled await does not stop."""
    import asyncio
    import json
    import os
    import time

    from unstep.cockpit.memory import Doc, LocalMemory

    async def go():
        mem = LocalMemory(disk_dir=str(tmp_path))
        mem.save_interval_s = 0
        mem.register_index("flight-X", "cockpit")
        calls = {"n": 0}

        async def threaded_write(index):
            calls["n"] += 1
            slow = calls["n"] == 1
            docs = [{"id": d.id, "text": d.text, "metadata": d.metadata} for d in mem.indexes[index].values()]
            path = mem._snapshot_path(index)

            def write():
                if slow:
                    time.sleep(0.3)  # finishes after the final write has been issued
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(f".{calls['n']}.tmp")
                tmp.write_text(json.dumps({"index": index, "docs": docs}), encoding="utf-8")
                os.replace(tmp, path)

            await asyncio.to_thread(write)

        mem._write_snapshot = threaded_write
        await mem.add_docs("flight-X", [Doc("a", "one", {"type": "clearance"})], "cockpit")
        await asyncio.sleep(0.05)  # the first (slow) write is under way in its thread
        await mem.add_docs("flight-X", [Doc("b", "two", {"type": "clearance"})], "cockpit")
        await mem.flush_saves()
        await asyncio.sleep(0.4)  # let any stray thread finish, as a late one would on a slow disk
        return await LocalMemory(disk_dir=str(tmp_path)).load_snapshot("flight-X")

    assert asyncio.run(go()) == 2


def test_only_a_plane_session_is_kept_on_board_never_the_shared_flight_log(tmp_path):
    """A local copy of the flight log would make its session open without downloading the cloud index, so after a
    restart it came up empty and the next push replaced the cloud flight log with only the new flights."""
    import asyncio

    from unstep.cockpit.memory import Doc, LocalMemory

    async def go():
        mem = LocalMemory(disk_dir=str(tmp_path))
        mem.save_interval_s = 0
        for index in ("flight-N123AB", "flightlog-118.700", "freq-118.700"):
            mem.register_index(index, "cockpit")
            await mem.add_docs(index, [Doc("c1", "hold short", {"type": "clearance"})], "cockpit")
        await mem.flush_saves()
        return mem.has_snapshot("flight-N123AB"), mem.has_snapshot("flightlog-118.700"), mem.has_snapshot("freq-118.700")

    assert asyncio.run(go()) == (True, False, False)
