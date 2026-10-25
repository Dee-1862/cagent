"""B5: Elastic Workflow ground agents. Kibana and Elasticsearch are mocked; definitions are checked offline."""

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
import yaml

from unstep import scenario
from unstep.contracts import AuditRecord, ProposedDirective
from unstep.ground import elastic_agents as ea
from unstep.ground.mock_agents import propose
from unstep.live.room import GroundAgents

ROOT = Path(__file__).resolve().parent.parent
DEFS = ROOT / "elastic"


def test_parse_agent_json_takes_the_first_object():
    assert ea.parse_agent_json('Sure! {"match": true, "x": {"y": 1}} done') == {"match": True, "x": {"y": 1}}
    assert ea.parse_agent_json('{bad} then {"ok": 1}') == {"ok": 1}
    assert ea.parse_agent_json("no json") is None and ea.parse_agent_json(None) is None
    assert ea.parse_agent_json({"a": 1}) == {"a": 1}


def base_proposal() -> ProposedDirective:
    return propose(scenario.anomaly_event(), scenario.tower_transcript())


def test_merge_adds_a_checked_citation_and_never_raises_confidence():
    p = base_proposal()
    good = ea.AgentsResult(intercept={"match": True},
                           compliance={"paragraph": "3-7-2", "title": "Taxi and Ground Movement Operations",
                                       "restrictive": True, "confidence": "high"}, citation_checked=True)
    m = ea.merge(p, good)
    assert m.rule_citation == "FAA JO 7110.65, paragraph 3-7-2 (Taxi and Ground Movement Operations)"
    assert m.confidence == p.confidence and m.instruction_text == p.instruction_text and m.slots == p.slots
    assert "Elastic agents" in m.confidence_method
    unchecked = ea.merge(p, ea.AgentsResult(intercept={"match": True}, compliance={"paragraph": "9-9-9"},
                                            citation_checked=False))
    assert unchecked.rule_citation is None and "not found" in unchecked.confidence_method
    no_match = ea.merge(p, ea.AgentsResult(intercept={"match": False}, compliance=None))
    assert no_match.confidence == "low" and "no match" in no_match.confidence_method
    not_restrictive = ea.merge(p, ea.AgentsResult(intercept={"match": True}, compliance={"restrictive": False}))
    assert not_restrictive.confidence == "low"
    assert ea.merge(p, None) is p


def kibana_and_es(found_after=1, faa_found=True, fail_run=False, seen=None):
    seen = [] if seen is None else seen
    polls = {"n": 0}

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.host, request.url.path))
        if request.url.path.startswith("/api/workflows/workflow/"):
            if fail_run:
                return httpx.Response(500)
            assert request.headers["kbn-xsrf"] == "true"
            return httpx.Response(200, json={"workflowExecutionId": "exec-1"})
        if request.url.path.startswith("/unstep-proposals/_doc/"):
            polls["n"] += 1
            if polls["n"] <= found_after:
                return httpx.Response(404, json={"found": False})
            return httpx.Response(200, json={"found": True, "_source": {
                "intercept": 'Here you go: {"match": true, "lost_words": "hold short", "explanation": "x"}',
                "compliance": '{"paragraph": "3-7-2", "title": "Taxi", "restrictive": true}'}})
        if request.url.path.startswith("/unstep-faa/_doc/"):
            return httpx.Response(200 if faa_found else 404, json={"found": faa_found})
        return httpx.Response(404)

    return httpx.MockTransport(handler), seen


def agents(transport, wait_s=2.0):
    return ea.ElasticAgents("https://kb.example", "https://es.example", "key", wait_s=wait_s, poll_s=0.01,
                            transport=transport)


def test_blocked_call_runs_the_workflow_and_reads_the_answer_back():
    transport, seen = kibana_and_es(found_after=2)
    result = asyncio.run(agents(transport).blocked_call(scenario.anomaly_event(), scenario.tower_transcript(),
                                                        base_proposal()))
    assert result.execution_id == "exec-1" and result.intercept["match"] is True
    assert result.compliance["paragraph"] == "3-7-2" and result.citation_checked is True
    assert ("POST", "kb.example", "/api/workflows/workflow/unstep-blocked-call/run") in seen
    assert ("GET", "es.example", "/unstep-faa/_doc/3-7-2") in seen


def test_slow_or_failing_workflow_keeps_the_local_proposal():
    slow, _ = kibana_and_es(found_after=10_000)
    assert asyncio.run(agents(slow, wait_s=0.05).blocked_call(
        scenario.anomaly_event(), scenario.tower_transcript(), base_proposal())) is None
    broken, _ = kibana_and_es(fail_run=True)
    assert asyncio.run(agents(broken).blocked_call(
        scenario.anomaly_event(), scenario.tower_transcript(), base_proposal())) is None


def test_ground_agents_use_elastic_when_configured():
    transport, _ = kibana_and_es(found_after=0)
    sent = []

    async def send(m):
        sent.append(m)

    async def go():
        g = GroundAgents(send, wait_s=1.0, elastic=agents(transport))
        await g.on_message(scenario.tower_transcript())
        await g.on_message(scenario.anomaly_event())
        while len(sent) < 2:
            await asyncio.sleep(0.01)

    asyncio.run(go())
    proposal, audit = sent
    assert proposal.rule_citation.startswith("FAA JO 7110.65, paragraph 3-7-2")
    assert isinstance(audit, AuditRecord) and audit.payload["agents"] == "Elastic Workflow unstep-blocked-call"
    assert audit.payload["workflow_execution_id"] == "exec-1"


def test_off_unless_opted_in(monkeypatch):
    monkeypatch.delenv("UNSTEP_ELASTIC_AGENTS", raising=False)
    assert ea.elastic_agents_from_env() is None
    monkeypatch.setenv("UNSTEP_ELASTIC_AGENTS", "1")
    monkeypatch.setattr(ea, "elastic_settings", lambda: None)
    assert ea.elastic_agents_from_env() is None


def test_definitions_are_consistent():
    tools = {json.loads(p.read_text())["id"] for p in (DEFS / "tools").glob("*.json")}
    agent_ids = set()
    for p in (DEFS / "agents").glob("*.json"):
        a = json.loads(p.read_text())
        agent_ids.add(a["id"])
        assert a["configuration"]["instructions"]
        for group in a["configuration"]["tools"]:
            assert set(group["tool_ids"]) <= tools, (a["id"], group)
            for t in group["tool_ids"]:
                assert t in a["configuration"]["instructions"]  # the agent is told when to use each tool
    for p in (DEFS / "workflows").glob("*.yaml"):
        wf = yaml.safe_load(p.read_text())
        assert wf["name"] == p.stem and wf["triggers"][0]["type"] == "manual"
        inputs = {i["name"] for i in wf["triggers"][0]["inputs"]}
        for step in wf["steps"]:
            if step["type"] == "ai.agent":
                assert step["agent-id"] in agent_ids
            for used in re.findall(r"inputs\.(\w+)", json.dumps(step)):
                assert used in inputs, (p.stem, used)
    blocked = yaml.safe_load((DEFS / "workflows" / "unstep-blocked-call.yaml").read_text())
    sent = set(json.loads(json.dumps({"event_id": 1, "callsign": 1, "heard_text": 1, "tower_text": 1,
                                      "lost_words": 1, "instruction": 1})))
    assert {i["name"] for i in blocked["triggers"][0]["inputs"]} == sent  # what blocked_call() sends
    for name, extra in (("unstep-blocked-intercept", {"heard_text", "tower_text", "lost_words"}),
                        ("unstep-blocked-compliance", {"instruction", "rule_paragraph", "rule_title", "rule_text"})):
        half = yaml.safe_load((DEFS / "workflows" / f"{name}.yaml").read_text())
        assert {i["name"] for i in half["triggers"][0]["inputs"]} == {"event_id", "callsign"} | extra
    fast = yaml.safe_load((DEFS / "workflows" / "unstep-blocked-call-fast.yaml").read_text())
    assert {i["name"] for i in fast["triggers"][0]["inputs"]} == sent | {"rule_paragraph", "rule_title", "rule_text"}


def test_deploy_dry_run_lists_every_object():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "deploy_elastic.py"), "--dry-run"],
                         capture_output=True, text=True, check=True).stdout
    for name in ("unstep-proposals", "unstep_faa_search", "unstep-intercept", "unstep-compliance",
                 "unstep-readback-auditor", "unstep-blocked-call", "unstep-readback-audit"):
        assert name in out
