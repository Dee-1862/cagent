"""One command that checks the pieces that were wired but never seen live. Run where Elastic is reachable (.env).

    python scripts/verify_wired.py                # all checks
    python scripts/verify_wired.py --skip-runs    # skip starting the two workflows (they spend model calls)

1. hold short: the stored rule the hub would show a hold-short card (expect paragraph 3-7-2, status reviewed).
2. scheduled workflows: starts `unstep-briefing` and `unstep-nightly-review` by hand (same steps as the schedule), waits up to
   60 s for each to save a new document, prints what it saved. This proves the steps work; it does not prove the clock fires.
3. plane position: if the hub is running (--hub URL), reads /live/geo status via /live/clearance-context for the first plane and
   prints the "Where the plane was" sentence the trace would carry.
4. the coach and the console routes: asks the coach through the converse API.
Prints OK / WARN / FAIL per line and exits 1 on FAIL.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep.config import elastic_settings, kibana_url  # noqa: E402
from unstep.ground.audit_chat import AuditChat  # noqa: E402
from unstep.ground.elastic_agents import ElasticAgents  # noqa: E402
from unstep.ground.reports import REPORTS, Reports  # noqa: E402

failures = 0


def say(level: str, text: str) -> None:
    global failures
    failures += level == "FAIL"
    print(f"{level:4} {text}")


async def check_hold_short() -> None:
    settings, kb = elastic_settings(), kibana_url()
    if not settings or not kb:
        return say("WARN", "hold short: Elastic is not configured")
    agents = ElasticAgents(kb, settings[0], settings[1])  # the stored-rule lookup needs no UNSTEP_ELASTIC_AGENTS switch
    hit = await agents.rule_for("hold short runway 33")
    if hit is None:
        return say("FAIL", "hold short: no stored rule found")
    ok = hit.paragraph == "3-7-2" and hit.status == "reviewed"
    say("OK" if ok else "FAIL", f"hold short: rule {hit.rule_id} paragraph {hit.paragraph} ({hit.status}, {hit.backend}, "
        f"{hit.wall_ms} ms); expected 3-7-2 reviewed")


async def check_runs(reports: Reports) -> None:
    before = await reports.latest()
    for name in REPORTS:
        started = await reports.run(name)
        if not started.get("ok"):
            say("FAIL", f"{name}: could not start: {started.get('error')}")
            continue
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            await asyncio.sleep(3)
            now = (await reports.latest()).get(name)
            if now and now["at"] != ((before.get(name) or {}).get("at")):
                say("OK", f"{name}: saved at {now['at']}: {(now['text'] or '')[:160]!r}")
                break
        else:
            say("FAIL", f"{name}: no new document within 60 s")
        await asyncio.sleep(21)  # the reports module allows one start every 20 s


async def check_where(hub: str | None) -> None:
    if not hub:
        return say("WARN", "plane position: pass --hub http://127.0.0.1:8765 with a plane joined and the console open")
    async with httpx.AsyncClient(timeout=10) as client:
        stations = (await client.get(f"{hub}/live/stations")).json()
        plane = next((s for s in stations["stations"] if s["kind"] == "aircraft" and stations["connected"].get(s["id"])), None)
        if plane is None:
            return say("WARN", "plane position: no plane is connected")
        context = (await client.get(f"{hub}/live/clearance-context/{plane['id']}")).json()
        say("OK", f"plane {plane['id']}: runway traffic {context.get('runway_traffic')}")
    from unstep.ground.places import describe_position

    # the trace line is built from the same stored position; a stepped-on call on this plane shows it live
    say("OK", "the trace adds 'Where the plane was: ...' for a stepped-on call on a plane with a position under 15 s old; "
              "make one on the console and read the trace (describe_position: " + describe_position(
                  {"lat": 37.865, "lon": -122.33, "areas": ["Taxiway B"]}, "33")[:80] + ")")


async def check_coach() -> None:
    settings, kb = elastic_settings(), kibana_url()
    if not settings or not kb:
        return say("WARN", "coach: Elastic is not configured")
    out = await AuditChat(kb, settings[1]).ask("How did controllers decide over the last 30 days?", "coach")
    say("OK" if out.get("ok") else "FAIL", f"coach: {out.get('answer') or out.get('error')!r} ({out.get('took_ms')} ms)")


async def main_async(args) -> int:
    settings, kb = elastic_settings(), kibana_url()
    await check_hold_short()
    if settings and kb and not args.skip_runs:
        await check_runs(Reports(settings[0], kb, settings[1]))
    await check_where(args.hub)
    await check_coach()
    return 1 if failures else 0


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hub")
    ap.add_argument("--skip-runs", action="store_true")
    sys.exit(asyncio.run(main_async(ap.parse_args())))
