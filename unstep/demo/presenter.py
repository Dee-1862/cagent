from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
import numpy as np
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from unstep import scenario
from unstep.clock import now_ms
from unstep.config import elastic_events_index, elastic_settings
from unstep.contracts import (AnomalyEvent, ApprovedDirective, AuditRecord, RejectedDirective,
                              TowerTranscript, unwrap, wrap)
from unstep.cockpit.audio import ArraySource, read_wav
from unstep.cockpit.edge import AudioOut, CockpitEdge, DEMO_READBACKS
from unstep.cockpit.inference import FakeAnswerer
from unstep.cockpit.memory import LocalMemory, create_memory
from unstep.cockpit.monitor import FrequencyMonitor
from unstep.cockpit.stt import FakeManualSTT, FakeTurnSTT, ReplayTurnSTT
from unstep.cockpit.tts import FakeTTS
from unstep.demo_audio import DEFAULT_DEMO_AUDIO_DIR, save_audio
from unstep.demo.mic import MIC_WAIT_S, MicSource, MicTurns
from unstep.gateway.server import LOOPBACK, create_app, origin_ok
from unstep.gateway.sink import MemorySink
from unstep.ground.mock_agents import propose
from unstep.ground.tower import FakeTowerTranscriber, TowerTranscriber
from unstep.ground.voice_approval import ApprovalLoop, ControllerVoice, _answer

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("unstep.demo")
SCENES = ("Radio", "Controller approval", "Directive and readbacks", "Pilot questions",
          "Full view", "Analytics", "Close")
QUESTIONS = ("Unstep, what was my last clearance?", "Unstep, what runway was I told to stop at?")
READBACK_HINT = "read back: hold short runway 33, Cessna 1-2-3"
# What the presenter is prompted to say in --mic mode, one hint per turn.
MIC_HINTS = {
    "controller": ["say: Approve", "say again: Approve"],
    "readback": [READBACK_HINT + " (demo: say 23 first)", READBACK_HINT],
    "questions": [f"ask: {q}" for q in QUESTIONS],
}
# With --mic the controller gets the mic wait plus time for the clip fallback.
CONTROLLER_WINDOW_MIC_S = MIC_WAIT_S + 15


class RoleLink:
    """In-process transport; all messages still pass Gateway.handle and its ACLs.

    Incoming messages are queued rather than recursively invoking the pipeline.
    The presenter consumes controller/cockpit queues only at the relevant beat.
    """

    def __init__(self, gateway, role):
        self.gateway, self.role = gateway, role
        self.queue = asyncio.Queue()
        self.online = False
        self.on_message = None

    async def connect(self):
        self.gateway.clients[self.role].add(self)
        self.online = True
        return True

    async def close(self):
        self.gateway.clients[self.role].discard(self)
        self.online = False

    async def send_text(self, raw):
        await self.queue.put(raw)

    async def send_json(self, message):
        raise RuntimeError(message["data"]["message"])

    async def send(self, message):
        await self.send_raw(wrap(message))
        return True

    async def send_raw(self, raw):
        await self.gateway.handle(self.role, raw, self)

    async def receive(self, kind):
        while True:
            _, msg = unwrap(await asyncio.wait_for(self.queue.get(), 15))
            if type(msg).__name__ == kind:
                return msg


class RecordedFakeTurns(FakeTurnSTT):
    """Scripted recognition, with the real input recording available for playback."""

    sample_rate = 16000

    def __init__(self, texts, clips):
        super().__init__(texts)
        self.clips = iter(clips)
        self.last_pcm = None

    async def events(self):
        for text in self.utterances:
            self.last_pcm = next(self.clips, None)
            async for event in FakeTurnSTT([text]).events():
                yield event


class BrowserVoice(ControllerVoice):
    async def _play(self, mono, sample_rate):
        # Browser is the sole audio output, including in live mode.
        pass


class Presenter:
    def __init__(self, gateway, *, live=False, audio_dir=DEFAULT_DEMO_AUDIO_DIR,
                 clips=None, realtime=True, mic=None, mic_wait_s=MIC_WAIT_S):
        self.gateway, self.live = gateway, live
        # Optional live push-to-talk (--mic). None keeps every scene on recorded clips.
        self.mic: MicSource | None = mic
        self.mic_wait_s = mic_wait_s
        self.controller_live = False
        if mic is not None:
            mic.notify = self.broadcast
        self.audio_dir = Path(audio_dir)
        self.clips = Path(clips) if clips else ROOT / "assets" / "clips" / "real"
        self.realtime = realtime
        self.scene = 0
        self.completed = 0
        self.audio_mode = True
        self.status = "Ready. Space to start the radio."
        self.fallbacks = set()
        if not live:
            self.fallbacks.add("Offline: fake STT, tone TTS, local memory and mock ground agents")
        self.peers = set()
        self.lock = asyncio.Lock()
        self.task = None
        self.generation = 0
        self.links = {}
        self.edge = None
        self.tts = None
        self.started = False
        self.run_started_ms = now_ms()

    def state(self, action=None):
        return {"type": "DemoScene", "scene": self.scene, "total": len(SCENES),
                "title": SCENES[max(0, self.scene - 1)], "audio_mode": self.audio_mode,
                "mode": "LIVE" if self.live else "REPLAY", "status": self.status,
                "busy": bool(self.task and not self.task.done()), "action": action,
                "generation": self.generation, "fallbacks": sorted(self.fallbacks),
                # Without --mic the controller's "Approve" is a recorded clip; say so on screen.
                "controller_recorded": not self.controller_live,
                "mic": self.mic.state() if self.mic else {"enabled": False},
                "frequency": scenario.FREQUENCY, "callsign": scenario.CALLSIGN,
                "services": {"Cartesia": "live configured" if self.live else "fake",
                             "Moss": getattr(getattr(self.edge, "memory", None), "backend", "idle"),
                             "Elastic": "configured" if self.live and elastic_settings() else "gateway"}}

    async def broadcast(self, action=None):
        state = self.state(action)
        for peer in list(self.peers):
            try:
                await peer.send_json(state)
            except Exception:
                self.peers.discard(peer)

    def samples(self, name):
        path = self.clips / name
        if path.is_file():
            return read_wav(path), True
        self.fallbacks.add(f"{name} missing: fake recognition / synthetic audio")
        fallback = ROOT / "assets" / "clips" / name
        if fallback.is_file():
            return read_wav(fallback), False
        # Synthetic input, not a fabricated detection: still processed by detector.
        t = np.arange(41600) / 16000
        samples = .08 * np.sin(2 * np.pi * (180 * t + 90 * t * t))
        if name == "stepped_on_call.wav":
            samples += .35 * np.sin(2 * np.pi * 1700 * t) * (t > 1.2)
        return samples.astype(np.float32), False

    def turns(self, names, texts):
        recordings = [self.samples(name) for name in names]
        pcm = [(np.clip(x, -1, 1) * 32767).astype("<i2").tobytes() for x, _ in recordings]
        if self.live and all(found for _, found in recordings):
            from unstep.cockpit.stt import CartesiaTurnSTT, build_keyterms
            return ReplayTurnSTT(lambda: CartesiaTurnSTT(keyterms=build_keyterms(
                callsigns=[scenario.CALLSIGN, scenario.SPOKEN_CALLSIGN], runways=["33", "23"])), pcm)
        return RecordedFakeTurns(texts, pcm)

    def listen(self, role, hints, names, texts, *, say_again=False):
        """Live mic turns when --mic, else the recorded clips exactly as before."""
        if self.mic is None:
            return self.turns(names, texts)

        def on_turn(party, live):
            if party == "controller":
                self.controller_live = live

        async def repeat():
            await self.edge.speak("Say again.")

        return MicTurns(self.mic, role, hints, lambda i: self.turns([names[i]], [texts[i]]),
                        wait_s=self.mic_wait_s, say_again=repeat if say_again else None,
                        on_turn=on_turn, on_fallback=self.fallbacks.add)

    async def start(self):
        if self.started:
            return
        for role in ("tower", "agents", "monitor", "controller_voice", "cockpit"):
            self.links[role] = RoleLink(self.gateway, role)
            await self.links[role].connect()
        memory = create_memory() if self.live else LocalMemory()
        self.monitor = FrequencyMonitor(create_memory() if self.live else LocalMemory())
        self.tts = FakeTTS()
        manual = lambda: FakeManualSTT(["Cessna 1-2-3 [static]"])
        if self.live:
            from unstep.cockpit.stt import CartesiaManualSTT, build_keyterms
            from unstep.cockpit.tts import CartesiaTTS
            self.tts = CartesiaTTS()
            manual = lambda: CartesiaManualSTT(keyterms=build_keyterms(
                callsigns=[scenario.CALLSIGN, scenario.SPOKEN_CALLSIGN], runways=["33"]))
        self.edge = CockpitEdge(link=self.links["cockpit"], memory=memory, tts=self.tts,
            manual_stt_factory=manual, turn_stt_factory=lambda: self.listen(
                "pilot", MIC_HINTS["readback"], ["wrong_readback.wav", "correct_readback.wav"],
                DEMO_READBACKS, say_again=True),
            answerer=None if self.live else FakeAnswerer(), audio_out=AudioOut(path=None),
            demo_audio_dir=self.audio_dir)
        await self.edge.start()
        self.started = True

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.edge:
            await self.edge.stop()
        for link in self.links.values():
            await link.close()
        if self.tts and hasattr(self.tts, "close"):
            await self.tts.close()
        self.started = False

    async def drain_monitor(self):
        link = self.links["monitor"]
        while not link.queue.empty():
            env, msg = unwrap(link.queue.get_nowait())
            for insight in await self.monitor.handle(msg, env.ts):
                await link.send(insight)

    async def run_scene(self, scene):
        try:
            await self.start()
            if scene == 1:
                await self.radio()
            elif scene == 2:
                proposal = await self.links["controller_voice"].receive("ProposedDirective")
                # Same strict loop either way; --mic only gives the presenter longer to answer.
                loop = ApprovalLoop(window_s=CONTROLLER_WINDOW_MIC_S if self.mic else 10.0)
                loop.enqueue(proposal)
                await _answer(loop, loop.start_next(), BrowserVoice(self.tts, self.audio_dir),
                    lambda: self.listen("controller", MIC_HINTS["controller"],
                                        ["controller_approve.wav"] * 2, ["Approve"] * 2),
                    self.links["controller_voice"].send_raw)
                decision = None
                for raw in list(self.links["cockpit"].queue._queue):
                    _, msg = unwrap(raw)
                    if getattr(msg, "event_id", None) == proposal.event_id:
                        decision = msg
                if isinstance(decision, RejectedDirective):
                    await self.edge._on_rejected(decision)
                    raise RuntimeError("controller rejected the directive; nothing was sent")
                if not isinstance(decision, ApprovedDirective):
                    raise RuntimeError("controller did not approve this proposal")
            elif scene == 3:
                approved = await self.links["cockpit"].receive("ApprovedDirective")
                await self.edge._on_approved(approved)
            elif scene == 4:
                # Moss Inference goes cold while the presenter talks; re-warm it while the first
                # question (a fixed intent, no LLM) plays, so the free-form one gets a warm model.
                rewarm = asyncio.create_task(self.warm_answerer())
                for name, fallback, hint in zip(["pilot_question.wav", "pilot_question_stop.wav"],
                                                QUESTIONS, MIC_HINTS["questions"]):
                    stt = self.listen("pilot", [hint], [name], [fallback], say_again=True)
                    async with stt:
                        async for event in stt.events():
                            if event.type == "turn.end" and event.transcript.strip():
                                # Input first; ask() emits the answer before its final audit.
                                await self.edge.audit("", "pilot_input", heard_text=event.transcript,
                                    party="pilot", **(getattr(stt, "last_input", None) or {}),
                                    **save_audio(self.audio_dir,
                                        np.frombuffer(stt.last_pcm, dtype="<i2"), 16000))
                                if fallback == QUESTIONS[1]:
                                    await rewarm
                                await self.edge.ask(event.transcript)
            await self.drain_monitor()
            self.completed = max(self.completed, scene)
            self.status = "Ready for next scene."
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("scene %s failed", scene)
            self.status = f"Scene failed ({type(exc).__name__}). Reset to retry; no result fabricated."
        finally:
            # The current task is finishing; publish busy=False.
            self.task = None
            await self.broadcast()

    async def radio(self):
        t0 = now_ms()
        clean, clean_real = self.samples("clean_call.wav")
        received, received_real = self.samples("stepped_on_call.wav")
        tower = TowerTranscriber(runways=["33"]) if self.live and clean_real else FakeTowerTranscriber()

        async def tower_side():
            # The tower and the cockpit hear the same radio call at the same time.
            pcm = (np.clip(clean, -1, 1) * 32767).astype("<i2").tobytes()
            transcript = await tower.transcribe(pcm, t0, t0 + round(len(clean) / 16),
                                                scenario.FREQUENCY, scenario.CALLSIGN)
            await self.links["tower"].send(transcript)
            await self.links["tower"].send(AuditRecord(event_id=transcript.transcript_id,
                stage="tower_audio", actor="tower", payload={"party": "tower", "spoken_text": transcript.text,
                    "words": [w.model_dump() for w in transcript.words], **save_audio(self.audio_dir, clean, 16000)}))

        tower_task = asyncio.create_task(tower_side())
        await self.edge.audit("", "radio_input", party="radio", heard_text="Radio input (recorded clip)",
                              **save_audio(self.audio_dir, received, 16000))
        if self.live and not received_real:
            self.edge.manual_stt_factory = lambda: FakeManualSTT(["Cessna 1-2-3 [static]"])
        try:
            events = await self.edge.run_audio(ArraySource(received, t0=t0), realtime=self.realtime)
        finally:
            await tower_task
        if not events:
            raise RuntimeError("no blocked transmission detected")
        frames = self.edge.latency.get("detect_frame_ms", [])
        if frames:
            await self.edge.audit(events[0].event_id, "detection", float(np.mean(frames)),
                                  measurement="mean detector frame processing", party="radio")
        # Consume the same messages as mock_agents.run, preserving role validation. The tower
        # transcript may arrive after the cockpit's event now that both run in parallel.
        agent = self.links["agents"]
        received_msgs = []
        while not agent.queue.empty():
            received_msgs.append(unwrap(agent.queue.get_nowait())[1])
        transcripts = [m for m in received_msgs if isinstance(m, TowerTranscript)]
        latest = transcripts[-1] if transcripts else None
        for msg in received_msgs:
            if isinstance(msg, AnomalyEvent):
                await agent.send(propose(msg, latest))

    async def warm_answerer(self):
        answerer = getattr(self.edge, "answerer", None)
        if answerer is None:
            return
        from unstep.cockpit.memory import Doc
        try:
            await answerer.answer("Which runway?", [Doc(id="warm", text="Runway 33", metadata={})])
        except Exception:
            self.fallbacks.add("Moss Inference warm-up failed")

    async def warm(self):
        """Live mode: open every connection before the presenter presses Space."""
        await self.start()
        try:
            await self.tts.speak("Unstep ready.")
        except Exception:
            self.fallbacks.add("Cartesia warm-up failed")
        await self.warm_answerer()
        self.status = "Ready. Space to start the radio."
        await self.broadcast()

    async def control(self, action):
        async with self.lock:
            if action == "reset":
                await self.stop()
                # Each run writes its utterances as WAV files; don't let them pile up.
                for old_wav in self.audio_dir.glob("*.wav"):
                    old_wav.unlink(missing_ok=True)
                self.gateway.history.clear()
                self.gateway.pending.clear()
                self.gateway.decided.clear()
                self.scene, self.completed = 1, 0
                self.controller_live = False
                if self.mic:
                    self.mic.reset()
                self.run_started_ms = now_ms()
                self.generation += 1
                self.audio_mode = True
                self.fallbacks.clear()
                if not self.live:
                    self.fallbacks.add("Offline: fake STT, tone TTS, local memory and mock ground agents")
                self.status = "Processing radio"
                self.task = asyncio.create_task(self.run_scene(1))
            elif action == "mode":
                self.audio_mode = not self.audio_mode
            elif action == "prev":
                self.scene = max(1, self.scene - 1)
                self.audio_mode = self.scene <= 4
            elif action == "next":
                if self.task and not self.task.done():
                    raise HTTPException(409, "Current scene is still processing")
                target = min(len(SCENES), self.scene + 1)
                if target > self.completed + 1:
                    raise HTTPException(409, "Reset after a failed scene")
                self.scene = target
                self.audio_mode = target <= 4
                if target > self.completed:
                    self.status = f"Processing {SCENES[target - 1]}"
                    self.task = asyncio.create_task(self.run_scene(target))
            await self.broadcast(action)
            return self.state(action)


def stats_query(since_ms: int | None = None):
    index = elastic_events_index().replace("`", "``")
    # Scope to this run, so rehearsals and earlier runs never show up as this run's numbers.
    scope = f"| WHERE ts >= {int(since_ms)}\n" if since_ms else ""
    return (f"FROM `{index}`\n{scope}| WHERE type == \"AnomalyEvent\" OR "
            '(type == "ReadbackResult" AND match == false) OR type == "ApprovedDirective"\n'
            '| STATS count = COUNT(*) BY type, approved_via\n| SORT type, approved_via')


async def statistics(gateway, *, elastic=True, since_ms=None):
    query = stats_query(since_ms)
    settings = elastic_settings() if elastic else None
    if settings:
        url, key = settings
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url.rstrip("/") + "/_query",
                    headers={"Authorization": f"ApiKey {key}"}, json={"query": query})
                response.raise_for_status()
                data = response.json()
            names = [column["name"] for column in data["columns"]]
            return {"esql": query, "rows": [dict(zip(names, row)) for row in data["values"]], "source": "elastic"}
        except (httpx.HTTPError, KeyError, ValueError):
            raise HTTPException(502, "Elastic query failed; no analytics result substituted") from None
    counts = {}
    for raw in gateway.history:
        env = json.loads(raw)
        kind, data = env["type"], env["data"]
        if kind == "AnomalyEvent" or kind == "ApprovedDirective" or (kind == "ReadbackResult" and data.get("match") is False):
            key = (kind, data.get("approved_via"))
            counts[key] = counts.get(key, 0) + 1
    return {"esql": query, "rows": [{"type": k, "approved_via": via, "count": count}
            for (k, via), count in sorted(counts.items(), key=lambda item: str(item[0]))],
            "source": "gateway", "scope": "last 200 gateway messages"}


class Control(BaseModel):
    action: Literal["next", "prev", "reset", "replay", "mode"]


def create_demo_app(*, live=False, audio_dir=DEFAULT_DEMO_AUDIO_DIR, sink=None, mic=False,
                    mic_stt_factory=None, **options):
    """`mic=True` adds live push-to-talk on /demo/mic. `mic_stt_factory` overrides the
    Cartesia manual STT (tests pass a fake)."""
    app = create_app(sink=sink if sink is not None else (None if live else MemorySink()),
                     demo_audio_dir=audio_dir)
    source = (MicSource(mic_stt_factory) if mic_stt_factory else MicSource()) if mic else None
    presenter = Presenter(app.state.gateway, live=live, audio_dir=audio_dir, mic=source, **options)
    app.state.presenter = presenter
    router = APIRouter()

    @router.post("/demo/control")
    async def control(body: Control, request: Request):
        if request.client.host not in LOOPBACK or not origin_ok(request):
            raise HTTPException(403, "Presenter controls are local and same-origin only")
        return await presenter.control(body.action)

    @router.get("/demo/stats")
    async def stats():
        return await statistics(app.state.gateway, elastic=live, since_ms=presenter.run_started_ms)

    @router.websocket("/demo/events")
    async def events(ws: WebSocket):
        if ws.client.host not in LOOPBACK or not origin_ok(ws):
            await ws.close(code=4003)
            return
        await ws.accept()
        presenter.peers.add(ws)
        try:
            await ws.send_json(presenter.state())
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            presenter.peers.discard(ws)

    @router.websocket("/demo/mic")
    async def mic_audio(ws: WebSocket):
        # Same local-only rules as /demo/events (the Host header is checked by middleware).
        if presenter.mic is None or ws.client.host not in LOOPBACK or not origin_ok(ws):
            await ws.close(code=4003)
            return
        await ws.accept()
        try:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes"):
                    presenter.mic.feed(message["bytes"])
                elif message.get("text"):
                    try:
                        kind = json.loads(message["text"]).get("type")
                    except (ValueError, AttributeError):
                        continue
                    if kind == "end":
                        presenter.mic.end()
        except WebSocketDisconnect:
            pass
        finally:
            presenter.mic.end()  # a dropped socket mid-utterance ends that utterance

    # Insert before the gateway's /demo static mount, which otherwise shadows APIs.
    app.router.routes[0:0] = router.routes
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            if live:
                presenter.status = "Warming up Cartesia, Moss and Moss Inference"
                await presenter.warm()
            try:
                yield
            finally:
                await presenter.stop()

    app.router.lifespan_context = lifespan
    return app
