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
from unstep.ground.rules import ElasticRules, LocalRules, RuleHit, describe

log = logging.getLogger("unstep.elastic_agents")

BLOCKED_CALL_WORKFLOW = "unstep-blocked-call"
BLOCKED_CALL_FAST = "unstep-blocked-call-fast"
BLOCKED_PARALLEL = "parallel"  # two single-purpose workflows started at the same moment
INTERCEPT_WORKFLOW = "unstep-blocked-intercept"
COMPLIANCE_WORKFLOW = "unstep-blocked-compliance"
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
    branches: dict = field(default_factory=dict)  # parallel mode: each agent's own time, ms
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
    current = proposal.rule_citation or ""
    reviewed = "by a stored rule" in current and "Candidate rule" not in current  # a person signed this paragraph off
    if _PARAGRAPH.match(paragraph) and result.citation_checked and reviewed and f"paragraph {paragraph}" not in current:
        # The reviewed stored rule stays on the card; the agent's paragraph is recorded as related (R56: hold short is
        # 3-7-2, the agent and the search prefer 3-7-4).
        result.notes.append(f"Compliance agent also cited {paragraph}, kept as related")
    elif _PARAGRAPH.match(paragraph) and result.citation_checked:
        title = (result.compliance or {}).get("title")
        update["rule_citation"] = f"FAA JO 7110.65, paragraph {paragraph}" + (f" ({title})" if title else "")
    elif paragraph:
        result.notes.append(f"citation {paragraph!r} not found in {FAA_INDEX}, dropped")
    if lower:
        update["confidence"] = "low"
    update["confidence_method"] = (method + " + Elastic agents (Intercept, Compliance)"
                                   + (": " + "; ".join(result.notes) if result.notes else ""))
    return proposal.model_copy(update=update)


def with_closest_rule(proposal: ProposedDirective, hit: dict | None) -> ProposedDirective:
    """Put the hybrid search's closest paragraph on the card at once, labelled as a search result. It never touches
    the instruction or the confidence."""
    if not hit or proposal.rule_citation and "TBD" not in proposal.rule_citation:
        return proposal
    how = "hybrid search + rerank" if hit.get("reranked") else "hybrid search"
    title = f" ({hit['title']})" if hit.get("title") else ""
    return proposal.model_copy(update={
        "rule_citation": f"Closest FAA rule: JO 7110.65, paragraph {hit['paragraph']}{title}, "
                         f"{how} score {hit['score']} in {hit['ms']} ms",
        "confidence_method": (proposal.confidence_method or "") + f" + Elastic {how}"})


class ElasticAgents:
    def __init__(self, kibana: str, es: str, api_key: str, *, wait_s: float = 6.0, poll_s: float = 0.25,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.kibana, self.es = kibana.rstrip("/"), es.rstrip("/")
        self.wait_s, self.poll_s = wait_s, poll_s
        self.client = httpx.AsyncClient(headers={"Authorization": f"ApiKey {api_key}"}, timeout=5.0,
                                        transport=transport)
        self._compliance_cache: dict[tuple, tuple[float, dict, str | None]] = {}  # key -> (when, answer, run id)
        self.rules_elastic = ElasticRules(es, api_key, transport=transport)
        self.rules_local = LocalRules()  # the file copy until the first refresh from Elastic lands
        self._rules_synced_at = float("-inf")
        self._rules_task: asyncio.Task | None = None

    async def aclose(self) -> None:
        if self._rules_task is not None and not self._rules_task.done():
            self._rules_task.cancel()
        await self.client.aclose()
        await self.rules_elastic.aclose()

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

    async def refresh_rules(self) -> int:
        """Pull every stored rule from Elastic into the hub's in-memory copy. Returns how many rules it now has."""
        rules = await self.rules_elastic.fetch_all()
        if rules:
            self.rules_local = LocalRules(rules)
        self._rules_synced_at = time.monotonic()
        return len(rules)

    async def rule_for(self, instruction_text: str, wait_s: float | None = None) -> RuleHit | None:
        """The stored rule for an instruction, answered from the hub's own in-memory copy in microseconds (an
        Elastic call from the hub costs the network round trip: Elastic's own time was 1 ms but the wall time
        about 75 ms). Elastic stays the source of truth: the copy is refreshed from the index in the background
        every UNSTEP_RULES_SYNC_S seconds, so a rule edited in Elastic reaches the hub within that time, with no
        deploy. Prefers a hit that has a paragraph. `wait_s` is kept for callers and no longer used."""
        stale = time.monotonic() - self._rules_synced_at > rules_sync_s()
        if stale and (self._rules_task is None or self._rules_task.done()):
            self._rules_synced_at = time.monotonic()  # one refresh per interval, even if it fails
            self._rules_task = asyncio.create_task(self.refresh_rules())
        hits = self.rules_local.match(instruction_text)
        with_paragraph = [h for h in hits if h.paragraph]
        return (with_paragraph or hits or [None])[0]

    async def paragraph_text(self, paragraph: str) -> str:
        """The paragraph's text from unstep-faa, by id (a lookup, not a search)."""
        try:
            r = await self.client.get(f"{self.es}/{FAA_INDEX}/_doc/{paragraph}")
            if r.status_code == 200:
                return str((r.json().get("_source") or {}).get("body") or "")[:900]
        except (httpx.HTTPError, ValueError):
            pass
        return ""

    async def cite(self, query: str, wait_s: float | None = None) -> dict | None:
        """Closest FAA paragraph by hybrid search (and a rerank), with no language model in the loop, so it can
        answer in the time of a search. Returns {paragraph, title, score, reranked, ms} or None. This is retrieval,
        not a judgment that the paragraph governs the call: the card says "closest rule" and the Compliance agent
        can still replace it later."""
        started = time.perf_counter()
        wait_s = cite_wait_s() if wait_s is None else wait_s
        reranker = rerank_id()
        try:
            async with asyncio.timeout(wait_s):
                for use in ([reranker, None] if reranker else [None]):
                    r = await self.client.post(f"{self.es}/{FAA_INDEX}/_search",
                                               json=faa_search_body(query, use))
                    if r.status_code == 200:
                        hits = r.json().get("hits", {}).get("hits", [])
                        for h in hits:
                            src = h.get("_source") or {}
                            paragraph = str(src.get("paragraph") or h.get("_id") or "")
                            if _PARAGRAPH.match(paragraph):
                                return {"paragraph": paragraph, "title": src.get("title"),
                                        "text": str(src.get("body") or "")[:900],
                                        "score": round(float(h.get("_score") or 0), 3), "reranked": bool(use),
                                        "ms": round((time.perf_counter() - started) * 1000, 1)}
                        return None
                    log.warning("FAA search answered %s%s", r.status_code, " with the reranker" if use else "")
        except (httpx.HTTPError, ValueError, TimeoutError, asyncio.TimeoutError) as exc:
            log.warning("FAA hybrid search failed (%s)", type(exc).__name__)
        return None

    async def _paragraph_exists(self, paragraph: str) -> bool:
        if not _PARAGRAPH.match(paragraph):
            return False
        r = await self.client.get(f"{self.es}/{FAA_INDEX}/_doc/{paragraph}")
        return r.status_code == 200 and bool(r.json().get("found"))

    async def blocked_call(self, event: AnomalyEvent, transcript: TowerTranscript,
                           proposal: ProposedDirective, wait_s: float | None = None,
                           rule: dict | None = None) -> AgentsResult | None:
        """Run the workflow and read the agents' answer back. `wait_s` overrides how long to wait (the late path
        waits longer because nothing is blocked on it)."""
        started = time.perf_counter()
        wait_s = self.wait_s if wait_s is None else wait_s
        if blocked_call_workflow() == BLOCKED_PARALLEL:
            return await self._blocked_parallel(event, transcript, proposal, wait_s, rule, started)
        try:
            inputs = {"event_id": event.event_id, "callsign": event.callsign, "heard_text": event.heard_text,
                      "tower_text": transcript.text, "lost_words": " ".join(proposal.blocked_words),
                      "instruction": proposal.instruction_text}
            workflow = blocked_call_workflow()
            if workflow == BLOCKED_CALL_FAST:  # the one-agent version is given the paragraph already found
                if rule and rule.get("paragraph") and not rule.get("text"):
                    rule = {**rule, "text": await self.paragraph_text(rule["paragraph"])}
                inputs.update({"rule_paragraph": (rule or {}).get("paragraph") or "",
                               "rule_title": (rule or {}).get("title") or "",
                               "rule_text": (rule or {}).get("text") or ""})
            execution_id = await self._run(workflow, inputs)
            doc = await self._wait_doc(PROPOSALS_INDEX, event.event_id, started + wait_s)
            if doc is None:
                log.warning("Elastic workflow for %s took over %.1f s; using the local proposal",
                            event.event_id, wait_s)
                return None
            if doc.get("ground") is not None:  # the one-agent workflow stores both answers in one JSON object
                both = parse_agent_json(doc.get("ground")) or {}
                intercept, compliance = both.get("intercept"), both.get("compliance")
                intercept = intercept if isinstance(intercept, dict) else None
                compliance = compliance if isinstance(compliance, dict) else None
            else:
                intercept, compliance = parse_agent_json(doc.get("intercept")), parse_agent_json(doc.get("compliance"))
            result = AgentsResult(intercept=intercept, compliance=compliance,
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

    def _cached_compliance(self, key: tuple):
        ttl = compliance_cache_ttl_s()
        hit = self._compliance_cache.get(key)
        if ttl > 0 and hit is not None and time.monotonic() - hit[0] < ttl:
            return hit[1], hit[2]
        return None

    def _remember_compliance(self, key: tuple, answer: dict, run_id: str | None) -> None:
        if compliance_cache_ttl_s() > 0 and answer:
            self._compliance_cache[key] = (time.monotonic(), answer, run_id)

    async def _branch(self, workflow: str, doc_id: str, inputs: dict, started: float, wait_s: float):
        """One of the two parallel agents: start its workflow, wait for its own answer document."""
        execution_id = await self._run(workflow, inputs)
        doc = await self._wait_doc(PROPOSALS_INDEX, doc_id, started + wait_s)
        return execution_id, doc, round((time.perf_counter() - started) * 1000, 1)

    async def _blocked_parallel(self, event, transcript, proposal, wait_s, rule, started) -> AgentsResult | None:
        """Intercept and Compliance as two separate single-call workflows started together, so the wait is the
        slower of the two instead of the sum. Each is given what it needs and makes no tool calls: Intercept the
        two transcripts, Compliance the instruction and the paragraph already found. If one fails or is late the
        other's answer is still used (merge handles a missing half)."""
        if rule and rule.get("paragraph") and not rule.get("text"):
            rule = {**rule, "text": await self.paragraph_text(rule["paragraph"])}
        rule = rule or {}
        intercept_in = {"event_id": event.event_id, "callsign": event.callsign, "heard_text": event.heard_text,
                        "tower_text": transcript.text, "lost_words": " ".join(proposal.blocked_words)}
        compliance_in = {"event_id": event.event_id, "callsign": event.callsign,
                         "instruction": proposal.instruction_text, "rule_paragraph": rule.get("paragraph") or "",
                         "rule_title": rule.get("title") or "", "rule_text": rule.get("text") or ""}
        mode = intercept_mode()
        skip_intercept = mode == "never" or (mode == "auto" and proposal.confidence == "high")
        cache_key = (proposal.slots.action, proposal.slots.runway, rule.get("paragraph") or "")
        cached = self._cached_compliance(cache_key) if rule.get("paragraph") else None
        tasks, names = [], []
        if not skip_intercept:
            tasks.append(self._branch(INTERCEPT_WORKFLOW, f"{event.event_id}:intercept", intercept_in, started, wait_s))
            names.append("intercept")
        if cached is None:
            tasks.append(self._branch(COMPLIANCE_WORKFLOW, f"{event.event_id}:compliance", compliance_in, started,
                                      wait_s))
            names.append("compliance")
        try:
            got = await asyncio.gather(*tasks, return_exceptions=True)
        except (httpx.HTTPError, ValueError):
            return None
        parts = {}
        if cached is not None:  # the same instruction against the same paragraph was judged before
            parts["compliance"] = (cached[0], cached[1], 0.0)
        for name, outcome in zip(names, got):
            if isinstance(outcome, Exception):
                log.warning("Elastic %s agent for %s failed (%s)", name, event.event_id, type(outcome).__name__)
                continue
            execution_id, doc, ms = outcome
            if doc is not None:
                parts[name] = (parse_agent_json(doc.get(name)), execution_id, ms)
        if not parts:
            log.warning("Neither parallel Elastic agent answered %s within %.1f s; using the local proposal",
                        event.event_id, wait_s)
            return None
        result = AgentsResult(intercept=(parts.get("intercept") or (None,))[0],
                              compliance=(parts.get("compliance") or (None,))[0],
                              execution_id=next((p[1] for p in parts.values() if p[1]), None),
                              branches={k: v[2] for k, v in parts.items()})
        if skip_intercept:
            result.notes.append("Intercept agent skipped: the local match was already high confidence")
        if cached is not None:
            result.notes.append("Compliance answer reused from an earlier identical instruction")
        paragraph = str((result.compliance or {}).get("paragraph") or "")
        if paragraph:
            result.citation_checked = await self._paragraph_exists(paragraph)
            if cached is None and result.citation_checked and paragraph == rule.get("paragraph"):
                self._remember_compliance(cache_key, result.compliance, parts["compliance"][1])
        result.took_ms = round((time.perf_counter() - started) * 1000, 1)
        return result

    async def readback_audit(self, event_id: str, instruction: str, readback: str, attempt: int) -> str | None:
        """Start the Readback Auditor; it stores its finding in unstep-findings. Never waits on it."""
        try:
            return await self._run(READBACK_AUDIT_WORKFLOW, {"event_id": event_id, "instruction": instruction,
                                                             "readback": readback, "attempt": attempt})
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("readback audit for %s not started (%s)", event_id, type(exc).__name__)
            return None


def rules_sync_s() -> float:
    """How often the hub refreshes its in-memory copy of the stored rules from Elastic (UNSTEP_RULES_SYNC_S, 30)."""
    try:
        return max(1.0, float(env("UNSTEP_RULES_SYNC_S", default="30")))
    except ValueError:
        return 30.0


def with_stored_rule(proposal: ProposedDirective, hit: RuleHit | None) -> ProposedDirective:
    """Put the stored rule's paragraph on the card at once. Wording depends on whether a person reviewed it."""
    text = describe(hit)
    if text is None or proposal.rule_citation and "TBD" not in proposal.rule_citation:
        return proposal
    return proposal.model_copy(update={
        "rule_citation": text,
        "confidence_method": (proposal.confidence_method or "") + f" + stored rule ({hit.backend})"})


def intercept_mode() -> str:
    """When the hub asks the Intercept agent (UNSTEP_INTERCEPT): `auto` (default) only when the local match is not
    already high confidence, `always`, or `never`. Live, Intercept is the slow half (10.7 to 22.6 s, R47) and its
    answer repeats what the local transcript match already decided when confidence is high."""
    mode = env("UNSTEP_INTERCEPT", default="auto").lower()
    return mode if mode in ("auto", "always", "never") else "auto"


def compliance_cache_ttl_s() -> float:
    """How long a Compliance answer is reused for the same instruction and paragraph (UNSTEP_COMPLIANCE_CACHE_S,
    default 0 = off: real questions differ, and a hit would skip the agent)."""
    try:
        return max(0.0, float(env("UNSTEP_COMPLIANCE_CACHE_S", default="0")))
    except ValueError:
        return 0.0


def blocked_call_workflow() -> str:
    """Which workflow the hub starts for a stepped-on call (UNSTEP_BLOCKED_WORKFLOW). The default is the parallel
    pair: live, one call took 12.2 s that way against 23.4 s and 33.8 s for the original two-agent workflow
    (Rishit's run, R47). `unstep-blocked-call` is the original, `unstep-blocked-call-fast` the one-agent version
    (16.2 s live)."""
    name = env("UNSTEP_BLOCKED_WORKFLOW", default=BLOCKED_PARALLEL)
    return name if name in (BLOCKED_CALL_WORKFLOW, BLOCKED_CALL_FAST, BLOCKED_PARALLEL) else BLOCKED_PARALLEL


def rerank_id() -> str | None:
    """The rerank endpoint for the FAA search (UNSTEP_RERANK_ID, default Jina's v3 reranker, which Rishit listed on
    the live project). Set it empty to skip reranking."""
    value = env("UNSTEP_RERANK_ID", default=".jina-reranker-v3")
    return value or None


def cite_wait_s() -> float:
    try:
        return max(0.2, float(env("UNSTEP_CITE_WAIT_S", default="1.5")))
    except ValueError:
        return 1.5


def faa_search_body(query: str, reranker: str | None, size: int = 3) -> dict:
    """Hybrid search of the FAA order: keyword and semantic results fused with RRF, then (optionally) re-ordered by a
    cross-encoder. The same pattern as Elastic's Cal Hacks workshop repo; the fields are ours (`text` is the
    semantic_text field, `body` the plain text copy, see scripts/ingest_faa.py)."""
    rrf = {"rrf": {"retrievers": [
        {"standard": {"query": {"multi_match": {"query": query, "fields": ["title^2", "body"]}}}},
        {"standard": {"query": {"semantic": {"field": "text", "query": query}}}}],
        "rank_window_size": 20}}
    retriever = rrf if not reranker else {"text_similarity_reranker": {
        "retriever": rrf, "field": "body", "inference_id": reranker, "inference_text": query,
        "rank_window_size": 10}}
    return {"retriever": retriever, "size": size, "_source": ["paragraph", "title", "chapter", "body"]}


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
