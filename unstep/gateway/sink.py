"""Event sink: every message through the gateway is stored here.

ElasticSink writes to the Elastic events index (task B1). JsonlSink appends to
data/events.jsonl when Elastic isn't configured. All sinks share one `write`
method, and ElasticSink.write never waits on the network: documents go on a
bounded queue and a background task sends them with the _bulk API, so a slow
or unreachable cluster can't hold up the live path ("audit never blocks").
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

log = logging.getLogger("unstep.sink")

from unstep.config import elastic_events_index

EVENTS_INDEX = elastic_events_index()

# Fields promoted from the message so ES|QL can filter and aggregate on them (task B8).
PROMOTED = ("event_id", "callsign", "frequency", "decision", "approved_via", "rejected_via", "match", "kind", "stage")

# `data` keeps the whole message in _source but isn't indexed, so one message
# type can never cause a mapping conflict that rejects another.
MAPPINGS = {
    "dynamic": "strict",
    "properties": {
        "@timestamp": {"type": "date"},
        "ts": {"type": "long"},
        "type": {"type": "keyword"},
        "source": {"type": "keyword"},
        "event_id": {"type": "keyword"},
        "callsign": {"type": "keyword"},
        "frequency": {"type": "keyword"},
        "decision": {"type": "keyword"},
        "approved_via": {"type": "keyword"},
        "rejected_via": {"type": "keyword"},
        "match": {"type": "boolean"},
        "kind": {"type": "keyword"},
        "stage": {"type": "keyword"},
        # Only on simulated traffic (scripts/simulate_traffic.py), which goes to its own index.
        "simulated": {"type": "boolean"},
        "run_id": {"type": "keyword"},
        "data": {"type": "object", "enabled": False},
    },
}


def to_document(record: dict) -> dict:
    data = record.get("data") or {}
    document = {
        "@timestamp": datetime.fromtimestamp(record["ts"] / 1000, tz=timezone.utc).isoformat(),
        "ts": record["ts"],
        "type": record["type"],
        "source": record.get("source"),
        "data": data,
    }
    for field in PROMOTED:
        if data.get(field) is not None:
            document[field] = data[field]
    if record.get("simulated"):  # simulated traffic is labelled on every record, machine-readable
        document["simulated"] = True
        document["run_id"] = record.get("run_id")
    if record["type"] == "ApprovedDirective":
        document["decision"] = "approve"
    elif record["type"] == "RejectedDirective":
        document["decision"] = "reject"
    return document


class JsonlSink:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, envelope: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(envelope) + "\n")


class MemorySink:
    """For tests."""

    def __init__(self):
        self.records: list[dict] = []

    def write(self, envelope: dict) -> None:
        self.records.append(envelope)


class ElasticSink:
    def __init__(
        self,
        url: str,
        api_key: str,
        index: str = EVENTS_INDEX,
        batch_size: int = 200,
        max_queue: int = 10_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.url = url.rstrip("/")
        self.index = index
        self.batch_size = batch_size
        self._headers = {"Authorization": f"ApiKey {api_key}", "Content-Type": "application/x-ndjson"}
        self._transport = transport
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=max_queue)
        self._worker: asyncio.Task | None = None
        self.sent = 0
        self.dropped = 0
        self.failed = 0

    def write(self, envelope: dict) -> None:
        try:
            self._queue.put_nowait(to_document(envelope))
        except asyncio.QueueFull:
            self.dropped += 1
            log.warning("Elastic queue full, dropped %s", envelope.get("type"))
            return
        if self._worker is None:
            self._worker = asyncio.get_running_loop().create_task(self._run())

    async def flush(self) -> None:
        """Waits until everything written so far has been sent (or given up on)."""
        await self._queue.join()

    async def aclose(self) -> None:
        await self.flush()
        if self._worker:
            self._worker.cancel()

    async def ensure_index(self, client: httpx.AsyncClient) -> None:
        response = await client.put(
            f"{self.url}/{self.index}",
            json={"mappings": MAPPINGS},
            headers={"Content-Type": "application/json"},
        )
        if response.status_code == 400 and "resource_already_exists" in response.text:
            return
        response.raise_for_status()

    async def _run(self) -> None:
        async with httpx.AsyncClient(headers=self._headers, timeout=15, transport=self._transport) as client:
            try:
                await self.ensure_index(client)
            except httpx.HTTPError:
                log.exception("could not create Elastic index %s", self.index)
            while True:
                batch = [await self._queue.get()]
                while len(batch) < self.batch_size and not self._queue.empty():
                    batch.append(self._queue.get_nowait())
                try:
                    await self._send(client, batch)
                finally:
                    for _ in batch:
                        self._queue.task_done()

    async def _send(self, client: httpx.AsyncClient, batch: list[dict]) -> None:
        body = "".join(
            json.dumps({"index": {"_index": self.index}}) + "\n" + json.dumps(doc) + "\n" for doc in batch
        )
        for attempt in (1, 2):
            try:
                response = await client.post(f"{self.url}/_bulk", content=body)
                response.raise_for_status()
                result = response.json()
                errors = [i["index"]["error"] for i in result["items"] if "error" in i["index"]]
                self.failed += len(errors)
                self.sent += len(batch) - len(errors)
                if errors:
                    log.error("Elastic rejected %d documents, first: %s", len(errors), errors[0])
                return
            except httpx.HTTPError:
                if attempt == 2:
                    self.failed += len(batch)
                    log.exception("Elastic bulk write failed, %d documents lost", len(batch))
                else:
                    await asyncio.sleep(0.5)


def sink_from_env(jsonl_path: Path):
    from unstep.config import elastic_settings

    settings = elastic_settings()
    if settings is None:
        log.info("Elastic not configured, storing events in %s", jsonl_path)
        return JsonlSink(jsonl_path)
    log.info("storing events in Elastic index %s", EVENTS_INDEX)
    return ElasticSink(*settings)
