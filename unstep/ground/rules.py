"""The FAA rule for an instruction as data: stored in Elastic as percolator queries, answered in milliseconds.

The usual use of a search engine is "store documents, run a query". The readback matcher (percolate.py) already
flips that: it stores each approved directive as a query and runs each readback through them. This does the same
for the rule book. Each rule is a stored query ("hold short" or "holding short"); a proposed instruction is the
document; Elastic returns the rules whose query it matches, with no model in the loop. Rules are data: a person
adds or fixes one in the index and the next instruction uses it, with no deploy.

`LocalRules` evaluates the same stored queries in process (so the hub answers in microseconds and offline, and the
two can be compared in tests). `ElasticRules` percolates in Elastic and keeps `took` and the wall time so the
numbers can be shown. Neither claims a paragraph that a person has not reviewed as reviewed.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from unstep.ground.percolate import normalize

log = logging.getLogger("unstep.rules")

RULES_INDEX = "unstep-rules"
RULES_FILE = Path(__file__).resolve().parent.parent.parent / "elastic" / "rules" / "rules.json"

MAPPINGS = {
    "dynamic": "strict",
    "properties": {
        "query": {"type": "percolator"},
        "text": {"type": "text"},  # the field stored queries match on
        "paragraph": {"type": "keyword"},
        "title": {"type": "keyword"},
        "status": {"type": "keyword"},
        "evidence": {"type": "keyword", "index": False},
    },
}


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    paragraph: str | None
    title: str | None
    status: str  # reviewed | candidate | needs_review
    backend: str  # local or elastic
    took_ms: float  # evaluation time (Elastic's own `took` for the elastic backend)
    wall_ms: float  # including the network

    def payload(self) -> dict:
        return {"rule_id": self.rule_id, "paragraph": self.paragraph, "title": self.title, "status": self.status,
                "backend": self.backend, "took_ms": round(self.took_ms, 3), "wall_ms": round(self.wall_ms, 2)}


def load_rules(path: Path = RULES_FILE) -> list[dict]:
    return json.loads(path.read_text())["rules"]


def rule_query(rule: dict) -> dict:
    """Any of the rule's phrases, as a stored Elastic query."""
    return {"bool": {"should": [{"match_phrase": {"text": normalize(p)}} for p in rule["phrases"]],
                     "minimum_should_match": 1}}


def rule_doc(rule: dict) -> dict:
    return {"query": rule_query(rule), "paragraph": rule.get("paragraph"), "title": rule.get("title"),
            "status": rule.get("status", "needs_review"), "evidence": rule.get("evidence")}


def _phrase_in(tokens: list[str], phrase: str) -> bool:
    words = phrase.split()
    return any(tokens[i:i + len(words)] == words for i in range(len(tokens) - len(words) + 1))


def matches(query: dict, normalized: str) -> bool:
    tokens = normalized.split()
    return any(_phrase_in(tokens, c["match_phrase"]["text"]) for c in query["bool"]["should"])


class LocalRules:
    backend = "local"

    def __init__(self, rules: list[dict] | None = None) -> None:
        self.rules = {r["id"]: r for r in (load_rules() if rules is None else rules)}
        self.queries = {i: rule_query(r) for i, r in self.rules.items()}

    def match(self, instruction_text: str) -> list[RuleHit]:
        started = time.perf_counter()
        norm = normalize(instruction_text)
        found = [i for i, q in self.queries.items() if matches(q, norm)]
        ms = (time.perf_counter() - started) * 1000
        return [RuleHit(i, self.rules[i].get("paragraph"), self.rules[i].get("title"),
                        self.rules[i].get("status", "needs_review"), self.backend, ms, ms) for i in found]


class ElasticRules:
    """Percolates a proposed instruction against the stored rules in Elastic."""

    backend = "elastic"

    def __init__(self, url: str, api_key: str, index: str = RULES_INDEX,
                 transport: httpx.AsyncBaseTransport | None = None, timeout_s: float = 2.0):
        self.url, self.index = url.rstrip("/"), index
        self.client = httpx.AsyncClient(headers={"Authorization": f"ApiKey {api_key}"}, timeout=timeout_s,
                                        transport=transport)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def match(self, instruction_text: str) -> list[RuleHit]:
        started = time.perf_counter()
        body = {"query": {"percolate": {"field": "query", "document": {"text": normalize(instruction_text)}}},
                "_source": ["paragraph", "title", "status"]}
        try:
            r = await self.client.post(f"{self.url}/{self.index}/_search", json=body)
            r.raise_for_status()
            result = r.json()
        except (httpx.HTTPError, ValueError):
            log.warning("Elastic rule percolate failed; no rule from Elastic")
            return []
        wall = (time.perf_counter() - started) * 1000
        took = float(result.get("took", 0))
        return [RuleHit(h["_id"], (h.get("_source") or {}).get("paragraph"), (h.get("_source") or {}).get("title"),
                        (h.get("_source") or {}).get("status", "needs_review"), self.backend, took, wall)
                for h in result.get("hits", {}).get("hits", [])]


def describe(hit: RuleHit | None) -> str | None:
    """The card's wording. A reviewed paragraph reads as the rule; anything else says it is a candidate."""
    if hit is None or not hit.paragraph:
        return None
    title = f" ({hit.title})" if hit.title else ""
    base = f"FAA JO 7110.65, paragraph {hit.paragraph}{title}"
    if hit.status == "reviewed":
        return f"{base}, matched in {round(hit.took_ms, 2)} ms by a stored rule"
    return f"Candidate rule, not yet reviewed: {base}, matched in {round(hit.took_ms, 2)} ms by a stored rule"
