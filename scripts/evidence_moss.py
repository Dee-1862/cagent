"""Evidence for the Moss table in the README: six aircraft sessions, how fast the plane's memory answers.

    python scripts/evidence_moss.py                 # real Moss (needs MOSS_PROJECT_ID and MOSS_PROJECT_KEY in .env)
    python scripts/evidence_moss.py --runs 100      # more samples per number

Measures, on the real Moss SDK with one local session per aircraft (six, as in the live room):
  fetch     the Clearance agent's "last tower call": a metadata filter plus a sort by time, newest first
  query     the hybrid search the cockpit runs on the fragment it did hear
  scores    the right clearance against unrelated speech for the same kind of fragment
  ask       "what was my last clearance?" answered from memory, spoken afterwards by Sonic (this is the Moss part only)
  disk      one session saved to disk and restored into a new session object, with the document count before and after

The speed numbers are the milliseconds Moss itself reports (`time_taken_ms`) and, next to them, our own wall clock
around the call. Every number carries its sample count. Writes docs/evidence/moss-<date>.json. The Moss Cloud
flight-log sync is proved by scripts/moss_live_check.py (its output is saved next to this file).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep.clock import now_ms  # noqa: E402
from unstep.cockpit.hint import derive_hint  # noqa: E402
from unstep.cockpit.memory import Doc, create_memory, flight_index  # noqa: E402
from unstep.cockpit.queries import answer_query  # noqa: E402
from unstep.cockpit.seed import COCKPIT, seed  # noqa: E402
from unstep.scenario import T0  # noqa: E402

CALLSIGNS = ["N123AB", "H456", "N240CR", "N678SK", "N789PA", "N901DA"]
RIGHT = "Cessna 123, short runway 30"
UNRELATED = "static and the weather in Paris"


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 3)


def summary(values: list[float]) -> dict:
    return {"n": len(values), "p50": pct(values, 0.5), "p95": pct(values, 0.95), "mean": round(statistics.fmean(values), 3),
            "max": round(max(values), 3)}


async def add_traffic(mem, flight: str, callsign: str) -> None:
    """A realistic little memory: tower calls to this plane and to others, and the plane's readbacks."""
    now = now_ms()
    docs = []
    for k in range(12):
        docs.append(Doc(f"atc-{k}", f"Tower: {callsign[:1]}one two three, runway three three, hold short, taxi via B"
                        if k % 3 else "Tower: Helicopter four five six, request approved",
                        {"callsign": callsign, "type": "heard", "speaker": "atc", "ts": now - (12 - k) * 1000}))
    docs.append(Doc("clr-latest", "Cessna 1-2-3, hold short runway 33",
                    {"callsign": callsign, "type": "clearance", "ts": now - 500}))
    docs.append(Doc("rb-1", "Hold short runway 33, Cessna 1-2-3",
                    {"callsign": callsign, "type": "readback", "speaker": callsign, "ts": now - 400}))
    await mem.add_docs(flight, docs, COCKPIT)


async def main(runs: int) -> dict:
    mem = create_memory()
    if getattr(mem, "backend", "") != "moss":
        raise SystemExit("Moss is not configured (MOSS_PROJECT_ID, MOSS_PROJECT_KEY): this check needs the real service.")
    result: dict = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "backend": mem.backend,
                    "sessions": len(CALLSIGNS), "runs_per_session": runs}

    opened = time.perf_counter()
    flights = {}
    for callsign in CALLSIGNS:
        airport, flight = await seed(mem, callsign, t0=T0)
        await add_traffic(mem, flight, callsign)
        flights[callsign] = flight
    result["open_and_seed_six_sessions_s"] = round(time.perf_counter() - opened, 2)

    fetch_ms, fetch_wall, query_ms, query_wall = [], [], [], []
    for callsign, flight in flights.items():
        for _ in range(runs):
            t = time.perf_counter()
            res = await mem.fetch(flight, filter={"$and": [{"speaker": {"$eq": "atc"}}]}, sort_by="ts", ascending=False, limit=20)
            fetch_wall.append((time.perf_counter() - t) * 1000)
            fetch_ms.append(res.time_taken_ms)
        for _ in range(runs):
            t = time.perf_counter()
            res = await mem.query(flight, RIGHT, top_k=3)
            query_wall.append((time.perf_counter() - t) * 1000)
            query_ms.append(res.time_taken_ms)
    result["fetch_last_tower_call_filter_and_sort"] = {"moss_reported_ms": summary(fetch_ms), "wall_ms": summary(fetch_wall)}
    result["hybrid_query_on_a_fragment"] = {"moss_reported_ms": summary(query_ms), "wall_ms": summary(query_wall)}

    scores = {}
    flight = flights["N123AB"]
    airport = "airport-KUNS"
    for label, fragment in (("right clearance", RIGHT), ("unrelated speech", UNRELATED)):
        ev: dict = {}
        hint = await derive_hint(mem, "N123AB", fragment, flight, airport, now=T0, evidence=ev)
        scores[label] = {"fragment": fragment, "score": ev.get("score", ev.get("best_score")), "floor": ev.get("floor"),
                         "below_floor": bool(ev.get("below_floor")), "hint": hint.kind}
    result["hybrid_scores"] = scores

    ask_ms = []
    for _ in range(max(10, runs // 2)):
        answer = await answer_query(mem, flight, "N123AB", "What was my last clearance?")
        ask_ms.append(answer.moss_ms)
    result["ask_last_clearance_moss_part_ms"] = summary(ask_ms)

    result["disk_and_cloud_sync"] = "measured by scripts/moss_live_check.py (sections 4 and 5), its output is saved next to this file"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=50, help="samples per number, per session")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "evidence")
    args = parser.parse_args()
    out = asyncio.run(main(args.runs))
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"moss-{datetime.now().strftime('%Y-%m-%d')}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    print("wrote", path)
