"""Readback matcher in Elastic (P2): every delivered directive becomes a stored query.

The usual direction is "store documents, run a query". A percolator flips it: each
approved directive is stored as a query ("hold short" and "runway 33" and "123"),
and each pilot readback is run against the stored queries as a document. A readback
that matches its directive's query is correct; one that matches nothing is flagged.
Elastic reports its own time for the check (`took`), shown next to our slot check.

When Elastic is not configured or not reachable, LocalPercolator evaluates the same
query dict in process, so the result and the evidence look the same offline.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from unstep.cockpit.phraseology import _digit_tokens, _tokens, callsign_digits
from unstep.contracts import ApprovedDirective

log = logging.getLogger("unstep.percolate")

CLEARANCES_INDEX = "unstep-clearances"

MAPPINGS = {
    "dynamic": "strict",
    "properties": {
        "query": {"type": "percolator"},
        "text": {"type": "text"},  # the field stored queries match on
        "event_id": {"type": "keyword"},
        "callsign": {"type": "keyword"},
        "instruction_text": {"type": "keyword", "index": False},
        "ts": {"type": "long"},
    },
}


def normalize(text: str) -> str:
    """Words to digit groups, so "runway three three" and "runway 33" read the same:
    'Hold short runway tree tree, Cessna one two three' -> 'hold short runway 33 cessna 123'."""
    out: list[str] = []
    for t in _digit_tokens(_tokens(text)):
        if t.isdigit() and out and out[-1].isdigit():
            out[-1] += t
        else:
            out.append(t)
    return " ".join(out)


def directive_query(directive: ApprovedDirective) -> dict:
    """The stored query: the action, the runway and the callsign digits must all be read back."""
    slots = directive.slots
    must: list[dict] = [{"match_phrase": {"text": normalize(slots.action)}}]
    if slots.runway:
        must.append({"match_phrase": {"text": f"runway {normalize(slots.runway)}"}})
    digits = callsign_digits(slots.callsign)
    if digits:
        must.append({"match": {"text": digits}})
    return {"bool": {"must": must}}


@dataclass
class Verdict:
    event_id: str
    match: bool
    backend: str  # elastic or local
    took_ms: float  # Elastic's own `took`, or local evaluation time
    wall_ms: float  # including the network
    normalized: str
    query: dict = field(default_factory=dict)

    def payload(self) -> dict:
        return {"match": self.match, "backend": self.backend, "took_ms": round(self.took_ms, 3),
                "wall_ms": round(self.wall_ms, 1), "normalized_readback": self.normalized, "query": self.query}


class Percolator(Protocol):
    async def register(self, directive: ApprovedDirective) -> None: ...

    async def check(self, event_id: str, readback_text: str) -> Verdict | None: ...


def _phrase_in(tokens: list[str], phrase: str) -> bool:
    words = phrase.split()
    return any(tokens[i:i + len(words)] == words for i in range(len(tokens) - len(words) + 1))


def evaluate(query: dict, normalized: str) -> bool:
    """In-process evaluation of the small query subset directive_query builds."""
    tokens = normalized.split()
    for clause in query["bool"]["must"]:
        if "match_phrase" in clause and not _phrase_in(tokens, clause["match_phrase"]["text"]):
            return False
        if "match" in clause and not set(clause["match"]["text"].split()) & set(tokens):
            return False
    return True


class LocalPercolator:
    backend = "local"

    def __init__(self) -> None:
        self.queries: dict[str, dict] = {}

    async def register(self, directive: ApprovedDirective) -> None:
        self.queries[directive.event_id] = directive_query(directive)

    async def check(self, event_id: str, readback_text: str) -> Verdict | None:
        query = self.queries.get(event_id)
        if query is None:
            return None
        started = time.perf_counter()
        norm = normalize(readback_text)
        ok = evaluate(query, norm)
        ms = (time.perf_counter() - started) * 1000
        return Verdict(event_id, ok, self.backend, ms, ms, norm, query)


class ElasticPercolator:
    """Stores directive queries in Elastic and percolates readbacks; falls back to local on errors."""

    backend = "elastic"

    def __init__(self, url: str, api_key: str, index: str = CLEARANCES_INDEX,
                 transport: httpx.AsyncBaseTransport | None = None, timeout_s: float = 3.0):
        self.url, self.index = url.rstrip("/"), index
        self.client = httpx.AsyncClient(headers={"Authorization": f"ApiKey {api_key}"}, timeout=timeout_s,
                                        transport=transport)
        self.local = LocalPercolator()
        self._ready = False

    async def _ensure_index(self) -> None:
        if self._ready:
            return
        r = await self.client.put(f"{self.url}/{self.index}", json={"mappings": MAPPINGS})
        if r.status_code != 400 or "resource_already_exists" not in r.text:
            r.raise_for_status()
        self._ready = True

    async def register(self, directive: ApprovedDirective) -> None:
        await self.local.register(directive)
        try:
            await self._ensure_index()
            r = await self.client.put(
                f"{self.url}/{self.index}/_doc/{directive.event_id}", params={"refresh": "true"},
                json={"query": directive_query(directive), "event_id": directive.event_id,
                      "callsign": directive.slots.callsign, "instruction_text": directive.instruction_text,
                      "ts": directive.approved_at})
            r.raise_for_status()
        except httpx.HTTPError:
            log.warning("Elastic percolator register failed for %s; local only", directive.event_id)

    async def check(self, event_id: str, readback_text: str) -> Verdict | None:
        local = await self.local.check(event_id, readback_text)
        if local is None:
            return None
        started = time.perf_counter()
        body = {"query": {"bool": {
            "must": {"percolate": {"field": "query", "document": {"text": local.normalized}}},
            "filter": {"term": {"event_id": event_id}}}}}
        try:
            r = await self.client.post(f"{self.url}/{self.index}/_search", json=body)
            r.raise_for_status()
            result = r.json()
        except (httpx.HTTPError, ValueError):
            log.warning("Elastic percolate failed for %s; using the local result", event_id)
            return local
        hits = [h["_id"] for h in result.get("hits", {}).get("hits", [])]
        return Verdict(event_id, event_id in hits, self.backend, float(result.get("took", 0)),
                       (time.perf_counter() - started) * 1000, local.normalized, local.query)

    async def aclose(self) -> None:
        await self.client.aclose()


def percolator_from_env() -> Percolator:
    from unstep.config import elastic_settings

    settings = elastic_settings()
    return ElasticPercolator(*settings) if settings else LocalPercolator()
