"""P2: readbacks checked against the approved directive stored as an Elastic percolator query."""

import asyncio
import json

import httpx

from unstep.contracts import ApprovedDirective, ReadbackResult, Slots, wrap
from unstep.gateway.server import Gateway
from unstep.gateway.sink import MemorySink
from unstep.ground.percolate import ElasticPercolator, LocalPercolator, directive_query, normalize


def directive(event_id="ev-1", runway="33", action="hold short"):
    return ApprovedDirective(event_id=event_id, instruction_text=f"Cessna 1-2-3, {action} Runway {runway}",
                             slots=Slots(callsign="N123AB", action=action, runway=runway),
                             approved_by="controller", approved_via="click")


def test_normalize_reads_spoken_and_written_numbers_the_same():
    assert normalize("Hold short runway tree tree, Cessna one two three.") == "hold short runway 33 cessna 123"
    assert normalize("hold short runway 33, Cessna 1-2-3") == "hold short runway 33 cessna 123"


def test_query_needs_action_runway_and_callsign():
    q = directive_query(directive())
    assert q == {"bool": {"must": [{"match_phrase": {"text": "hold short"}},
                                   {"match_phrase": {"text": "runway 33"}},
                                   {"match": {"text": "123"}}]}}


def test_local_percolator_catches_wrong_runway_and_missing_hold_short():
    async def go():
        p = LocalPercolator()
        await p.register(directive())
        right = await p.check("ev-1", "Hold short runway three three, Cessna one two three.")
        wrong_runway = await p.check("ev-1", "Hold short runway two three, Cessna one two three.")
        no_hold = await p.check("ev-1", "Runway three three, Cessna one two three.")
        other_plane = await p.check("ev-1", "Hold short runway three three, Piper seven eight niner.")
        assert (right.match, wrong_runway.match, no_hold.match, other_plane.match) == (True, False, False, False)
        assert await p.check("unknown", "anything") is None

    asyncio.run(go())


def fake_elastic(log):
    def handler(request: httpx.Request) -> httpx.Response:
        log.append((request.method, request.url.path, json.loads(request.content or b"{}")))
        if request.url.path.endswith("/_search"):
            doc = json.loads(request.content)["query"]["bool"]["must"]["percolate"]["document"]["text"]
            hits = [{"_id": "ev-1"}] if "runway 33" in doc else []
            return httpx.Response(200, json={"took": 2, "hits": {"hits": hits}})
        return httpx.Response(200, json={"result": "created"})

    return httpx.MockTransport(handler)


def test_elastic_percolator_stores_the_query_and_reports_took():
    async def go():
        log = []
        p = ElasticPercolator("https://es.example", "key", transport=fake_elastic(log))
        await p.register(directive())
        v = await p.check("ev-1", "Hold short runway three three, Cessna one two three.")
        assert v.match and v.backend == "elastic" and v.took_ms == 2
        stored = next(body for method, path, body in log if path == "/unstep-clearances/_doc/ev-1")
        assert stored["query"] == directive_query(directive()) and stored["callsign"] == "N123AB"
        search = log[-1][2]["query"]["bool"]
        assert search["filter"] == {"term": {"event_id": "ev-1"}}
        assert not (await p.check("ev-1", "Hold short runway two three, Cessna one two three.")).match
        await p.aclose()

    asyncio.run(go())


def test_elastic_down_falls_back_to_the_same_local_result():
    async def go():
        def down(request):
            raise httpx.ConnectError("blocked")

        p = ElasticPercolator("https://es.example", "key", transport=httpx.MockTransport(down))
        await p.register(directive())
        v = await p.check("ev-1", "Hold short runway three three, Cessna one two three.")
        assert v.match and v.backend == "local"
        await p.aclose()

    asyncio.run(go())


class Socket:
    def __init__(self):
        self.sent = []

    async def send_text(self, raw):
        self.sent.append(raw)

    async def send_json(self, m):
        self.sent.append(json.dumps(m))


def test_gateway_audits_every_readback_with_the_percolator_verdict():
    async def go():
        sink = MemorySink()
        gw = Gateway(sink)
        await gw.emit(directive())
        await asyncio.sleep(0.01)
        await gw.handle("cockpit", wrap(ReadbackResult(event_id="ev-1", match=False,
                                                       readback_text="Hold short runway two three, Cessna one two three.")),
                        Socket())
        await asyncio.sleep(0.05)
        audits = [r for r in sink.records if r["type"] == "AuditRecord" and r["data"]["stage"] == "readback_percolate"]
        assert len(audits) == 1
        data = audits[0]["data"]
        assert data["payload"]["match"] is False and data["payload"]["slot_check_match"] is False
        assert data["payload"]["normalized_readback"] == "hold short runway 23 cessna 123"

    asyncio.run(go())
