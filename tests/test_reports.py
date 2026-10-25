import asyncio

import httpx
from fastapi.testclient import TestClient

from unstep.ground import audit_chat as ac
from unstep.ground.reports import Reports
from unstep.live.app import create_live_app

from tests.test_live_join import room as make_room


def reports(handler):
    return Reports("https://es.example", "https://kb.example", "key", transport=httpx.MockTransport(handler))


def test_latest_reads_the_newest_document_of_each_index():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        index = request.url.path.split("/")[1]
        field = "briefing" if index == "unstep-briefings" else "review"
        return httpx.Response(200, json={"hits": {"hits": [{"_source": {field: f"text from {index}", "@timestamp": "2026-10-25T08:00:00Z"}}]}})

    out = asyncio.run(reports(handler).latest())
    assert out["briefing"]["text"] == "text from unstep-briefings" and out["review"]["text"] == "text from unstep-reviews"
    assert seen == ["/unstep-briefings/_search", "/unstep-reviews/_search"]


def test_latest_is_none_when_empty_or_failing():
    out = asyncio.run(reports(lambda r: httpx.Response(404)).latest())
    assert out == {"briefing": None, "review": None}


def test_run_starts_the_workflow_once_in_a_while():
    posted = []

    def handler(request):
        posted.append(request.url.path)
        return httpx.Response(200, json={})

    async def go():
        r = reports(handler)
        return await r.run("review"), await r.run("briefing"), await reports(handler).run("nonsense")

    first, second, bad = asyncio.run(go())
    assert first["ok"] and posted == ["/api/workflows/workflow/unstep-nightly-review/run"]
    assert second["ok"] is False and bad["error"] == "Unknown report."


def test_routes_and_the_coach_can_be_asked(monkeypatch):
    r = make_room(monkeypatch)
    asked = []

    def converse(request):
        import json
        asked.append(json.loads(request.content)["agent_id"])
        return httpx.Response(200, json={"response": {"message": "Not enough data to see a trend."}})

    with TestClient(create_live_app(live=False, room=r)) as client:
        client.app.state.audit_chat = ac.AuditChat("https://kb.example", "key", transport=httpx.MockTransport(converse))
        client.app.state.reports = reports(lambda req: httpx.Response(200, json={"hits": {"hits": []}}))
        assert client.get("/live/ask-audit").json()["agents"] == ["audit", "coach"]
        body = client.post("/live/ask-audit", json={"question": "Trend?", "agent": "coach"}).json()
        assert body["ok"] and body["agent"] == "unstep-coach" and asked == ["unstep-coach"]
        assert client.get("/live/reports").json() == {"available": True, "briefing": None, "review": None}
        client.app.state.reports = None
        assert client.get("/live/reports").json() == {"available": False}
        assert client.post("/live/reports/run").json()["available"] is False
