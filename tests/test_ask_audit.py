"""E-2: ask the audit trail. Kibana is mocked; the agent and tools are checked as definitions."""

import asyncio
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from unstep.ground import audit_chat as ac
from unstep.live.app import create_live_app

from tests.test_live_join import room as make_join_room

ROOT = Path(__file__).resolve().parent.parent
GUESS = {"conversation_id": "c1", "steps": [{"type": "tool_call", "tool_id": "unstep_audit_blocked_by_callsign",
                                             "params": {"query": "FROM unstep-events | STATS blocked = COUNT(*) BY callsign"}}],
         "response": {"message": "N123AB was blocked 4 times, more than any other plane."}}


def chat(handler, **kw):
    return ac.AuditChat("https://kb.example", "key", transport=httpx.MockTransport(handler), **kw)


def test_parse_converse_is_tolerant_about_the_layout():
    p = ac.parse_converse(GUESS)
    assert p["answer"].startswith("N123AB was blocked") and p["esql"] == ["FROM unstep-events | STATS blocked = COUNT(*) BY callsign"]
    assert p["tools"] == ["unstep_audit_blocked_by_callsign"]
    assert ac.parse_converse({"message": "plain"})["answer"] == "plain"
    assert ac.parse_converse("nonsense") == {"answer": None, "esql": [], "tools": []}


def test_ask_posts_the_question_to_the_audit_agent_and_returns_the_query():
    seen = []

    def handler(request):
        seen.append((request.url.path, request.headers["kbn-xsrf"], json.loads(request.content)))
        return httpx.Response(200, json=GUESS)

    out = asyncio.run(chat(handler).ask("  Which plane   was blocked most? "))
    assert out["ok"] and out["took_ms"] >= 0 and out["agent"] == "unstep-audit"
    assert seen == [("/api/agent_builder/converse", "true", {"input": "Which plane was blocked most?", "agent_id": "unstep-audit"})]


def test_failures_and_limits_never_raise():
    boom = lambda r: httpx.Response(500)  # noqa: E731
    assert asyncio.run(chat(boom).ask("anything"))["ok"] is False
    assert asyncio.run(chat(boom).ask("   "))["error"].startswith("Ask a question")
    empty = asyncio.run(chat(lambda r: httpx.Response(200, json={"steps": []})).ask("x"))
    assert empty["ok"] is False and "without text" in empty["error"]

    async def twice():
        c = chat(lambda r: httpx.Response(200, json=GUESS))
        first = await c.ask("one")
        second = await c.ask("two")  # inside the minimum gap
        return first["ok"], second["ok"], second["error"]

    assert asyncio.run(twice()) == (True, False, "One question at a time. Try again in a moment.")
    long = asyncio.run(chat(lambda r: (httpx.Response(200, json=GUESS))).ask("x" * 1000))
    assert long["ok"]


def test_route_is_off_without_elastic_and_works_with_it(monkeypatch):
    r = make_join_room(monkeypatch)
    with TestClient(create_live_app(live=False, room=r)) as client:
        client.app.state.audit_chat = None
        assert client.get("/live/ask-audit").json()["available"] is False
        body = client.post("/live/ask-audit", json={"question": "hi"}).json()
        assert body["ok"] is False and body["available"] is False
        client.app.state.audit_chat = chat(lambda req: httpx.Response(200, json=GUESS))
        assert client.get("/live/ask-audit").json()["available"] is True
        ok = client.post("/live/ask-audit", json={"question": "Which plane?"}).json()
        assert ok["ok"] and ok["esql"] and ok["answer"].startswith("N123AB")
        assert client.post("/live/ask-audit", content=b"not json").json()["ok"] is False


def test_agent_and_tools_are_read_only_esql_over_real_traffic_only():
    tools = {json.loads(p.read_text())["id"]: json.loads(p.read_text()) for p in (ROOT / "elastic" / "tools").glob("unstep_audit_*.json")}
    assert len(tools) == 4
    for t in tools.values():
        q = t["configuration"]["query"]
        assert t["type"] == "esql" and q.startswith("FROM unstep-events") and "sim" not in q  # never the simulated index
        assert "NOW() - 60 minutes" in q and not any(w in q.upper() for w in (" DELETE", "INSERT", "UPDATE"))
    agent = json.loads((ROOT / "elastic" / "agents" / "unstep-audit.json").read_text())
    assert set(agent["configuration"]["tools"][0]["tool_ids"]) == set(tools)
    assert "never guess" in agent["configuration"]["instructions"] and "cannot see live radio" in agent["configuration"]["instructions"]


def test_parse_converse_repairs_utf8_read_as_cp1252():
    from unstep.ground.audit_chat import parse_converse

    broken = "Cessna 123 — four blocked calls".encode("utf-8").decode("cp1252")
    assert parse_converse({"response": {"message": broken}})["answer"] == "Cessna 123 — four blocked calls"
    assert parse_converse({"response": {"message": "plain text"}})["answer"] == "plain text"
