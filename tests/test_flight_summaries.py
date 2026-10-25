"""A one-line record of each flight in Elastic when it ends: counts only, best effort, never in the way of a landing."""

import asyncio
import json

import httpx

from unstep.cockpit.memory import Doc, LocalMemory
from unstep.ground.flights import FlightSummaries, summarize
from unstep.live.flightlog import FlightLog


def docs():
    return [Doc("h1", "Cessna 1-2-3 [static]", {"type": "heard", "stepped_on": "true"}),
            Doc("h2", "hold short", {"type": "heard", "stepped_on": "false"}),
            Doc("r1", "hold short 33", {"type": "readback"}),
            Doc("c1", "hold short runway 33", {"type": "clearance"}),
            Doc("a1", "advisory", {"type": "advisory"})]


def test_the_summary_counts_calls_blocked_calls_and_readbacks():
    s = summarize("N123AB", "118.700", "N123AB-1", "landed: no activity for 10 min", 1_000, docs())
    assert s["calls_heard"] == 2 and s["blocked_calls"] == 1 and s["readbacks"] == 1 and s["clearances"] == 1
    assert s["advisories"] == 1 and s["doc_count"] == 5 and s["@timestamp"] == 1_000 and s["callsign"] == "N123AB"
    assert "text" not in s and "words" not in s  # counts only; the words stay in the plane's own flight log


def test_the_summary_is_written_to_elastic_with_its_index_created_once():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"result": "created"})

    async def go():
        fs = FlightSummaries("https://es.example", "key", transport=httpx.MockTransport(handler))
        assert await fs.record({"callsign": "A"}) and await fs.record({"callsign": "B"})

    asyncio.run(go())
    assert [m for m, _, _ in seen] == ["PUT", "POST", "POST"]  # one index creation, two documents
    assert seen[0][1] == "/unstep-flights" and seen[1][1] == "/unstep-flights/_doc"


def test_a_failed_write_is_logged_and_does_not_raise():
    async def go():
        fs = FlightSummaries("https://es.example", "key", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        return await fs.record({"callsign": "A"})

    assert asyncio.run(go()) is False


def test_archiving_a_flight_sends_its_summary_off_the_landing_path():
    class Fake:
        def __init__(self):
            self.got = []

        async def record(self, summary):
            await asyncio.sleep(0.05)  # a slow Elastic
            self.got.append(summary)
            return True

    async def go():
        mem = LocalMemory()
        log = FlightLog(mem, "118.700")
        log.summaries = Fake()
        mem.register_index("flight-A", "cockpit")
        await mem.add_docs("flight-A", docs(), "cockpit")
        started = asyncio.get_running_loop().time()
        record = await log.archive("A", mem, "flight-A", "landed: no activity for 10 min")
        quick = asyncio.get_running_loop().time() - started
        await asyncio.sleep(0.2)
        return record, quick, log.summaries.got

    record, quick, got = asyncio.run(go())
    assert record["docs"] == 5 and quick < 0.04  # the landing did not wait for Elastic
    assert got and got[0]["callsign"] == "A" and got[0]["blocked_calls"] == 1 and got[0]["frequency"] == "118.700"


def test_the_audit_agent_can_read_the_flight_summaries_and_the_deploy_creates_the_index():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    agent = json.loads((root / "elastic" / "agents" / "unstep-audit.json").read_text())
    assert "unstep_audit_landed_flights" in agent["configuration"]["tools"][0]["tool_ids"]
    out = subprocess.run([sys.executable, str(root / "scripts" / "deploy_elastic.py"), "--dry-run"],
                         capture_output=True, text=True, check=True).stdout
    assert "index unstep-flights" in out and "unstep_audit_landed_flights" in out
