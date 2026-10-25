"""Scheduled workflows, the coach agent, the trend tool and the MCP client. Definitions are checked as files; MCP is mocked."""

import asyncio
import json
from pathlib import Path

import httpx
import yaml

from scripts.mcp_demo import McpClient, parse_reply
from scripts import deploy_elastic

ROOT = Path(__file__).resolve().parent.parent
EL = ROOT / "elastic"


def test_scheduled_triggers_use_the_documented_shape():
    for name, every in (("unstep-nightly-review", "1d"), ("unstep-briefing", "8h")):
        wf = yaml.safe_load((EL / "workflows" / f"{name}.yaml").read_text())
        sched = [t for t in wf["triggers"] if t["type"] == "scheduled"]
        assert sched == [{"type": "scheduled", "with": {"every": every}}]
        assert any(t["type"] == "manual" for t in wf["triggers"])  # can still be run by hand


def test_nightly_review_calls_the_coach_and_saves_to_an_index_the_deploy_creates():
    wf = yaml.safe_load((EL / "workflows" / "unstep-nightly-review.yaml").read_text())
    steps = {s["name"]: s for s in wf["steps"]}
    assert steps["review"]["agent-id"] == "unstep-coach"
    assert steps["save_review"]["with"]["index"] == "unstep-reviews" in deploy_elastic.INDEXES


def test_coach_is_read_only_and_never_claims_learning():
    agent = json.loads((EL / "agents" / "unstep-coach.json").read_text())["configuration"]
    tools = {t for g in agent["tools"] for t in g["tool_ids"]}
    assert tools == {"unstep_trend_decisions", "unstep_faa_search"}
    assert (EL / "tools" / "unstep_trend_decisions.json").exists()
    assert "Never say the system learned" in agent["instructions"] and "not enough data" in agent["instructions"]


def test_trend_tool_reads_real_traffic_only():
    q = json.loads((EL / "tools" / "unstep_trend_decisions.json").read_text())["configuration"]["query"]
    assert q.startswith("FROM unstep-events") and "sim" not in q and "30 days" in q
    assert not any(w in q.upper() for w in (" DELETE", "INSERT", "UPDATE"))


def test_unverified_workflow_tool_is_not_deployed():
    assert (EL / "proposed" / "unstep_run_briefing.json").exists()
    assert "unstep_run_briefing" not in {t["id"] for t in deploy_elastic.load_definitions()["tools"]}


def test_parse_reply_reads_json_and_event_streams():
    assert parse_reply(httpx.Response(200, text='{"id": 1}')) == {"id": 1}
    assert parse_reply(httpx.Response(200, text='event: message\ndata: {"id": 2}\n\n')) == {"id": 2}
    assert parse_reply(httpx.Response(200, text="")) == {}


def test_mcp_client_initialises_then_lists_and_calls():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append((request.url.path, body["method"], request.headers.get("Mcp-Session-Id")))
        if body["method"] == "tools/list":
            return httpx.Response(200, json={"id": body["id"], "result": {"tools": [{"name": "unstep_trend_decisions"}]}})
        if body["method"] == "initialize":
            return httpx.Response(200, json={"id": body["id"], "result": {}}, headers={"Mcp-Session-Id": "s1"})
        return httpx.Response(200, json={"id": body.get("id"), "result": {"content": []}})

    async def go():
        c = McpClient("https://kb.example", "key", transport=httpx.MockTransport(handler))
        await c.start()
        tools = await c.tools()
        await c.call("unstep_trend_decisions")
        await c.close()
        return tools

    assert asyncio.run(go()) == [{"name": "unstep_trend_decisions"}]
    assert [m for _, m, _ in seen] == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
    assert all(p == "/api/agent_builder/mcp" for p, _, _ in seen) and seen[-1][2] == "s1"


def test_maps_only_deploy_touches_no_agent_tool_or_workflow():
    steps = deploy_elastic.map_steps()
    labels = [s[0] for s in steps]
    assert labels == ["data view unstep-airport", "data view unstep-positions", "map unstep-airport-map"]
    assert all(not l.startswith(("tool", "agent", "workflows")) for l in labels)
    saved = steps[-1][3]["attributes"]
    layers = json.loads(saved["layerListJSON"])
    assert {l["sourceDescriptor"]["indexPatternId"] for l in layers} == set(deploy_elastic.MAP_VIEWS)
    assert {l["sourceDescriptor"]["geoField"] for l in layers} == {"area", "location"}
    assert json.loads(saved["mapStateJSON"])["refreshConfig"]["interval"] == 1000
