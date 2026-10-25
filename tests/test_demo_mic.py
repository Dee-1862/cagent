"""Presenter --mic mode, offline: fake STT, synthetic PCM, no sockets to vendors."""
import asyncio
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from unstep.cockpit.stt import FakeManualSTT
from unstep.demo.presenter import create_demo_app


def tone_frames(seconds=0.5):
    t = np.arange(int(16000 * seconds)) / 16000
    pcm = (0.2 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2").tobytes()
    return [pcm[i:i + 3200] for i in range(0, len(pcm), 3200)]  # 100 ms frames


def scripted(*texts):
    """A fake mic STT factory: each utterance gets the next scripted transcript."""
    queue = list(texts)
    return lambda: FakeManualSTT([queue.pop(0) if queue else ""])


async def speak(mic, times=1):
    """Act as the browser: wait for each prompt, stream frames, release V.

    Counts prompts instead of polling `mic.waiting` for False: with instant fakes the scene finishes one turn and
    asks the next in the same event-loop pass, so a poll can never see `waiting` drop and the helper used to wait
    forever for a prompt it had already missed (it only passed where timers are slow, such as Windows)."""
    prompts = {"n": 1 if mic.waiting else 0}
    real_expect = mic.expect

    async def counted(role, hint):
        prompts["n"] += 1
        await real_expect(role, hint)

    mic.expect = counted
    try:
        for i in range(1, times + 1):
            while prompts["n"] < i:
                await asyncio.sleep(0.005)
            for frame in tone_frames():
                mic.feed(frame)
            mic.end()
    finally:
        mic.expect = real_expect


def records(presenter):
    return [json.loads(raw) for raw in presenter.gateway.history]


def audits(presenter, stage):
    return [r["data"]["payload"] for r in records(presenter)
            if r["type"] == "AuditRecord" and r["data"]["stage"] == stage]


def app_with_mic(tmp_path, stt_factory, **options):
    return create_demo_app(audio_dir=tmp_path / "audio", realtime=False, mic=True,
                           mic_stt_factory=stt_factory, **options)


def test_mic_socket_is_local_and_same_origin_only(tmp_path, monkeypatch):
    with TestClient(app_with_mic(tmp_path, scripted("Approve"))) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/demo/mic", headers={"origin": "https://untrusted.example"}) as ws:
                ws.receive_text()
        assert error.value.code == 4003
        with pytest.raises(Exception):
            with client.websocket_connect("/demo/mic", headers={"host": "evil.example:8765"}) as ws:
                ws.receive_text()
        monkeypatch.setattr("unstep.demo.presenter.LOOPBACK", set())
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/demo/mic") as ws:
                ws.receive_text()
        assert error.value.code == 4003
    # Without --mic there is no mic socket at all.
    with TestClient(create_demo_app(audio_dir=tmp_path / "plain")) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/demo/mic") as ws:
                ws.receive_text()


def test_mic_socket_streams_frames_only_while_waiting(tmp_path):
    app = app_with_mic(tmp_path, scripted("Approve"))
    mic = app.state.presenter.mic
    with TestClient(app) as client:
        with client.websocket_connect("/demo/mic") as ws:
            ws.send_bytes(b"\x01\x00" * 1600)  # not waiting: dropped
            ws.send_text(json.dumps({"type": "end"}))
            mic.waiting = True
            ws.send_bytes(b"\x01\x00" * 1600)
            ws.send_text(json.dumps({"type": "end"}))
        deadline = time.monotonic() + 2
        while mic.utterances.qsize() < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
    assert mic.utterances.qsize() == 1
    frames = mic.utterances.get_nowait().frames
    assert frames.get_nowait() == b"\x01\x00" * 1600 and frames.get_nowait() is None


def test_live_controller_utterance_approves_and_is_not_labeled_recorded(tmp_path):
    async def run():
        app = app_with_mic(tmp_path, scripted("Approve"), clips=tmp_path / "missing")
        p = app.state.presenter
        try:
            await p.run_scene(1)
            assert p.state()["mic"] == {"enabled": True, "waiting": False, "role": None, "hint": "",
                                        "status": "", "transcript": ""}
            prompts = []
            p.mic.notify = lambda: _note(prompts, p)
            await asyncio.wait_for(asyncio.gather(p.run_scene(2), speak(p.mic)), 10)
            assert p.completed == 2, p.status
            assert ("controller", "say: Approve") in prompts
            types = [r["type"] for r in records(p)]
            assert "ApprovedDirective" in types and "RejectedDirective" not in types
            approved = next(r["data"] for r in records(p) if r["type"] == "ApprovedDirective")
            assert approved["approved_via"] == "voice"
            state = p.state()
            assert state["controller_recorded"] is False
            assert state["mic"]["transcript"] == "Approve" and not state["mic"]["waiting"]
            heard = audits(p, "controller_heard")
            assert heard[-1]["input"] == "live mic" and heard[-1]["heard_text"] == "Approve"
            assert (p.audio_dir / heard[-1]["audio_url"].split("/")[-1]).is_file()
            assert not any("Mic fallback" in f for f in p.fallbacks)
        finally:
            await p.stop()

    async def _note(prompts, p):
        if p.mic.waiting:
            prompts.append((p.mic.role, p.mic.hint))

    asyncio.run(run())


def test_unclear_live_speech_gets_say_again_and_never_approves(tmp_path):
    async def run():
        app = app_with_mic(tmp_path, scripted("", "approve it maybe"), clips=tmp_path / "missing")
        p = app.state.presenter
        try:
            await p.run_scene(1)
            await asyncio.wait_for(asyncio.gather(p.run_scene(2), speak(p.mic, 2)), 10)
            types = [r["type"] for r in records(p)]
            assert "ApprovedDirective" not in types and p.completed == 1
            spoken = [a.get("display_text", "") for a in audits(p, "controller_spoken")]
            assert any("Say again" in text for text in spoken)
        finally:
            await p.stop()

    asyncio.run(run())


def test_silence_falls_back_to_the_recorded_clip_with_a_label(tmp_path):
    async def run():
        app = app_with_mic(tmp_path, scripted("Approve"), clips=tmp_path / "missing", mic_wait_s=0.05)
        p = app.state.presenter
        try:
            await p.run_scene(1)
            await asyncio.wait_for(p.run_scene(2), 10)
            assert p.completed == 2, p.status
            assert "ApprovedDirective" in [r["type"] for r in records(p)]
            assert p.state()["controller_recorded"] is True
            assert any("Mic fallback: no speech" in f for f in p.state()["fallbacks"])
            heard = audits(p, "controller_heard")[-1]
            assert heard["input"] == "recorded clip" and "no speech" in heard["mic_fallback"]
        finally:
            await p.stop()

    asyncio.run(run())


def test_live_readbacks_and_questions_run_the_real_pipeline(tmp_path):
    async def run():
        app = app_with_mic(tmp_path, scripted("Approve", "Hold short runway 23, Cessna 1-2-3",
                                              "Hold short runway 33, Cessna 1-2-3",
                                              "Unstep, what was my last clearance?",
                                              "Unstep, what runway was I told to stop at?"),
                           clips=tmp_path / "missing")
        p = app.state.presenter
        try:
            await p.run_scene(1)
            await asyncio.wait_for(asyncio.gather(p.run_scene(2), speak(p.mic)), 10)
            await asyncio.wait_for(asyncio.gather(p.run_scene(3), speak(p.mic, 2)), 10)
            assert p.completed == 3, p.status
            results = [r["data"]["match"] for r in records(p) if r["type"] == "ReadbackResult"]
            assert results == [False, True]
            assert all(a["input"] == "live mic" for a in audits(p, "readback"))
            await asyncio.wait_for(asyncio.gather(p.run_scene(4), speak(p.mic, 2)), 10)
            assert p.completed == 4, p.status
            assert [r["type"] for r in records(p)].count("PilotQuery") == 2
            assert [a["input"] for a in audits(p, "pilot_input")] == ["live mic", "live mic"]
        finally:
            await p.stop()

    asyncio.run(run())
