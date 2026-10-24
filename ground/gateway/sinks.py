"""Where the gateway stores every message.

write() never waits. Documents go on a bounded queue and a background worker
stores them, so a slow or unreachable store can't hold up the live path. If the
queue is full the document is dropped and counted.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

log = logging.getLogger("unstep.sink")


def to_document(envelope: dict, sender_role: str) -> dict:
    """Flat fields at the top so ES|QL can filter on type, event and time."""
    payload = envelope["payload"]
    return {
        "@timestamp": datetime.fromtimestamp(
            envelope["gateway_ts"] / 1000, tz=timezone.utc
        ).isoformat(),
        "type": envelope["type"],
        "event_id": payload.get("event_id"),
        "callsign": payload.get("callsign"),
        "frequency": payload.get("frequency"),
        "sender_role": sender_role,
        "gateway_ts": envelope["gateway_ts"],
        "sent_at": envelope.get("sent_at"),
        "payload": payload,
    }


class MemorySink:
    """Stores documents in a list. Used by tests and the local demo."""

    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.dropped = 0

    def write(self, document: dict) -> None:
        self.documents.append(document)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class QueuedSink:
    def __init__(self, max_queue: int = 10_000) -> None:
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=max_queue)
        self._worker: asyncio.Task | None = None
        self.dropped = 0

    def write(self, document: dict) -> None:
        try:
            self._queue.put_nowait(document)
        except asyncio.QueueFull:
            self.dropped += 1
            log.warning("sink queue full, dropped %s", document.get("type"))

    async def start(self) -> None:
        self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        await self._queue.join()
        if self._worker:
            self._worker.cancel()

    async def _run(self) -> None:
        while True:
            document = await self._queue.get()
            try:
                await self.store(document)
            except Exception:
                log.exception("failed to store %s", document.get("type"))
            finally:
                self._queue.task_done()

    async def store(self, document: dict) -> None:
        raise NotImplementedError


class JsonlSink(QueuedSink):
    """One JSON document per line. The default when Elastic isn't configured."""

    def __init__(self, path: Path, max_queue: int = 10_000) -> None:
        super().__init__(max_queue)
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def store(self, document: dict) -> None:
        line = json.dumps(document) + "\n"
        await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)


class ElasticSink(QueuedSink):
    """Indexes each document into the Elastic events index."""

    def __init__(self, url: str, api_key: str, index: str, max_queue: int = 10_000) -> None:
        super().__init__(max_queue)
        self.endpoint = f"{url.rstrip('/')}/{index}/_doc"
        self._headers = {"Authorization": f"ApiKey {api_key}"}
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(headers=self._headers, timeout=10)
        await super().start()

    async def stop(self) -> None:
        await super().stop()
        if self._client:
            await self._client.aclose()

    async def store(self, document: dict) -> None:
        response = await self._client.post(self.endpoint, json=document)
        response.raise_for_status()
