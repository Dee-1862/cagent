"""Live proof for Moss (M-1): the plane's memory, the score floor, and the flight log surviving a restart.

Needs MOSS_PROJECT_ID and MOSS_PROJECT_KEY. Run it where Moss is reachable (Rishit's laptop has keys):

    python scripts/moss_live_check.py                 # whole check, deletes the test flight log at the end
    python scripts/moss_live_check.py --keep          # keep the test flight log index in Moss Cloud
    python scripts/moss_live_check.py --dry-run       # no network: local stand-in, checks the script's own flow

What it prints, and why:
  1. the fragment search on a plane session: query, top hit, score, ms, for a garbled fragment, a worse one and an
     unrelated one. Use the scores to choose UNSTEP_MOSS_MIN_SCORE (the floor is ours: session queries don't document min_score).
  2. "last minute" and "whole exchange" answers with their search ms.
  3. whether Moss's own sort_by and group_by on a session behave the way our code assumes (we never trust them;
     this tells us whether they could be used). Differences are printed, not failures.
  4. the flight log: two flights archived, ONE push, then a brand new client (a restart) and how many flights
     came back and how fast. The index is named flightlog-check-<time>, never the real one, and per-aircraft
     sessions are never pushed.
  5. the plane's memory on disk (MM1): save a session with `save_to_disk`, drop it, build a new session object
     and `load_from_disk` it with no index download, then ask "what was my last clearance?". Prints the doc count
     and the load ms. This proves "on board, from disk, no cloud index"; it does not prove the process can start
     with the Moss service unreachable (opening a session object still contacts Moss to check credentials).

Exit code 1 if a check that our code relies on fails. A dry run proves the flow only, not Moss.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep.clock import now_ms  # noqa: E402
from unstep.cockpit.hint import derive_hint  # noqa: E402
from unstep.cockpit.memory import Doc, LocalMemory, create_memory  # noqa: E402
from unstep.cockpit.queries import answer_query, record  # noqa: E402
from unstep.cockpit.seed import COCKPIT, seed  # noqa: E402
from unstep.live.flightlog import FlightLog  # noqa: E402
from unstep.scenario import CALLSIGN, T0  # noqa: E402

FRAGMENTS = ["Cessna 123, short runway 30", "Cessna hold runway", "static and the weather in Paris"]


async def plane_checks(mem, report) -> int:
    failures = 0
    airport, flight = await seed(mem, CALLSIGN, t0=T0)
    now = now_ms()
    exchange = "evt-check-1"
    await mem.add_docs(flight, [
        Doc("heard-1", "Cessna 1-2-3 [static]", {"callsign": CALLSIGN, "type": "heard", "speaker": "atc", "ts": now - 4000, "exchange": exchange, "stepped_on": "true"}),
        Doc("clr-evt", "Cessna 1-2-3, hold short runway 33", {"callsign": CALLSIGN, "type": "clearance", "ts": now - 3000, "exchange": exchange}),
        Doc("readback-1", "Hold short runway 33, Cessna 1-2-3", {"callsign": CALLSIGN, "type": "readback", "speaker": CALLSIGN, "ts": now - 2000, "exchange": exchange}),
    ], COCKPIT)
    report("1. fragment search on the plane's session (hybrid, alpha 0.5):")
    for frag in FRAGMENTS:
        ev: dict = {}
        hint = await derive_hint(mem, CALLSIGN, frag, flight, airport, now=T0, evidence=ev)
        top = ev.get("top_hit_text") or "(no hit shown)"
        report(f"   {frag!r}: score {ev.get('score', ev.get('best_score'))} floor {ev.get('floor')} "
               f"{'BELOW FLOOR' if ev.get('below_floor') else 'clears'} search {ev.get('search_ms')} ms hint {hint.kind} top: {top}")
    for question in ("What did the tower tell me in the last minute?", "What was the whole exchange?"):
        q = await answer_query(mem, flight, CALLSIGN, question)
        report(f"2. {question} -> {q.moss_ms} ms: {q.answer[:140]}")
        failures += q.answer.startswith("Advisory. No record") or q.answer.startswith("Advisory. Nothing")
    report("3. native sort_by and group_by on the session (diagnostic only):")
    if getattr(mem, "backend", "") == "moss":
        try:
            from moss import GetDocumentsOptions, ParentGrouping

            session = await mem._session(flight)
            raw = await session.get_docs(GetDocumentsOptions(sort_by="ts", ascending=False))
            ts = [float(d.metadata.get("ts", 0)) for d in raw if d.metadata.get("ts")]
            report(f"   sort_by ts descending is numeric: {ts == sorted(ts, reverse=True)} ({len(ts)} docs)")
            grouped = await session.get_docs(GetDocumentsOptions(group_by=ParentGrouping("exchange", "ts")))
            report(f"   group_by exchange returned {len(grouped)} unit(s); first text: {(grouped[0].text if grouped else '')[:100]!r}")
        except Exception as exc:  # unverified features: report, don't fail
            report(f"   not usable here: {type(exc).__name__}: {exc}")
    else:
        report("   skipped: the local stand-in has no native sort or grouping")
    return failures


async def flight_log_checks(factory, report, keep: bool) -> int:
    mem = factory()
    frequency = f"check-{int(time.time())}"
    log = FlightLog(mem, frequency)
    for callsign, text in (("N123AB", "Cessna 1-2-3, hold short runway 33"), ("H456", "Helicopter 4-5-6, hold short runway 15")):
        index = f"flight-{callsign}-check"
        mem.register_index(index, COCKPIT)
        await mem.add_docs(index, [Doc("clr-1", text, {"callsign": callsign, "type": "clearance", "ts": now_ms()})], COCKPIT)
        await log.archive(callsign, mem, index, "live check")
    pushed = await log.push()
    report(f"4. flight log {log.index}: {len(log.flights)} flights archived, pushed once: {pushed}")
    failures = 0 if pushed and pushed.get("ok") else 1
    mem2 = factory()  # a restart: a new client (a dry run hands back the same memory, so it proves nothing there)
    log2 = FlightLog(mem2, frequency)
    started = time.perf_counter()
    found = await log2.search("hold short", top_k=10)
    ms = round((time.perf_counter() - started) * 1000)
    restored = {d["callsign"] for d in found["docs"]}
    report(f"   after a fresh client: {len(found['docs'])} docs back in {ms} ms, callsigns {sorted(c for c in restored if c)}")
    failures += not {"N123AB", "H456"} <= restored
    if getattr(mem2, "backend", "") == "moss" and not keep:
        try:
            await mem2.client.delete_index(log.index)
            report(f"   deleted the test index {log.index}")
        except Exception as exc:
            report(f"   could not delete {log.index} ({type(exc).__name__}); delete it in the Moss portal")
    return failures


async def disk_checks(make_memory, report) -> int:
    """MM1: a plane's flight session saved to disk, then restored into a brand new session object."""
    from unstep.cockpit.memory import flight_index

    flight = flight_index(CALLSIGN)
    with tempfile.TemporaryDirectory(prefix="unstep-moss-disk-") as folder:
        first = make_memory(folder)
        await first.open(flight)
        _, flight = await seed(first, CALLSIGN, t0=T0)
        await record(first, flight, CALLSIGN, "clr-disk-check", "Cessna 1-2-3, hold short runway 33", "clearance",
                     ts=now_ms())
        await first.flush_saves()
        report(f"5. on-board memory: saved {first.saves} snapshot(s) of the plane session under {folder}")
        failures = 0 if first.saves else 1
        del first  # the "kill"
        second = make_memory(folder)  # a restart: a new session object, restored from disk
        await second.open(flight)
        count = await second.load_snapshot(flight)
        if count is None:
            report("   nothing came back from disk")
            return failures + 1
        await seed(second, CALLSIGN, t0=T0, skip_existing=True)
        ids = [d.id for d in (await second.fetch(flight)).docs]
        q = await answer_query(second, flight, CALLSIGN, "What was my last clearance?")
        report(f"   after a restart from disk: {count} docs loaded in {second.last_load_ms} ms, "
               f"{len(ids)} after seeding (duplicates: {len(ids) - len(set(ids))})")
        report(f"   what was my last clearance? -> {q.answer[:140]}")
        failures += (len(ids) != len(set(ids))) + ("hold short runway 33" not in q.answer.lower())
        # Where does the restore time go, and is the first one slower (model start-up)? Restore twice more into
        # fresh session objects of the same client: the cold and the warm numbers are different claims.
        runs = [(count, second.last_load_ms, dict(second.load_breakdown))]
        for _ in range(2):
            second.drop(flight, keep_snapshot=True)
            started = time.perf_counter()
            n = await second.load_snapshot(flight)
            runs.append((n, round((time.perf_counter() - started) * 1000, 1), dict(second.load_breakdown)))
        for i, (n, ms, parts) in enumerate(runs, 1):
            report(f"   restore {i}{' (cold)' if i == 1 else ''}: {n} docs in {ms} ms  {parts}")
        warm = sorted(ms for _, ms, _ in runs[1:])
        report(f"   cold {runs[0][1]} ms, warm {warm[0]} to {warm[-1]} ms. "
               "load_from_disk is the Moss SDK's own time; open_ms is a session the plane already holds.")
        return failures


async def main_async(dry_run: bool, keep: bool, out=print) -> int:
    if dry_run:
        shared = LocalMemory()
        factory = lambda: shared  # noqa: E731
        out("DRY RUN: local stand-in, nothing here proves Moss.")
        mem = shared
    else:
        mem = create_memory()
        if getattr(mem, "backend", "") != "moss":
            out("skipped: set MOSS_PROJECT_ID and MOSS_PROJECT_KEY (and install `moss`).")
            return 0
        clients = iter([mem])

        def factory():  # the first call reuses this client; the restart check builds a brand new one
            return next(clients, None) or create_memory()

    failures = await plane_checks(mem, out)
    failures += await flight_log_checks(factory, out, keep)
    if dry_run:
        failures += await disk_checks(lambda folder: LocalMemory(disk_dir=folder), out)
    else:
        from unstep.cockpit.memory import MossMemory

        pid, key = os.environ["MOSS_PROJECT_ID"], os.environ["MOSS_PROJECT_KEY"]
        failures += await disk_checks(lambda folder: MossMemory(pid, key, disk_dir=folder), out)
    out("ok" if not failures else f"{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main_async(args.dry_run, args.keep)))
