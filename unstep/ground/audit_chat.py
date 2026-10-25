"""Ask the audit trail (E-2): a controller's question, answered by an Elastic Agent Builder agent whose tools are
ES|QL over the audit data, with the ES|QL it ran shown.

Off the radio path: it only runs when someone asks on the console, with a timeout, a length limit and one
question at a time, and a failure just says so. Read-only: the agent has no tool that can change anything. Only
real traffic is read (simulated runs live in another index). The converse response shape is read from search
summaries of Elastic's docs, not from a live cluster, so `parse_converse` is tolerant and the first live run
(docs/19, E-1) should pin the real shape with a test.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

from unstep.config import elastic_settings, kibana_url

log = logging.getLogger("unstep.audit_chat")

AGENT_ID = "unstep-audit"
AGENTS = {"audit": "unstep-audit", "coach": "unstep-coach"}  # the console may address either; both are read-only
MAX_QUESTION = 300
TIMEOUT_S = 25.0
MIN_GAP_S = 1.5  # at most one question per this many seconds, across all consoles
_ESQL = re.compile(r"^\s*(FROM|ROW|SHOW|TS)\b", re.I)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _unmojibake(text: str) -> str:
    """Repair UTF-8 text that was read as cp1252 somewhere on the way (an em dash turns into three odd characters)."""
    if "\u00e2" not in text and "\u00c3" not in text:
        return text
    try:
        return text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def parse_converse(body) -> dict:
    """Pull the answer text and the ES|QL the agent ran out of a converse response, without assuming the layout."""
    answer = None
    if isinstance(body, dict):
        resp = body.get("response")
        for candidate in (resp.get("message") if isinstance(resp, dict) else resp, body.get("message"),
                          body.get("output"), body.get("answer")):
            if isinstance(candidate, str) and candidate.strip():
                answer = candidate.strip()
                break
    queries: list[str] = []
    for d in _walk(body):
        for key in ("query", "esql", "esql_query"):
            v = d.get(key)
            if isinstance(v, str) and _ESQL.match(v) and v.strip() not in queries:
                queries.append(v.strip())
    tools = sorted({d["tool_id"] for d in _walk(body) if isinstance(d.get("tool_id"), str)})
    answer = _unmojibake(answer) if answer else answer
    return {"answer": answer, "esql": queries, "tools": tools}


class AuditChat:
    def __init__(self, kibana: str, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = TIMEOUT_S):
        self.kibana, self.timeout_s = kibana.rstrip("/"), timeout_s
        self.client = httpx.AsyncClient(headers={"Authorization": f"ApiKey {api_key}", "kbn-xsrf": "true"},
                                        timeout=timeout_s, transport=transport)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def ask(self, question: str, agent: str = "audit") -> dict:
        agent_id = AGENTS.get(agent, AGENT_ID)
        question = " ".join((question or "").split())[:MAX_QUESTION]
        if not question:
            return {"ok": False, "error": "Ask a question first."}
        if self._lock.locked() or time.monotonic() - self._last < MIN_GAP_S:
            return {"ok": False, "error": "One question at a time. Try again in a moment."}
        async with self._lock:
            self._last = time.monotonic()
            started = time.perf_counter()
            try:
                r = await self.client.post(f"{self.kibana}/api/agent_builder/converse",
                                           json={"input": question, "agent_id": agent_id})
                r.raise_for_status()
                parsed = parse_converse(r.json())
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("audit question failed: %s", type(exc).__name__)
                return {"ok": False, "error": "Elastic didn't answer in time. The radio is unaffected."}
            took = round((time.perf_counter() - started) * 1000)
        if not parsed["answer"]:
            return {"ok": False, "error": "Elastic answered, but without text.", "took_ms": took, **parsed}
        return {"ok": True, "took_ms": took, "agent": agent_id, **parsed}


def audit_chat_from_env() -> AuditChat | None:
    settings, kb = elastic_settings(), kibana_url()
    if not settings or not kb:
        return None
    return AuditChat(kb, settings[1])
