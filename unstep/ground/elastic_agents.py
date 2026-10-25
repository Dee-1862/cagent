"""Ground agents on Elastic (B5): Agent Builder agents run by an Elastic Workflow.

The definitions live in elastic/ (tools, agents, workflows) and scripts/deploy_elastic.py
creates them. Per stepped-on call the hub starts the `unstep-blocked-call` workflow
(manual trigger, POST /api/workflows/workflow/{id}/run), the Intercept and Compliance
agents run, and the workflow stores their answers in `unstep-proposals` under the event
id, which the hub reads back.

Safety: the agents never write the instruction. The hub builds it from the controller's
own transcript (mock_agents.propose); the agents can only add the FAA citation and lower
the confidence (Intercept says no match, Compliance says not restrictive), which sends the
call to the human. A citation is kept only if that paragraph exists in `unstep-faa`. Any
error or a slow run (UNSTEP_AGENTS_WAIT_S, default 6 s) keeps the local proposal.

Opt in with UNSTEP_ELASTIC_AGENTS=1 plus the Elastic and Kibana settings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from unstep.config import elastic_settings, env, kibana_url
from unstep.contracts import AnomalyEvent, ProposedDirective, TowerTranscript

log = logging.getLogger("unstep.elastic_agents")

BLOCKED_CALL_WORKFLOW = "unstep-blocked-call"
READBACK_AUDIT_WORKFLOW = "unstep-readback-audit"
PROPOSALS_INDEX = "unstep-proposals"
FINDINGS_INDEX = "unstep-findings"
FAA_INDEX = "unstep-faa"
_PARAGRAPH = re.compile(r"^\d{1,2}-\d{1,2}-\d{1,2}$")


def parse_agent_json(text) -> dict | None:
    """The first JSON object in an agent's reply (agents are told to answer JSON only)."""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start:i + 1])
                        return value if isinstance(value, dict) else None
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


@dataclass
class AgentsResult:
    intercept: dict | None
    compliance: dict | None
    execution_id: str | None = None
    took_ms: float = 0.0
    citation_checked: bool | None = None  # True: paragraph found in unstep-faa
    notes: list[str] = field(default_factory=list)


def merge(proposal: ProposedDirective, result: AgentsResult | None) -> ProposedDirective:
    """Add what the agents found to the hub's own proposal. Agents can lower confidence, never raise it."""
    if result is None:
        return proposal
    update: dict = {}
    method = proposal.confidence_method or ""
    lower = False
    if result.intercept is not None and result.intercept.get("match") is False:
        lower = True
        result.notes.append("Intercept agent found no match")
    restrictive = result.compliance.get("restrictive") if result.compliance else None
    if restrictive is False and proposal.slots.action in ("hold short", "hold position", "stop", "go around"):
        lower = True
        result.notes.append("Compliance agent says not restrictive")
    paragraph = str((result.compliance or {}).get("paragraph") or "")
    if _PARAGRAPH.match(paragraph) and result.citation_checked:
        title = (result.compliance or {}).get("title")
        update["rule_citation"] = f"FAA JO 7110.65, paragraph {paragraph}" + (f" ({title})" if title else "")
    elif paragraph:
        result.notes.append(f"citation {paragraph!r} not found in {FAA_INDEX}, dropped")
    if lower:
        update["confidence"] = "low"
    update["confidence_method"] = (method + " + Elastic agents (Intercept, Compliance)"
                                   + (": " + "; ".join(result.notes) if result.notes else ""))
    return proposal.model_copy(update=update)


class ElasticAgents:
    def __init__(self, kibana: str, es: str, api_key: str, *, wait_s: float = 6.0, poll_s: float = 0.25,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.kibana, self.es = kibana.rstrip("/"), es.rstrip("/")
        self.wait_s, self.poll_s = wait_s, poll_s
        self.client = httpx.AsyncClient(headers={"Authorization": f"ApiKey {api_key}"}, timeout=5.0,
                                        transport=transport)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _run(self, workflow: str, inputs: dict) -> str | None:
        r = await self.client.post(f"{self.kibana}/api/workflows/workflow/{workflow}/run",
                                   headers={"kbn-xsrf": "true"}, json={"inputs": inputs})
        r.raise_for_status()
        body = r.json() if r.content else {}
        return body.get("workflowExecutionId") or body.get("executionId")

    async def _wait_doc(self, index: str, doc_id: str, deadline: float) -> dict | None:
        while time.perf_counter() < deadline:
            r = await self.client.get(f"{self.es}/{index}/_doc/{doc_id}")
            if r.status_code == 200 and r.json().get("found"):
                return r.json().get("_source") or {}
            await asyncio.sleep(self.poll_s)
        return None

    async def _paragraph_exists(self, paragraph: str) -> bool:
        if not _PARAGRAPH.match(paragraph):
            return False
        r = await self.client.get(f"{self.es}/{FAA_INDEX}/_doc/{paragraph}")
        return r.status_code == 200 and bool(r.json().get("found"))

    async def blocked_call(self, event: AnomalyEvent, transcript: TowerTranscript,
                           proposal: ProposedDirective, wait_s: float | None = None) -> AgentsResult | None:
        """Run the workflow and read the agents' answer back. `wait_s` overrides how long to wait (the late path
        waits longer because nothing is blocked on it)."""
        started = time.perf_counter()
        wait_s = self.wait_s if wait_s is None else wait_s
        try:
            execution_id = await self._run(BLOCKED_CALL_WORKFLOW, {
                "event_id": event.event_id, "callsign": event.callsign, "heard_text": event.heard_text,
                "tower_text": transcript.text, "lost_words": " ".join(proposal.blocked_words),
                "instruction": proposal.instruction_text})
            doc = await self._wait_doc(PROPOSALS_INDEX, event.event_id, started + wait_s)
            if doc is None:
                log.warning("Elastic workflow for %s took over %.1f s; using the local proposal",
                            event.event_id, wait_s)
                return None
            result = AgentsResult(intercept=parse_agent_json(doc.get("intercept")),
                                  compliance=parse_agent_json(doc.get("compliance")),
                                  execution_id=execution_id or doc.get("execution_id"))
            paragraph = str((result.compliance or {}).get("paragraph") or "")
            if paragraph:
                result.citation_checked = await self._paragraph_exists(paragraph)
            result.took_ms = round((time.perf_counter() - started) * 1000, 1)
            return result
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Elastic agents failed for %s (%s); using the local proposal",
                        event.event_id, type(exc).__name__)
            return None

    async def readback_audit(self, event_id: str, instruction: str, readback: str, attempt: int) -> str | None:
        """Start the Readback Auditor; it stores its finding in unstep-findings. Never waits on it."""
        try:
            return await self._run(READBACK_AUDIT_WORKFLOW, {"event_id": event_id, "instruction": instruction,
                                                             "readback": readback, "attempt": attempt})
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("readback audit for %s not started (%s)", event_id, type(exc).__name__)
            return None


def late_wait_s() -> float:
    """How long the late path waits for the agents after the card is already shown (UNSTEP_AGENTS_LATE_S)."""
    try:
        return max(1.0, float(env("UNSTEP_AGENTS_LATE_S", default="30")))
    except ValueError:
        return 30.0


def elastic_agents_from_env() -> ElasticAgents | None:
    if env("UNSTEP_ELASTIC_AGENTS", default="0").lower() not in ("1", "true", "yes", "on"):
        return None
    settings, kb = elastic_settings(), kibana_url()
    if not settings or not kb:
        log.warning("UNSTEP_ELASTIC_AGENTS is on but Elastic or Kibana is not configured; using local agents")
        return None
    try:
        wait_s = float(env("UNSTEP_AGENTS_WAIT_S", default="6"))
    except ValueError:
        wait_s = 6.0
    return ElasticAgents(kb, settings[0], settings[1], wait_s=wait_s)
