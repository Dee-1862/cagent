"""Live smoke test for MossMemory.

Seeds `airport-KUNS` and `flight-N123AB` through MossMemory (the same seed the
demo uses), runs the demo hint query, runs a `$gte` filter on `ts`, prints
Moss `time_taken_ms`, and checks that numeric filters work on `ts` even though
Moss stores metadata as strings. Pushes both indexes to Moss Cloud unless
--no-push is given.

Needs MOSS_PROJECT_ID and MOSS_PROJECT_KEY in .env; otherwise prints
"skipped: ..." and exits 0.

Run from the repo root: python scripts/smoke_moss.py [--no-push]
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


async def main(push: bool) -> int:
    pid, pkey = os.getenv("MOSS_PROJECT_ID"), os.getenv("MOSS_PROJECT_KEY")
    if not pid or not pkey:
        print("skipped: MOSS_PROJECT_ID/MOSS_PROJECT_KEY not set")
        return 0

    from unstep.cockpit.hint import derive_hint
    from unstep.cockpit.memory import MossMemory
    from unstep.cockpit.seed import COCKPIT, PREFLIGHT, seed
    from unstep.scenario import CALLSIGN, T0, anomaly_event

    mem = MossMemory(pid, pkey)
    t = time.perf_counter()
    a, f = await seed(mem)
    print(f"seeded {a} and {f} in {1000 * (time.perf_counter() - t):.0f} ms (session open + embed)")

    failures = 0

    # Demo hint query (same call the cockpit makes on a stepped-on transmission).
    heard = anomaly_event().heard_text
    hint = await derive_hint(mem, CALLSIGN, heard, f, a, now=T0)  # seed data is stamped at T0
    print(f"[hint] heard={heard!r} -> kind={hint.kind} text={hint.text!r} "
          f"source={hint.source_doc_id} moss_ms={hint.moss_ms}")
    if hint.kind != "restrictive" or hint.source_doc_id != f"{f}/clr-0007":
        print("[hint] FAIL: expected restrictive hint from clr-0007")
        failures += 1

    # Raw hint-style query, to show time_taken_ms per call.
    res = await mem.query(f, "Cessna 1-2-3 runway taxi hold short", top_k=3, alpha=0.4,
                          filter={"$and": [{"callsign": {"$eq": CALLSIGN}}, {"type": {"$eq": "clearance"}}]})
    print(f"[query] time_taken_ms={res.time_taken_ms:.3f} docs=" + ", ".join(f"{d.id}:{d.score:.3f}" for d in res.docs))

    # $gte on ts. Seed ts values: clr-0005 = T0-6min, clr-0006 = T0-5min, clr-0007 = T0-3min.
    # A cutoff of T0-4min must return only clr-0007. A lexicographic string compare would
    # also pass here, so a second cutoff with fewer digits (1000) must return all three.
    cases = [
        ("int cutoff T0-4min", {"ts": {"$gte": T0 - 4 * 60_000}}, {"clr-0007"}),
        ("str cutoff T0-4min", {"ts": {"$gte": str(T0 - 4 * 60_000)}}, {"clr-0007"}),
        ("int cutoff 1000 (fewer digits)", {"ts": {"$gte": 1000}}, {"clr-0005", "clr-0006", "clr-0007"}),
        ("int cutoff 9e12 (none)", {"ts": {"$gte": 9_000_000_000_000}}, set()),
    ]
    for label, flt, want in cases:
        try:
            r = await mem.query(f, "Cessna 1-2-3 clearance", top_k=10, alpha=0.5, filter=flt)
            got = {d.id for d in r.docs}
            ok = got == want
            failures += not ok
            print(f"[ts $gte] {label}: {'PASS' if ok else 'FAIL'} got={sorted(got)} want={sorted(want)} "
                  f"time_taken_ms={r.time_taken_ms:.3f}")
        except Exception as e:  # report and keep going: this is the check we care about
            failures += 1
            print(f"[ts $gte] {label}: ERROR {type(e).__name__}: {e}")

    if push:
        for index, owner in ((a, PREFLIGHT), (f, COCKPIT)):
            t = time.perf_counter()
            await mem.push(index, writer=owner)
            print(f"[push] {index} pushed in {1000 * (time.perf_counter() - t):.0f} ms")

    print("ok" if not failures else f"{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(push="--no-push" not in sys.argv)))
