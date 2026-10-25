"""A one-line record of each flight, written to Elastic when the flight ends (`unstep-flights`).

The flight log in Moss holds what a plane heard. This is the summary the tower cares about afterwards: who landed,
why, and how many calls that plane heard and had stepped on. It lets the audit agent answer "which flights landed in
the last hour and how many calls did each miss?" from Elastic. Best effort: a failed write is logged and never
blocks a landing. It records only counts; the words stay in the plane's own flight log.
"""

from __future__ import annotations

import logging
import time
from collections import Counter

import httpx

from unstep.config import elastic_settings, env

log = logging.getLogger("unstep.flights")

FLIGHTS_INDEX = "unstep-flights"

MAPPINGS = {
    "dynamic": "strict",
    "properties": {
        "@timestamp": {"type": "date"},
        "callsign": {"type": "keyword"},
        "frequency": {"type": "keyword"},
        "reason": {"type": "keyword"},
        "landed_ms": {"type": "long"},
        "doc_count": {"type": "integer"},
        "calls_heard": {"type": "integer"},
        "blocked_calls": {"type": "integer"},
        "readbacks": {"type": "integer"},
        "clearances": {"type": "integer"},
        "advisories": {"type": "integer"},
        "flight_id": {"type": "keyword"},
    },
}


def summarize(callsign: str, frequency: str, flight_id: str, reason: str, landed_ms: int, docs: list) -> dict:
    """Counts from the archived documents (their `type` and `stepped_on` metadata)."""
    kinds = Counter(str(d.metadata.get("type", "")) for d in docs)
    blocked = sum(1 for d in docs if d.metadata.get("type") == "heard" and str(d.metadata.get("stepped_on")) == "true")
    return {"@timestamp": landed_ms, "callsign": callsign, "frequency": frequency, "reason": reason,
            "landed_ms": landed_ms, "doc_count": len(docs), "calls_heard": kinds.get("heard", 0),
            "blocked_calls": blocked, "readbacks": kinds.get("readback", 0), "clearances": kinds.get("clearance", 0),
            "advisories": kinds.get("advisory", 0), "flight_id": flight_id}


class FlightSummaries:
    def __init__(self, url: str, api_key: str, index: str = FLIGHTS_INDEX,
                 transport: httpx.AsyncBaseTransport | None = None, timeout_s: float = 4.0):
        self.url, self.index = url.rstrip("/"), index
        self.client = httpx.AsyncClient(headers={"Authorization": f"ApiKey {api_key}"}, timeout=timeout_s,
                                        transport=transport)
        self._ready = False
        self.written = 0

    @classmethod
    def from_env(cls) -> "FlightSummaries | None":
        if env("UNSTEP_FLIGHT_SUMMARIES", default="1").lower() in ("0", "false", "no", "off"):
            return None
        settings = elastic_settings()
        return cls(settings[0], settings[1]) if settings else None

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _ensure_index(self) -> None:
        if self._ready:
            return
        r = await self.client.put(f"{self.url}/{self.index}", json={"mappings": MAPPINGS})
        if r.status_code != 400 or "resource_already_exists" not in r.text:
            r.raise_for_status()
        self._ready = True

    async def record(self, summary: dict) -> bool:
        started = time.perf_counter()
        try:
            await self._ensure_index()
            r = await self.client.post(f"{self.url}/{self.index}/_doc", json=summary)
            r.raise_for_status()
        except (httpx.HTTPError, ValueError):
            log.warning("could not write the flight summary for %s to Elastic; the landing is not affected",
                        summary.get("callsign"))
            return False
        self.written += 1
        log.info("flight summary for %s written to Elastic in %.0f ms", summary.get("callsign"),
                 (time.perf_counter() - started) * 1000)
        return True
