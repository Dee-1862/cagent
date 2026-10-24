"""Presenter contracts and real offline pipeline. No sockets or vendor calls needed."""
import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from unstep import scenario
from unstep.contracts import ApprovedDirective, ReadbackResult, wrap
from unstep.demo.presenter import Presenter, create_demo_app, statistics
from unstep.gateway.server import Gateway
from unstep.gateway.sink import MemorySink


async def finish(presenter):
    task = presenter.task
    if task:
        await asyncio.wait_for(task, 30)
    assert "failed" not in presenter.status, presenter.status


def test_scene_transitions_and_no_duplicate_work(tmp_path):
    async def run():
        p = Presenter(Gateway(MemorySink()), audio_dir=tmp_path, realtime=False)
        calls = []

        async def scene(number):
            calls.append(number)
            p.completed = number
            p.task = None

        p.run_scene = scene
        assert p.scene == 0
        await p.control("next")
        await finish(p)
        assert p.scene == 1
        await p.control("next")
        await finish(p)
        await p.control("prev")
        assert p.scene == 1
        await p.control("next")
        assert p.scene == 2 and calls == [1, 2]
        await p.control("mode")
        assert not p.audio_mode
        await p.control("replay")
        assert calls == [1, 2]
        await p.control("reset")
        await finish(p)
        assert p.scene == 1 and p.generation == 1 and p.audio_mode
        assert calls == [1, 2, 1]
        await p.stop()

    asyncio.run(run())


def test_busy_scene_does_not_skip_and_reset_cancels(tmp_path):
    async def run():
        p = Presenter(Gateway(MemorySink()), audio_dir=tmp_path)
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def scene(number):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        p.run_scene = scene
        await p.control("next")
        await started.wait()
        with pytest.raises(HTTPException) as error:
            await p.control("next")
        assert error.value.status_code == 409 and p.scene == 1
        await p.control("reset")
        assert cancelled.is_set()
        await p.stop()

    asyncio.run(run())


def test_routes_assets_events_and_gateway_counts(tmp_path, monkeypatch):
    monkeypatch.setattr("unstep.demo.presenter.elastic_settings", lambda: None)
    app = create_demo_app(audio_dir=tmp_path, realtime=False)
    gw = app.state.gateway
    approved = ApprovedDirective(event_id="evt", instruction_text="Hold short runway 33",
        slots=scenario.SLOTS, approved_by="controller", approved_via="voice")
    for msg in [scenario.anomaly_event(), approved,
                ReadbackResult(event_id="evt", readback_text="runway 23", match=False),
                ReadbackResult(event_id="evt", readback_text="runway 33", match=True)]:
        gw.history.append(wrap(msg))
    with TestClient(app) as client:
        for path, content in [("/demo/", "demo.js"), ("/demo/demo.js", "decodeAudioData"),
                              ("/demo/demo.css", "#0A0E13")]:
            response = client.get(path)
            assert response.status_code == 200 and content in response.text
        result = client.get("/demo/stats").json()
        assert result["source"] == "gateway" and "STATS" in result["esql"]
        assert {row["type"]: row["count"] for row in result["rows"]} == {
            "AnomalyEvent": 1, "ApprovedDirective": 1, "ReadbackResult": 1}
        assert next(row for row in result["rows"] if row["type"] == "ApprovedDirective")["approved_via"] == "voice"
        assert client.post("/demo/control", json={"action": "unknown"}).status_code == 422
        assert client.post("/demo/control", json={"action": "next"},
                           headers={"Origin": "https://untrusted.example"}).status_code == 403
        with client.websocket_connect("/demo/events") as ws:
            assert ws.receive_json()["type"] == "DemoScene"
            result = client.post("/demo/control", json={"action": "mode"})
            assert result.status_code == 200
            assert ws.receive_json()["audio_mode"] is False
        assert client.get("/demo/audio/missing.wav").status_code == 404


def test_offline_all_scenes_real_pipeline_without_network(tmp_path, monkeypatch):
    # Fail immediately if offline mode accidentally selects a network client.
    async def forbidden(*args, **kwargs):
        raise AssertionError("offline demo attempted network access")

    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    monkeypatch.setattr("websockets.connect", forbidden)
    monkeypatch.setattr("unstep.demo.presenter.create_memory", lambda: pytest.fail("cloud memory selected"))

    async def run():
        # Missing real directory exercises explicit fallback to synthetic fixture clips.
        app = create_demo_app(audio_dir=tmp_path / "audio", clips=tmp_path / "missing", realtime=False)
        p = app.state.presenter
        try:
            for number in range(1, 8):
                await p.control("next")
                await finish(p)
                assert p.scene == number
                records = [json.loads(raw) for raw in p.gateway.history]
                types = [record["type"] for record in records]
                if number == 1:
                    assert "ProposedDirective" in types and "VoiceApproval" not in types
                if number == 2:
                    assert "ApprovedDirective" in types and "ReadbackResult" not in types
                if number == 3:
                    assert types.count("ReadbackResult") == 2 and "PilotQuery" not in types
            expected = ["AnomalyEvent", "ProposedDirective", "VoiceApproval", "ApprovedDirective",
                        "ReadbackResult", "ReadbackResult", "PilotQuery", "PilotQuery"]
            assert [kind for kind in types if kind in set(expected)] == expected
            assert [r["data"]["match"] for r in records if r["type"] == "ReadbackResult"] == [False, True]
            assert any("missing" in reason for reason in p.fallbacks)
            audio = [r["data"]["payload"]["audio_url"] for r in records
                     if r["type"] == "AuditRecord" and r["data"]["payload"].get("audio_url")]
            assert audio and all((p.audio_dir / url.split("/")[-1]).is_file() for url in audio)
            assert p.monitor.rules.events
            result = await statistics(p.gateway, elastic=False)
            assert result["source"] == "gateway"
        finally:
            await p.stop()

    asyncio.run(run())


def test_elastic_query_uses_promoted_fields_and_does_not_hide_failure(monkeypatch):
    monkeypatch.setattr("unstep.demo.presenter.elastic_settings", lambda: ("https://elastic.invalid", "test-key"))
    captured = []

    async def post(self, url, **kwargs):
        captured.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "columns": [{"name": "count"}, {"name": "type"}, {"name": "approved_via"}],
            "values": [[2, "ApprovedDirective", "voice"]]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    result = asyncio.run(statistics(Gateway(MemorySink())))
    assert result["source"] == "elastic" and result["rows"][0]["count"] == 2
    assert captured[0][0].endswith("/_query")
    assert "BY type, approved_via" in captured[0][1]["json"]["query"]

    async def fail(*args, **kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail)
    with pytest.raises(HTTPException) as error:
        asyncio.run(statistics(Gateway(MemorySink())))
    assert error.value.status_code == 502


def test_rejection_is_not_counted_as_an_approved_scene(monkeypatch):
    import asyncio
    from unstep.demo.presenter import create_demo_app
    from unstep.ground import voice_approval

    monkeypatch.setattr(voice_approval.ApprovalLoop, "classify", staticmethod(lambda text: "reject"))
    app = create_demo_app(live=False)
    presenter = app.state.presenter
    presenter.realtime = False

    async def go():
        await presenter.run_scene(1)
        await presenter.run_scene(2)
        await presenter.stop()

    asyncio.run(go())
    assert presenter.completed == 1
    assert "rejected" in presenter.status.lower() or "failed" in presenter.status.lower()
