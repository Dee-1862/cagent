"""End to end: the real CockpitEdge against a real gateway (uvicorn on a free port)
with the mock agents and a scripted controller. Everything offline with fakes.
"""

import asyncio
import socket
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import soundfile as sf
import uvicorn
import websockets

from unstep.cockpit.audio import WavFileSource
from unstep.cockpit.edge import BLOCKED_NO_HINT, REQUEST_SAY_AGAIN, AudioOut, CockpitEdge, GatewayLink
from unstep.cockpit.memory import LocalMemory
from unstep.cockpit.stt import FakeManualSTT, FakeTurnSTT, TurnEvent
from unstep.cockpit.tts import FakeTTS
from unstep.contracts import (
    AnomalyEvent,
    PilotQuery,
    ProposedDirective,
    ReadbackResult,
    VoiceApproval,
    unwrap,
    wrap,
)
from unstep.gateway.server import create_app
from unstep.gateway.sink import MemorySink
from unstep.ground import mock_agents

CLIPS = Path(__file__).resolve().parents[1] / "assets" / "clips"
STEPPED = CLIPS / "stepped_on_call.wav"
WRONG, RIGHT = "Hold short runway two three, Cessna 1-2-3", "Hold short runway three three, Cessna 1-2-3"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def controller(url: str, decision: str) -> None:
    async with websockets.connect(f"{url}/ws/controller_voice") as ws:
        async for raw in ws:
            _, msg = unwrap(raw)
            if isinstance(msg, ProposedDirective):
                await ws.send(wrap(VoiceApproval(event_id=msg.event_id, heard_text=decision, decision=decision)))


@asynccontextmanager
async def ground(decision: str = "approve"):
    sink = MemorySink()
    app = create_app(sink)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    url = f"ws://127.0.0.1:{port}"
    helpers = [asyncio.create_task(mock_agents.run(url)), asyncio.create_task(controller(url, decision))]
    gw = app.state.gateway
    for _ in range(300):
        if gw.clients.get("agents") and gw.clients.get("controller_voice"):
            break
        await asyncio.sleep(0.01)
    try:
        yield url, sink
    finally:
        for h in helpers:
            h.cancel()
        server.should_exit = True
        await task


def make_edge(url: str, tmp_path, heard="Cessna 1-2-3 [static]", readbacks=(WRONG, RIGHT), tts=None):
    tts = tts or FakeTTS()
    edge = CockpitEdge(
        link=GatewayLink(url, connect_timeout_s=1.0),
        memory=LocalMemory(),
        tts=tts,
        manual_stt_factory=lambda: FakeManualSTT([heard]),
        turn_stt_factory=lambda: FakeTurnSTT(readbacks),
        audio_out=AudioOut(tmp_path / "cockpit_audio.wav"),
    )
    return edge, tts


def spoken(tts: FakeTTS) -> list[str]:
    return tts.spoken[1:]  # [0] is the pre-generated offline alert


def stored(sink, kind):
    return [r for r in sink.records if r["type"] == kind]


def test_approve_readback_wrong_then_right_and_query(tmp_path):
    async def go():
        async with ground("approve") as (url, sink):
            edge, tts = make_edge(url, tmp_path)
            assert await edge.start()
            events = await edge.run_audio(WavFileSource(STEPPED))
            assert len(events) == 1
            ev = events[0]
            assert await edge.wait_resolved(ev.event_id, 10) == "confirmed"
            q = await edge.ask("Unstep, what was my last clearance?")
            await asyncio.sleep(0.1)
            await edge.stop()
            return edge, tts, sink, ev, q

    edge, tts, sink, ev, q = asyncio.run(go())
    said = spoken(tts)
    assert said[0] == "Advisory. Transmission blocked. Likely hold short runway tree tree. Awaiting controller."
    assert "hold short runway tree tree. Read back." in said[1]
    assert said[2] == "Advisory. Readback incorrect. Runway tree tree."
    assert said[3] == "Advisory. Readback correct."
    assert "Last clearance" in said[4] and "hold short runway tree tree" in said[4]

    assert ev.local_hint.kind == "restrictive" and ev.local_hint.source_doc_id.endswith("clr-0007")
    assert ev.overlap_start < ev.overlap_end
    results = [r for r in edge.sent if isinstance(r, ReadbackResult)]
    assert [(r.attempt, r.match) for r in results] == [(1, False), (2, True)]
    assert q.source_doc_id.endswith(f"clr-{ev.event_id}")
    assert any(isinstance(m, PilotQuery) for m in edge.sent)

    assert len(stored(sink, "AnomalyEvent")) == 1
    assert len(stored(sink, "ReadbackResult")) == 2
    assert len(stored(sink, "PilotQuery")) == 1
    stages = {r["data"]["stage"] for r in stored(sink, "AuditRecord")}
    assert {"detection", "cockpit_stt", "local_hint", "directive_spoken", "readback", "pilot_query"} <= stages
    lat = edge.latency_summary()
    for k in ("detect_frame_ms", "moss_ms", "tts_first_audio_ms", "round_trip_ms"):
        assert k in lat
    assert not edge.outbox

    audio, sr = sf.read(str(tmp_path / "cockpit_audio.wav"), dtype="int16")
    assert audio.ndim == 2 and audio.shape[1] == 2
    assert np.abs(audio[:, 0]).max() > 0 and not audio[:, 1].any()  # left ear only


def test_reject_says_request_say_again(tmp_path):
    async def go():
        async with ground("reject") as (url, sink):
            edge, tts = make_edge(url, tmp_path)
            assert await edge.start()
            events = await edge.run_audio(WavFileSource(STEPPED))
            outcome = await edge.wait_resolved(events[0].event_id, 10)
            await edge.stop()
            return edge, tts, outcome

    edge, tts, outcome = asyncio.run(go())
    assert outcome == "rejected"
    assert spoken(tts)[-1] == REQUEST_SAY_AGAIN
    assert not any(isinstance(m, ReadbackResult) for m in edge.sent)


def test_gateway_down_plays_offline_alert_and_keeps_working(tmp_path):
    async def go():
        edge, tts = make_edge(f"ws://127.0.0.1:{free_port()}", tmp_path)
        assert not await edge.start()
        events = await edge.run_audio(WavFileSource(STEPPED))
        q = await edge.ask("Unstep, which taxiway?")
        await edge.stop()
        return edge, tts, events, q

    edge, tts, events, q = asyncio.run(go())
    assert len(events) == 1 and edge.outcomes[events[0].event_id] == "offline"
    texts = [ln.text for ln in edge.lines if ln.party == "PILOT EAR"]
    assert any("Likely hold short" in t for t in texts)  # hint still works locally
    assert any("request say again" in t and "offline" in t for t in texts)
    assert "Bravo" in q.answer  # queries still answered from local memory
    assert any(isinstance(m, AnomalyEvent) for m in edge.outbox)


def test_permissive_fragment_never_gets_a_hint(tmp_path):
    async def go():
        async with ground("approve") as (url, sink):
            edge, tts = make_edge(url, tmp_path, heard="Cessna 1-2-3 cleared for [static]")
            assert await edge.start()
            events = await edge.run_audio(WavFileSource(STEPPED))
            await edge.wait_resolved(events[0].event_id, 10)
            await edge.stop()
            return tts, events

    tts, events = asyncio.run(go())
    said = spoken(tts)
    assert said[0] == BLOCKED_NO_HINT
    assert not any("Likely" in s for s in said)
    assert events[0].local_hint.kind == "none"


def test_clean_call_fires_nothing(tmp_path):
    async def go():
        async with ground("approve") as (url, sink):
            edge, tts = make_edge(url, tmp_path)
            await edge.start()
            events = await edge.run_audio(WavFileSource(CLIPS / "clean_call.wav"))
            await edge.stop()
            return events, sink

    events, sink = asyncio.run(go())
    assert events == [] and not stored(sink, "AnomalyEvent")


class SlowTTS(FakeTTS):
    async def speak(self, text, context_id=None, on_chunk=None):
        for _ in range(50):
            if context_id in self.cancelled:
                break
            await asyncio.sleep(0.005)
        return await super().speak(text, context_id, on_chunk)


def test_turn_start_interrupts_voice(tmp_path):
    async def go():
        edge, tts = make_edge("ws://127.0.0.1:1", tmp_path, tts=SlowTTS())
        speaking = asyncio.create_task(edge.speak("Hold short Runway 33"))
        await asyncio.sleep(0.02)
        await edge.on_turn(TurnEvent("turn.start"))
        return await speaking

    assert asyncio.run(go()).speech.cancelled
