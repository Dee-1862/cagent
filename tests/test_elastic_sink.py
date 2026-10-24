"""Task B1: the gateway stores every message in the Elastic events index."""

import asyncio
import json
import os
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from unstep.config import elastic_settings, load_env
from unstep.contracts import AnomalyEvent, ProposedDirective, Slots, VoiceApproval, wrap
from unstep.gateway.server import create_app
from unstep.gateway.sink import ElasticSink, to_document

TS = 1792771331000


class FakeElastic:
    """Records requests and answers like Elastic's index and _bulk APIs."""

    def __init__(self, fail_bulk: int = 0, reject: bool = False, delay: float = 0):
        self.created_index = 0
        self.documents: list[dict] = []
        self.fail_bulk = fail_bulk
        self.reject = reject
        self.delay = delay

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.delay:
            await asyncio.sleep(self.delay)
        if request.method == "PUT":
            self.created_index += 1
            if self.created_index > 1:
                return httpx.Response(400, json={"error": {"type": "resource_already_exists_exception"}})
            return httpx.Response(200, json={"acknowledged": True})
        if self.fail_bulk:
            self.fail_bulk -= 1
            return httpx.Response(503)
        lines = request.content.decode().splitlines()
        docs = [json.loads(line) for line in lines[1::2]]
        self.documents.extend(docs)
        item = {"index": {"status": 400, "error": {"type": "mapper_exception"}}} if self.reject else {"index": {"status": 201}}
        return httpx.Response(200, json={"errors": self.reject, "items": [item for _ in docs]})


def make_sink(fake: FakeElastic, **kwargs) -> ElasticSink:
    return ElasticSink("https://es.example", "key", transport=httpx.MockTransport(fake), **kwargs)


def record(type_name: str = "AnomalyEvent", **data) -> dict:
    return {"source": "cockpit", "type": type_name, "ts": TS, "data": {"event_id": "evt-1", "callsign": "N123AB", **data}}


def test_document_promotes_query_fields():
    doc = to_document(record("ReadbackResult", match=False, frequency="118.300"))
    assert doc["@timestamp"].startswith("2026-10-")
    assert (doc["type"], doc["event_id"], doc["callsign"], doc["match"]) == ("ReadbackResult", "evt-1", "N123AB", False)
    assert doc["data"]["frequency"] == "118.300"


def test_decisions_are_promoted():
    assert to_document(record("ApprovedDirective", approved_via="voice"))["decision"] == "approve"
    assert to_document(record("RejectedDirective"))["decision"] == "reject"


def test_documents_are_sent_in_bulk_and_index_created():
    async def run():
        fake = FakeElastic()
        sink = make_sink(fake)
        for i in range(5):
            sink.write(record(event_id=f"evt-{i}"))
        await sink.aclose()
        return fake, sink

    fake, sink = asyncio.run(run())
    assert fake.created_index == 1
    assert [d["event_id"] for d in fake.documents] == [f"evt-{i}" for i in range(5)]
    assert (sink.sent, sink.failed, sink.dropped) == (5, 0, 0)


def test_one_failed_bulk_request_is_retried():
    async def run():
        fake = FakeElastic(fail_bulk=1)
        sink = make_sink(fake)
        sink.write(record())
        await sink.aclose()
        return sink

    sink = asyncio.run(run())
    assert (sink.sent, sink.failed) == (1, 0)


def test_unreachable_elastic_is_counted_never_raised():
    async def run():
        sink = make_sink(FakeElastic(fail_bulk=99))
        sink.write(record())
        await sink.aclose()
        return sink

    sink = asyncio.run(run())
    assert (sink.sent, sink.failed) == (0, 1)


def test_rejected_documents_are_counted():
    async def run():
        sink = make_sink(FakeElastic(reject=True))
        sink.write(record())
        await sink.aclose()
        return sink

    assert asyncio.run(run()).failed == 1


def test_write_never_waits_for_the_network():
    async def run():
        sink = make_sink(FakeElastic(delay=1), max_queue=2)
        start = time.perf_counter()
        for _ in range(5):
            sink.write(record())
        elapsed = time.perf_counter() - start
        dropped = sink.dropped
        sink._worker.cancel()
        return elapsed, dropped

    elapsed, dropped = asyncio.run(run())
    assert elapsed < 0.05
    assert dropped >= 2  # queue of 2 is full while Elastic is slow


def test_gateway_stores_the_approval_flow_in_elastic():
    fake = FakeElastic()
    slots = Slots(callsign="N123AB", action="hold short", runway="33")
    with TestClient(create_app(make_sink(fake))) as client:
        with client.websocket_connect("/ws/agents") as agents, client.websocket_connect(
            "/ws/controller_voice"
        ) as voice, client.websocket_connect("/ws/cockpit") as cockpit:
            agents.send_text(
                wrap(
                    ProposedDirective(
                        event_id="evt-1",
                        transcript_id="tt-1",
                        blocked_words=["hold", "short", "Runway", "33"],
                        instruction_text="Cessna 1-2-3, hold short Runway 33",
                        slots=slots,
                        confidence="high",
                        confidence_method="test",
                        rule_citation="test",
                    )
                )
            )
            voice.receive_json()
            voice.send_text(wrap(VoiceApproval(event_id="evt-1", heard_text="approve", decision="approve", attempt=1)))
            assert cockpit.receive_json()["type"] == "ApprovedDirective"
    # Leaving the client runs the shutdown flush.
    types = [d["type"] for d in fake.documents]
    assert types == ["ProposedDirective", "VoiceApproval", "ApprovedDirective"]
    approved = fake.documents[-1]
    assert (approved["decision"], approved["approved_via"], approved["source"]) == ("approve", "voice", "gateway")


@pytest.mark.skipif(os.getenv("UNSTEP_LIVE_ELASTIC") != "1", reason="set UNSTEP_LIVE_ELASTIC=1 to hit the real cluster")
def test_live_elastic_round_trip():
    load_env()
    settings = elastic_settings()
    assert settings, "Elastic URL and key missing from .env"
    url, key = settings
    index = f"unstep-events-test-{uuid.uuid4().hex[:8]}"
    headers = {"Authorization": f"ApiKey {key}"}

    async def run():
        sink = ElasticSink(url, key, index=index)
        sink.write({"source": "cockpit", "type": "AnomalyEvent", "ts": TS, "data": {"event_id": "evt-live"}})
        await sink.aclose()
        return sink

    try:
        sink = asyncio.run(run())
        assert (sink.sent, sink.failed) == (1, 0)
        httpx.post(f"{url}/{index}/_refresh", headers=headers, timeout=20)
        count = httpx.get(f"{url}/{index}/_count", headers=headers, timeout=20).json()["count"]
        assert count == 1
    finally:
        httpx.delete(f"{url}/{index}", headers=headers, timeout=20)
