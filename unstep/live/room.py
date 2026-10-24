"""The live room: people on a shared frequency, agents in the middle, a human for edge cases.

Every agent runs in this process but talks to the real gateway through
InProcLink, so every message passes the gateway's role checks, routing,
single-decision rule and Elastic storage exactly as over a WebSocket.

    people (browsers)  ->  radio (mix, radio truth)  ->  tower transcriber, cockpit agent per aircraft
    cockpit agents     ->  gateway  ->  ground agents  ->  policy agent  ->  auto-relay or the controller
    gateway (observer) ->  event traces and agent-graph flows  ->  browsers

See docs/11-live-demo.md.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable

import numpy as np
import soundfile as sf

from unstep import scenario
from unstep.clock import now_ms
from unstep.config import ROOT, env, moss_aircraft, realtime_replay
from unstep.contracts import (AnomalyEvent, ApprovedDirective, AuditRecord, Insight, PilotQuery,
                              ProposedDirective, ReadbackResult, RejectedDirective, TowerTranscript,
                              VoiceApproval, Word, unwrap, wrap)
from unstep.cockpit.audio import SAMPLE_RATE, ArraySource
from unstep.cockpit.edge import AudioOut, CockpitEdge, Line
from unstep.cockpit.memory import LocalMemory, create_memory
from unstep.cockpit.monitor import FrequencyMonitor
from unstep.cockpit.phraseology import parse_callsign
from unstep.cockpit.stt import CartesiaManualSTT, FakeManualSTT, TurnEvent, build_keyterms
from unstep.cockpit.tts import FakeTTS
from unstep.ground.mock_agents import propose
from unstep.ground.policy import PolicyAgent
from unstep.live.radio import KeyedSquelch, Mix, Transmission, clusters, heard_text, mix, to_mono16k

log = logging.getLogger("unstep.live")

VOICES_FILE = ROOT / "assets" / "clips" / "real" / "voices.json"
GAP_MS = 300  # quiet time after the last transmission before a cluster is processed
TRANSCRIPT_WAIT_S = 12.0  # how long ground agents wait for the tower transcript
READBACK_WAIT_S = 45.0  # how long a cockpit waits for the pilot's readback
CLAIM_S = 20.0  # a seat handed out by join() stays reserved this long for its websocket
MAX_STREAM_S = 60  # longest push-to-talk stream accepted
STREAM_FINAL_S = 10.0  # how long consumers wait for a streamed transcript before replaying the clip


@dataclass
class Station:
    id: str
    kind: str  # atc, aircraft, observer
    label: str
    voice_role: str | None = None  # key in assets/clips/real/voices.json
    callsign: str | None = None
    spoken: str | None = None  # callsign as said on frequency, e.g. "Cessna 1-2-3"
    name: str | None = None  # plain name for judges, e.g. "Plane A"


def aircraft_station(callsign: str, spoken: str, name: str, voice_role: str) -> Station:
    return Station(callsign, "aircraft", f"Pilot, {spoken} ({callsign})", voice_role, callsign, spoken, name)


FLEET_STATIONS = [aircraft_station(*f) for f in scenario.FLEET]
DEFAULT_STATIONS = [
    Station("atc", "atc", "Tower controller: human in the loop", "tower"),
    *FLEET_STATIONS[:2],
    Station("observer", "observer", "Observer screen for judges"),
]

# Agent graph shown to the controller and the observer. Flows animate its edges.
GRAPH_NODES = [
    {"id": "radio", "label": "Radio 118.700", "sub": "shared frequency"},
    {"id": "tower_stt", "label": "Tower transcriber", "sub": "Cartesia STT"},
    {"id": "cockpit:N123AB", "label": "Cockpit agent N123AB", "sub": "Cartesia + Moss"},
    {"id": "cockpit:H456", "label": "Cockpit agent H456", "sub": "Cartesia + local memory"},
    {"id": "gateway", "label": "Gateway", "sub": "routing and rules"},
    {"id": "ground", "label": "Ground agents", "sub": "mock until Elastic B5"},
    {"id": "policy", "label": "Policy agent", "sub": "auto-relay or escalate"},
    {"id": "monitor", "label": "Frequency monitor", "sub": "insights"},
    {"id": "controller", "label": "Controller (you)", "sub": "edge cases only"},
    {"id": "elastic", "label": "Elastic", "sub": "audit and analytics"},
]


def wav_b64(samples: np.ndarray, sample_rate: int) -> str:
    """float or int16, mono or stereo -> base64 WAV for the browser."""
    buf = io.BytesIO()
    data = np.asarray(samples)
    if data.dtype != np.int16:
        data = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16)
    sf.write(buf, data, sample_rate, format="WAV", subtype="PCM_16")
    return base64.b64encode(buf.getvalue()).decode()


def pcm16(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def station_voices() -> dict[str, str]:
    try:
        return {k: v["id"] for k, v in json.loads(VOICES_FILE.read_text(encoding="utf-8"))["voices"].items()}
    except (OSError, KeyError, ValueError):
        return {}


class InProcLink:
    """A gateway client inside this process. Messages still go through Gateway.handle.

    Incoming messages are queued and handled by one task per link, so a reply sent
    while handling never re-enters the gateway's broadcast.
    """

    def __init__(self, gateway, role: str, on_message: Callable[..., Awaitable[Any]] | None = None,
                 on_error: Callable[[str], Any] | None = None):
        self.gateway, self.role = gateway, role
        self.on_message = on_message
        self.on_error = on_error
        self.online = False
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def connect(self) -> bool:
        self.gateway.clients[self.role].add(self)
        self.online = True
        if self._task is None:
            self._task = asyncio.create_task(self._drain())
        return True

    async def close(self) -> None:
        self.gateway.clients[self.role].discard(self)
        self.online = False
        if self._task:
            self._task.cancel()

    async def send(self, msg) -> bool:
        await self.gateway.handle(self.role, wrap(msg), self)
        return True

    async def send_text(self, raw: str) -> None:  # called by the gateway
        await self._queue.put(raw)

    async def send_json(self, message: dict) -> None:  # gateway error replies
        text = message.get("data", {}).get("message", str(message))
        log.warning("gateway error for %s: %s", self.role, text)
        if self.on_error:
            self.on_error(text)

    async def _drain(self) -> None:
        while True:
            raw = await self._queue.get()
            try:
                env_, msg = unwrap(raw)
                if msg is not None and self.on_message is not None:
                    if self.role == "observer":
                        await self.on_message(env_, msg)
                    else:
                        await self.on_message(msg)
            except Exception:
                log.exception("%s failed on a message", self.role)


class StationTurns:
    """A pilot's readbacks arrive as that aircraft's radio transmissions."""

    def __init__(self, wait_s: float = READBACK_WAIT_S):
        self.queue: asyncio.Queue[tuple[str, bytes | None]] = asyncio.Queue()
        self.listening = 0
        self.wait_s = wait_s

    def factory(self):
        return _Turns(self)


class _Turns:
    sample_rate = SAMPLE_RATE

    def __init__(self, owner: StationTurns):
        self.owner = owner
        self.last_pcm = None

    async def __aenter__(self):
        while not self.owner.queue.empty():  # drop anything said before the directive
            self.owner.queue.get_nowait()
        self.owner.listening += 1
        return self

    async def __aexit__(self, *exc):
        self.owner.listening -= 1

    async def send_audio(self, pcm: bytes) -> None:
        pass

    async def configure(self, **turn) -> None:
        pass

    async def events(self):
        while True:
            try:
                text, pcm = await asyncio.wait_for(self.owner.queue.get(), self.owner.wait_s)
            except asyncio.TimeoutError:
                return
            self.last_pcm = pcm
            yield TurnEvent("turn.start")
            yield TurnEvent("turn.end", transcript=text)


class SerialTTS:
    """One headset, one voice: queues speak() calls on a shared speech connection.

    In the live room an auto-relayed directive can arrive while the cockpit is still
    speaking the local hint; two concurrent speak() calls on one Cartesia socket fail.
    """

    def __init__(self, engine):
        self.engine = engine
        self._lock = asyncio.Lock()

    async def speak(self, text, context_id=None, on_chunk=None):
        async with self._lock:
            return await self.engine.speak(text, context_id=context_id, on_chunk=on_chunk)

    def __getattr__(self, name):
        return getattr(self.engine, name)


class BrowserAudioOut(AudioOut):
    """Sends what the cockpit agent speaks to that pilot's browser (left ear already)."""

    def __init__(self, room: "LiveRoom", station: str):
        super().__init__(path=None)
        self.room, self.station = room, station

    def add(self, stereo: np.ndarray, sample_rate: int) -> None:
        self.room.send_to({self.station}, {"type": "advisory_audio", "audio": wav_b64(stereo, sample_rate)})


class LiveEdge(CockpitEdge):
    """CockpitEdge that also shows its transcript lines in the pilot's browser."""

    room: "LiveRoom | None" = None

    def _note(self, party: str, text: str, **latency: float) -> Line:
        line = super()._note(party, text, **latency)
        if self.room is not None:
            self.room.send_to({self.callsign}, {"type": "cockpit_line", **asdict(line)})
        return line


class GroundAgents:
    """Stand-in for the Intercept and Compliance agents until the Elastic Workflow (B5).

    Matches each blocked call with the controller's own transmission and proposes
    the directive with unstep.ground.mock_agents.propose.
    """

    def __init__(self, send, wait_s: float = TRANSCRIPT_WAIT_S):
        self.send, self.wait_s = send, wait_s
        self.transcripts: list[TowerTranscript] = []
        self._changed = asyncio.Condition()
        self._tasks: set[asyncio.Task] = set()

    async def on_message(self, msg) -> None:
        if isinstance(msg, TowerTranscript):
            async with self._changed:
                self.transcripts.append(msg)
                self._changed.notify_all()
        elif isinstance(msg, AnomalyEvent):
            task = asyncio.create_task(self._propose(msg))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _match(self, event: AnomalyEvent) -> TowerTranscript | None:
        for t in reversed(self.transcripts):
            if (t.frequency == event.frequency and t.ptt_start < event.squelch_close
                    and t.ptt_end > event.squelch_open):
                return t
        return None

    async def _propose(self, event: AnomalyEvent) -> None:
        started = now_ms()
        async with self._changed:
            try:
                await asyncio.wait_for(self._changed.wait_for(lambda: self._match(event) is not None), self.wait_s)
            except asyncio.TimeoutError:
                pass
        transcript = self._match(event)
        proposal = propose(event, transcript)
        await self.send(proposal)
        await self.send(AuditRecord(event_id=event.event_id, stage="ground_agents", actor="agents",
                                    latency_ms=now_ms() - started, payload={
                                        "matched_transcript": transcript.transcript_id if transcript else None,
                                        "tower_text": transcript.text if transcript else None,
                                        "blocked_words": proposal.blocked_words,
                                        "confidence": proposal.confidence,
                                        "confidence_method": proposal.confidence_method,
                                        "agents": "mock intercept + compliance (Elastic Workflow in B5)"}))


class LiveRoom:
    def __init__(self, gateway, *, live: bool, stations: list[Station] | None = None,
                 tts_factory: Callable[[str | None], Any] | None = None, advisory_tts=None,
                 tower_transcriber=None, frequency: str = scenario.FREQUENCY,
                 stream_stt_factory: Callable[[Station], Any] | None = None):
        self.gateway, self.live, self.frequency = gateway, live, frequency
        self.stations = {s.id: s for s in (stations or DEFAULT_STATIONS)}
        self.voices = station_voices()
        self.tts_factory = tts_factory or self._default_tts
        self.advisory_tts = advisory_tts
        self.tower_transcriber = tower_transcriber
        self.stream_stt_factory = stream_stt_factory
        self.streams: dict[str, dict] = {}  # station -> push-to-talk stream in progress (P3)
        self.stream_results: dict[str, asyncio.Task] = {}  # tx_id -> streamed transcript
        self.alignments: dict[str, dict] = {}  # transcript_id -> tower word alignment report (P7b)
        # W3: replays to the manual STT endpoint go as fast as possible unless UNSTEP_REALTIME_REPLAY=1
        self.realtime_replay = realtime_replay()
        self.clients: dict[str, set] = {sid: set() for sid in self.stations}
        self.edges: dict[str, LiveEdge] = {}
        self.turns: dict[str, StationTurns] = {}
        self.traces: dict[str, dict] = {}
        self.transcripts: dict[str, TowerTranscript] = {}
        self.insights: list[dict] = []
        self.radio_log: list[dict] = []
        self.pending: list[Transmission] = []
        self.keyed: set[str] = set()
        self._wake = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._started = False
        self._start_lock = asyncio.Lock()
        self.links: dict[str, InProcLink] = {}
        self.policy: PolicyAgent | None = None
        self.monitor: FrequencyMonitor | None = None  # writes the hub's freq-<frequency> session
        self.graph = [dict(n) for n in GRAPH_NODES]
        self.key_since: dict[str, int] = {}  # station -> hub time its radio key went down
        self.stepons: list[dict] = []  # live two-keys-down detections, matched to events for timings
        self.claims: dict[str, float] = {}  # station -> hub time join() handed it out
        self._join_lock = asyncio.Lock()
        self._moss_used = 0

    # ------------------------------------------------------------ setup

    def _default_tts(self, voice_id: str | None):
        if self.live and env("CARTESIA_API_KEY") and voice_id:
            from unstep.cockpit.tts import CartesiaTTS

            return CartesiaTTS(voice_id=voice_id)
        return FakeTTS(sample_rate=SAMPLE_RATE)

    def _advisory_tts(self):
        if self.advisory_tts is not None:
            return self.advisory_tts
        if self.live and env("CARTESIA_API_KEY") and env("CARTESIA_VOICE_ID"):
            from unstep.cockpit.tts import CartesiaTTS

            return CartesiaTTS()
        return FakeTTS()

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        async with self._start_lock:
            if self._started:
                return
            gw = self.gateway
            self.links["tower"] = InProcLink(gw, "tower")
            ground = GroundAgents(lambda m: self.links["agents"].send(m))
            self.links["agents"] = InProcLink(gw, "agents", ground.on_message)
            self.policy = PolicyAgent(lambda m: self.links["policy"].send(m))
            self.links["policy"] = InProcLink(gw, "policy", self.policy.on_message,
                                              on_error=lambda t: self._status(f"policy: {t}"))
            # The hub's frequency session (freq-<frequency>): a Moss session when live, written
            # only by the Frequency Monitor, never pushed. Local memory offline or if Moss fails.
            monitor = self.monitor = FrequencyMonitor(create_memory() if self.live else LocalMemory())

            async def monitor_on(msg):
                try:
                    insights = await monitor.handle(msg, now_ms())
                except Exception:
                    if monitor.memory.backend == "local":
                        raise
                    log.exception("Moss frequency session failed; the monitor uses local memory from now on")
                    monitor.memory, monitor.registered = LocalMemory(), set()
                    insights = await monitor.handle(msg, now_ms())
                for insight in insights:
                    await self.links["monitor"].send(insight)

            self.links["monitor"] = InProcLink(gw, "monitor", monitor_on)
            self.links["dashboard"] = InProcLink(gw, "dashboard", on_error=lambda t: self._status(t, to={"atc"}))
            self.links["observer"] = InProcLink(gw, "observer", self._observe)
            for link in self.links.values():
                await link.connect()

            for s in list(self.stations.values()):
                if s.kind == "aircraft":
                    await self._start_edge(s)
            self._spawn(self._scheduler())
            self._spawn(self._ticker())
            self._started = True

    async def _start_edge(self, s: Station) -> None:
        """One cockpit agent per aircraft, with its own flight session."""
        turns = StationTurns()
        # A Moss session indexes in memory and only reaches the cloud index on push_index(),
        # which per-aircraft sessions never call, so the plan's index limit does not cap them
        # (six real sessions checked by Rishit, R3). UNSTEP_MOSS_AIRCRAFT (default 6) planes get Moss.
        use_moss = self.live and self._moss_used < moss_aircraft()
        memory = create_memory() if use_moss else LocalMemory()
        self._moss_used += 1

        def build(mem):
            e = LiveEdge(callsign=s.callsign, frequency=self.frequency,
                         link=InProcLink(self.gateway, "cockpit"), memory=mem,
                         tts=SerialTTS(self._advisory_tts()), turn_stt_factory=turns.factory,
                         audio_out=BrowserAudioOut(self, s.id))
            e.room = self
            return e

        edge = build(memory)
        try:
            await edge.start()
        except Exception:
            if memory.backend == "local":
                raise
            # Moss unreachable (venue network, outage): this plane flies on local memory instead of
            # taking the room down. The graph label says which memory it has.
            log.exception("Moss failed for %s; using local memory", s.callsign)
            await edge.link.close()
            memory = LocalMemory()
            edge = build(memory)
            await edge.start()
        self.edges[s.callsign] = edge
        self.turns[s.callsign] = turns
        if self.key_since:  # joined while someone is talking: hold its advisories too
            self._spawn(self._frequency_busy(edge, True))
        node = f"cockpit:{s.callsign}"
        if not any(n["id"] == node for n in self.graph):
            self.graph.append({"id": node, "label": f"Cockpit agent {s.callsign}",
                               "sub": "Cartesia + " + getattr(memory, "backend", "local")})

    def stations_info(self) -> list[dict]:
        return [asdict(s) for s in self.stations.values()]

    async def claim_aircraft(self) -> Station | None:
        """Seat for a person who taps "join as a pilot": a free fleet aircraft, added on demand.

        Free means nobody is connected to it and no other join claimed it in the last
        CLAIM_S seconds. None when the whole fleet is taken.
        """
        async with self._join_lock:
            now = now_ms()
            for s in FLEET_STATIONS:
                if s.callsign not in self.fleet_limit():
                    break
                taken = self.clients.get(s.id) or now - self.claims.get(s.id, -1e12) < CLAIM_S * 1000
                if taken:
                    continue
                if s.id not in self.stations:
                    self.stations[s.id] = s
                    self.clients[s.id] = set()
                    if self._started:
                        await self._start_edge(s)
                    self.send_to(None, {"type": "stations", "stations": self.stations_info(),
                                        "graph": self.graph})
                self.claims[s.id] = now
                return self.stations[s.id]
            return None

    @staticmethod
    def fleet_limit() -> set[str]:
        n = int(env("UNSTEP_MAX_AIRCRAFT") or len(scenario.FLEET))
        return {f[0] for f in scenario.FLEET[:max(1, n)]}

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for edge in self.edges.values():
            await edge.stop()
        for link in self.links.values():
            await link.close()

    async def _frequency_busy(self, edge, busy: bool) -> None:
        """Tell one cockpit agent the frequency is busy (hold and cut its voice) or free (P5)."""
        try:
            await edge.set_frequency_busy(busy)
        except Exception:
            log.exception("set_frequency_busy(%s) failed for %s", busy, getattr(edge, "callsign", "?"))

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ------------------------------------------------------------ browsers

    async def join(self, station: str, ws) -> None:
        self.clients[station].add(ws)
        self.claims.pop(station, None)
        await ws.send_json(self.snapshot(station))
        self.presence()

    def leave(self, station: str, ws) -> None:
        self.clients[station].discard(ws)
        if not self.clients[station] and station in self.key_since:
            self._key(station, False)  # a phone that drops mid-call must not hold the key down
        self.presence()

    def snapshot(self, station: str) -> dict:
        return {"type": "hello", "you": station, "now_ms": now_ms(), "live": self.live,
                "frequency": self.frequency,
                "stations": self.stations_info(), "keyed": dict(self.key_since),
                "graph": self.graph, "autonomy": self.policy.enabled if self.policy else True,
                "traces": list(self.traces.values()), "radio": self.radio_log[-30:],
                "insights": self.insights[-20:], "mic": self.live and bool(env("CARTESIA_API_KEY"))}

    def presence(self) -> None:
        self.send_to(None, {"type": "presence", "connected": {k: len(v) for k, v in self.clients.items()}})

    def send_to(self, stations: set[str] | None, message: dict) -> None:
        targets = self.stations.keys() if stations is None else stations
        for sid in targets:
            for ws in list(self.clients.get(sid, ())):
                self._spawn(self._safe_send(sid, ws, message))

    async def _safe_send(self, sid: str, ws, message: dict) -> None:
        try:
            await ws.send_json(message)
        except Exception:
            self.clients.get(sid, set()).discard(ws)

    def _status(self, text: str, to: set[str] | None = None) -> None:
        self.send_to(to, {"type": "status", "text": text, "ts": now_ms()})

    def flow(self, src: str, dst: str, label: str, event_id: str | None = None) -> None:
        self.send_to(None, {"type": "flow", "from": src, "to": dst, "label": label,
                            "event_id": event_id, "ts": now_ms()})

    # ------------------------------------------------------------ inputs from people

    async def handle(self, station: str, data: dict) -> None:
        kind = data.get("type")
        if kind == "say":
            await self.say(station, str(data.get("text", ""))[:300])
        elif kind == "mic":
            await self.mic(station, base64.b64decode(data["pcm"]), int(data["start_ms"]))
        elif kind == "mic_frame":
            await self.mic_frame(station, base64.b64decode(data["pcm"]), int(data["start_ms"]))
        elif kind == "mic_end":
            await self.mic_end(station)
        elif kind == "key":
            at = data.get("at")
            self._key(station, bool(data.get("down")), int(at) if isinstance(at, (int, float)) else None)
        elif kind == "ask" and station in self.edges:
            self._spawn(self.edges[station].ask(str(data.get("text", ""))[:200]))
        elif kind == "decide" and station == "atc":
            await self.decide(str(data["event_id"]), bool(data["approve"]))
        elif kind == "autonomy" and station == "atc" and self.policy is not None:
            self.policy.enabled = bool(data.get("on"))
            self.send_to(None, {"type": "autonomy", "on": self.policy.enabled})

    async def say(self, station: str, text: str) -> Transmission | None:
        s = self.stations.get(station)
        if s is None or s.kind == "observer" or not text.strip():
            return None
        try:
            speech = await self.tts_factory(self.voices.get(s.voice_role or "")).speak(text)
        except Exception as e:
            log.exception("TTS failed for %s's line %r", station, text)
            self._status(f"Not sent: speech failed ({type(e).__name__}). Try again.", to={station, "atc"})
            return None
        pcm = to_mono16k(speech.pcm, speech.sample_rate)
        if len(pcm) < SAMPLE_RATE * 2 // 10:  # under 100 ms: nothing would go on air (R13 item 2)
            log.warning("TTS returned %d bytes for %s's line %r; not sent", len(pcm), station, text)
            self._status("Not sent: no audio came back for that line. Try again.", to={station, "atc"})
            return None
        tx = Transmission(station, now_ms(), pcm, text=text, words=list(speech.words))
        await self.transmit(tx)
        return tx

    async def mic(self, station: str, pcm: bytes, start_ms: int) -> Transmission | None:
        s = self.stations.get(station)
        if s is None or s.kind == "observer" or not pcm:
            return None
        self._key(station, False)
        tx = Transmission(station, start_ms, to_mono16k(pcm, SAMPLE_RATE))
        await self.transmit(tx)
        return tx

    # ------------------------------------------------------------ streamed push-to-talk (P3)

    def _stream_stt(self, s: Station):
        """Cartesia streams for one push-to-talk, or None offline (then the clip path runs as before)."""
        if not (self.live and env("CARTESIA_API_KEY")):
            return None
        runways = ("33", "28L")
        if s.kind == "atc":
            from unstep.ground.tower import TowerStream

            planes = [x for x in self.stations.values() if x.kind == "aircraft"]
            return TowerStream(callsigns=[c for x in planes for c in (x.spoken, x.callsign) if c], runways=runways)
        return CartesiaManualSTT(keyterms=build_keyterms(callsigns=[s.spoken or s.callsign, s.callsign],
                                                         runways=runways))

    async def mic_frame(self, station: str, pcm: bytes, start_ms: int) -> None:
        """About 100 ms of 16 kHz PCM while the key is held. Goes to Cartesia as it arrives,
        so speech reaches STT at real-time pace by itself and finalize can run at release."""
        s = self.stations.get(station)
        if s is None or s.kind == "observer" or not pcm:
            return
        st = self.streams.get(station)
        if st is not None and st["start_ms"] != start_ms:  # a new press without an end: close the old one
            await self.mic_end(station)
            st = None
        if st is None:
            st = self.streams[station] = {"start_ms": start_ms, "chunks": [], "bytes": 0,
                                          "queue": asyncio.Queue(), "pump": None}
            stt = (self.stream_stt_factory or self._stream_stt)(s)
            if stt is not None:
                st["pump"] = self._spawn(self._pump(s, stt, st))
            self._key(station, True, start_ms)
        if st["bytes"] + len(pcm) > MAX_STREAM_S * SAMPLE_RATE * 2:
            return
        st["chunks"].append(pcm)
        st["bytes"] += len(pcm)
        st["queue"].put_nowait(pcm)

    async def _pump(self, s: Station, stt, st: dict):
        try:
            async with stt:
                while (pcm := await st["queue"].get()) is not None:
                    await stt.send_audio(pcm)
                released = now_ms()
                if s.kind == "atc":
                    result = await stt.finish(st["start_ms"], st["end_ms"], self.frequency)
                    if getattr(stt, "last_alignment", None):
                        self.alignments[result.transcript_id] = stt.last_alignment
                else:
                    result = (await stt.finalize()).text
                log.info("streamed STT for %s final %d ms after release", s.id, now_ms() - released)
                return result
        except Exception:
            log.exception("streamed STT failed for %s; the clip will be transcribed instead", s.id)
            return None

    async def mic_end(self, station: str) -> Transmission | None:
        st = self.streams.pop(station, None)
        self._key(station, False)
        if st is None:
            return None
        pcm = b"".join(st["chunks"])
        if len(pcm) < 0.3 * SAMPLE_RATE * 2:  # a tap, not a call
            if st["pump"] is not None:
                st["pump"].cancel()
            return None
        st["end_ms"] = st["start_ms"] + round(len(pcm) / 2 * 1000 / SAMPLE_RATE)
        st["queue"].put_nowait(None)
        tx = Transmission(station, st["start_ms"], to_mono16k(pcm, SAMPLE_RATE))
        if st["pump"] is not None:
            self.stream_results[tx.tx_id] = st["pump"]
        await self.transmit(tx)
        return tx

    async def _streamed(self, tx: Transmission):
        """The transcript streamed during the key press, or None (offline, failed or too slow)."""
        task = self.stream_results.pop(tx.tx_id, None)
        if task is None:
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(task), STREAM_FINAL_S)
        except Exception:
            return None

    async def transmit(self, tx: Transmission) -> None:
        # Everyone else hears it now; overlapping clips mix in the listener's browser.
        listeners = {sid for sid, s in self.stations.items() if sid != tx.station}
        self.send_to(listeners, {"type": "onair", "station": tx.station, "tx_id": tx.tx_id,
                                 "start_ms": tx.start_ms, "end_ms": tx.end_ms,
                                 "audio": wav_b64(tx.pcm, SAMPLE_RATE)})
        self.send_to({tx.station}, {"type": "transmitting", "tx_id": tx.tx_id, "text": tx.text,
                                    "end_ms": tx.end_ms})
        self.flow(tx.station if tx.station == "atc" else f"pilot:{tx.station}", "radio", "voice")
        self.pending.append(tx)
        self._wake.set()

    def _key(self, station: str, down: bool, at: int | None = None) -> None:
        """Radio key up or down, shared with every seat the moment it happens.

        Phones show "Tower is talking" from this, and two keys down at once is a
        stepped-on call known within one network hop, long before any transcript.
        `at` is the press time on the hub clock as the phone measured it (after its
        clock sync); the gap to now is the one-way delay from that phone.
        """
        received = now_ms()
        s = self.stations.get(station)
        if s is None or s.kind == "observer":
            return
        if down:
            if station in self.key_since:
                return
            pressed = at if at is not None and abs(received - at) < 5000 else received
            self.key_since[station] = pressed
            self.keyed.add(station)
        else:
            if self.key_since.pop(station, None) is None:
                return
            self.keyed.discard(station)
        if len(self.key_since) == (1 if down else 0):  # the frequency just became busy or free (P5)
            for edge in list(self.edges.values()):
                self._spawn(self._frequency_busy(edge, down))
        self._wake.set()
        self.send_to(None, {"type": "keyed", "station": station, "down": down,
                            "keyed": dict(self.key_since), "ts": received})
        if down and len(self.key_since) >= 2:
            alert = {"type": "stepon_live", "stations": sorted(self.key_since),
                     "since_ms": max(self.key_since.values()), "detected_ms": received,
                     "uplink_ms": received - self.key_since[station]}
            self.stepons = [*self.stepons[-19:], alert]
            self.send_to(None, alert)

    async def decide(self, event_id: str, approve: bool) -> None:
        trace = self.traces.get(event_id)
        if trace is None or trace.get("proposal") is None:
            self._status(f"{event_id} has no proposal", to={"atc"})
            return
        p = ProposedDirective(**trace["proposal"])
        msg = (ApprovedDirective(event_id=event_id, instruction_text=p.instruction_text, slots=p.slots,
                                 approved_by="controller", approved_via="click") if approve
               else RejectedDirective(event_id=event_id, rejected_by="controller", rejected_via="click"))
        await self.links["dashboard"].send(msg)

    # ------------------------------------------------------------ the frequency

    async def _scheduler(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self.pending:
                wait_ms = max(t.end_ms for t in self.pending) + GAP_MS - now_ms()
                if wait_ms > 0 or self.keyed:
                    try:
                        await asyncio.wait_for(self._wake.wait(), max(wait_ms, 50) / 1000)
                        self._wake.clear()
                    except asyncio.TimeoutError:
                        pass
                    continue
                batch, self.pending = self.pending, []
                for cluster in clusters(batch):
                    self._spawn(self.process(cluster))

    async def process(self, cluster: list[Transmission]) -> None:
        mx = mix(cluster)
        summary = {"type": "radio", "t0": mx.t0,
                   "transmissions": [{"station": t.station, "text": t.text, "start_ms": t.start_ms,
                                      "end_ms": t.end_ms} for t in cluster],
                   "overlaps": [asdict(o) for o in mx.overlaps]}
        self.radio_log.append(summary)
        self.send_to(None, summary)
        jobs = [self._tower(t) for t in cluster if self.stations[t.station].kind == "atc"]
        towers = [t for t in cluster if self.stations[t.station].kind == "atc"]
        for s in self.stations.values():
            if s.kind == "aircraft" and mx.heard_by(s.id):
                jobs.append(self._cockpit_hears(s.callsign, mx, towers))
        for t in cluster:
            if self.stations[t.station].kind == "aircraft":
                jobs.append(self._pilot_spoke(t, clean=not mx.overlaps))
        await asyncio.gather(*jobs, return_exceptions=False)

    async def _tower(self, tx: Transmission) -> None:
        self.flow("radio", "tower_stt", "tower audio")
        callsign = parse_callsign(tx.text) if tx.text else None
        streamed = await self._streamed(tx)
        if streamed is not None:
            transcript = streamed
        elif self.tower_transcriber is not None or (self.live and env("CARTESIA_API_KEY")):
            from unstep.ground.tower import TowerTranscriber

            transcriber = self.tower_transcriber or TowerTranscriber(runways=("33", "28L"),
                                                                     realtime=self.realtime_replay)
            transcript = await transcriber.transcribe(pcm16(tx.pcm), tx.start_ms, tx.end_ms,
                                                      self.frequency, callsign)
            if getattr(transcriber, "last_alignment", None):
                self.alignments[transcript.transcript_id] = transcriber.last_alignment
        else:
            transcript = known_transcript(tx, self.frequency, callsign)
        if transcript.callsign is None:
            transcript = transcript.model_copy(update={"callsign": parse_callsign(transcript.text)})
        self.transcripts[transcript.transcript_id] = transcript
        await self.links["tower"].send(transcript)
        report = self.alignments.pop(transcript.transcript_id, None)
        if report is not None:
            from unstep.ground.tower import alignment_audit

            await self.links["tower"].send(alignment_audit(transcript, report))

    async def _cockpit_hears(self, callsign: str, mx: Mix, towers: list[Transmission]) -> None:
        edge = self.edges[callsign]
        if self.live and env("CARTESIA_API_KEY"):
            terms = build_keyterms(callsigns=[callsign, scenario.SPOKEN_CALLSIGN], runways=["33", "28L"])
            edge.manual_stt_factory = lambda: CartesiaManualSTT(keyterms=terms)
        else:
            if towers:
                heard = heard_text(towers[0], mx.overlaps)
            elif mx.overlaps:
                heard = "[static]"
            else:
                heard = " ".join(t.text or "" for t in mx.transmissions)
            edge.manual_stt_factory = lambda h=heard: FakeManualSTT([h])
        self.flow("radio", f"cockpit:{callsign}", "what this aircraft heard")
        await edge.run_audio(ArraySource(mx.pcm, t0=mx.t0, squelch=KeyedSquelch(mx.any_keyed)),
                             realtime=self.live and self.realtime_replay)

    async def _pilot_spoke(self, tx: Transmission, clean: bool) -> None:
        turns = self.turns.get(tx.station)
        if turns is None or not clean or turns.listening == 0:
            self.stream_results.pop(tx.tx_id, None)
            return  # a stepped-on readback is lost, as it would be on the radio
        text = tx.text or await self._streamed(tx)
        if text is None and self.live and env("CARTESIA_API_KEY"):
            async with CartesiaManualSTT(keyterms=build_keyterms(callsigns=[tx.station], runways=["33", "28L"])) as stt:
                for i in range(0, len(tx.pcm), 1600):
                    await stt.send_audio(pcm16(tx.pcm[i:i + 1600]))
                    if self.realtime_replay:
                        await asyncio.sleep(0.1)
                text = (await stt.finalize()).text
        if text:
            await turns.queue.put((text, pcm16(tx.pcm)))

    async def _ticker(self) -> None:
        """Marks proposals that ran out of time, so the controller sees it."""
        while True:
            await asyncio.sleep(1)
            now = now_ms()
            for trace in self.traces.values():
                if trace["status"] == "needs_you" and trace.get("deadline_ms") and now > trace["deadline_ms"]:
                    self._step(trace, "gateway", "expired", "No decision in time: nothing was sent")
                    trace["status"] = "expired"
                    self.send_to(None, {"type": "trace", "trace": trace})

    # ------------------------------------------------------------ explainability

    def _trace(self, event_id: str, callsign: str | None = None) -> dict:
        trace = self.traces.get(event_id)
        if trace is None:
            trace = self.traces[event_id] = {"event_id": event_id, "callsign": callsign, "status": "detected",
                                             "created_ms": now_ms(), "steps": [], "proposal": None,
                                             "policy": None, "readbacks": [], "timings": []}
        if callsign and not trace.get("callsign"):
            trace["callsign"] = callsign
        return trace

    @staticmethod
    def _time(trace: dict, stage: str, at_ms: int | None, ms: float | None = None, by: str | None = None) -> None:
        """One mark on the event's timeline, hub clock. `ms` is a measured duration where there is one
        (Moss search, TTS first audio, Elastic's own time); the console draws these as a waterfall."""
        if at_ms is None:
            return
        trace.setdefault("timings", []).append({"stage": stage, "at_ms": int(at_ms), "ms": ms, "by": by})

    @staticmethod
    def _step(trace: dict, actor: str, kind: str, text: str, **data) -> None:
        trace["steps"].append({"ts": now_ms(), "actor": actor, "kind": kind, "text": text, "data": data})

    async def _observe(self, env_, msg) -> None:
        """Every gateway message: animate the graph and build the evidence chain."""
        self.flow("gateway", "elastic", "stored")
        event_id = getattr(msg, "event_id", None)
        if isinstance(msg, TowerTranscript):
            self.flow("tower_stt", "gateway", "TowerTranscript")
            for dst in ("ground", "policy", "monitor"):
                self.flow("gateway", dst, "TowerTranscript")
            self.send_to(None, {"type": "transcript", "transcript": msg.model_dump(mode="json")})
            return
        if isinstance(msg, Insight):
            self.flow("monitor", "gateway", "Insight")
            self.flow("gateway", "controller", "Insight")
            item = msg.model_dump(mode="json")
            self.insights.append(item)
            self.send_to(None, {"type": "insight", "insight": item})
            return
        if isinstance(msg, PilotQuery):
            self.flow(f"cockpit:{msg.callsign}", "gateway", "PilotQuery")
            self.send_to(None, {"type": "query", "query": msg.model_dump(mode="json")})
            return
        if event_id is None:
            return
        if isinstance(msg, AnomalyEvent):
            trace = self._trace(event_id, msg.callsign)
            self.flow(f"cockpit:{msg.callsign}", "gateway", "AnomalyEvent", event_id)
            for dst in ("ground", "policy", "monitor"):
                self.flow("gateway", dst, "AnomalyEvent", event_id)
            hint = msg.local_hint
            trace["event"] = msg.model_dump(mode="json")
            self._step(trace, f"cockpit:{msg.callsign}", "detected",
                       f"Stepped-on call detected. Heard: \"{msg.heard_text}\"",
                       overlap_ms=msg.overlap_end - msg.overlap_start)
            self._time(trace, "call_start", msg.squelch_open, by="radio")
            keys = next((k for k in reversed(self.stepons)
                         if msg.squelch_open - 1000 <= k["since_ms"] <= msg.squelch_close), None)
            if keys is not None:  # only push-to-talk keys give this; typed lines have no key press
                self._time(trace, "keys_overlap", keys["since_ms"], by="radio")
                self._time(trace, "keys_detected", keys["detected_ms"],
                           ms=keys["detected_ms"] - keys["since_ms"], by="hub")
            self._time(trace, "stepped_on", msg.overlap_start, ms=msg.overlap_end - msg.overlap_start,
                       by=f"cockpit:{msg.callsign}")
            self._time(trace, "call_end", msg.squelch_close, by="radio")
            self._time(trace, "event_raised", env_.ts, ms=env_.ts - msg.squelch_close, by=f"cockpit:{msg.callsign}")
            if hint.kind == "restrictive":
                self._step(trace, f"cockpit:{msg.callsign}", "hint",
                           f"Local hint \"{hint.text}\" from Moss record {hint.source_doc_id} "
                           f"in {hint.moss_ms} ms", source_text=hint.source_text, moss_ms=hint.moss_ms)
                self._time(trace, "hint", env_.ts, ms=hint.moss_ms, by="moss")
        else:
            # Only a detected blocked call starts a trace; speech, radio and query audits do not.
            trace = self.traces.get(event_id)
            if trace is None:
                return
        cs = trace.get("callsign")
        if isinstance(msg, ProposedDirective):
            self.flow("ground", "gateway", "ProposedDirective", event_id)
            self.flow("gateway", "policy", "ProposedDirective", event_id)
            trace["proposal"] = msg.model_dump(mode="json")
            tower = self.transcripts.get(msg.transcript_id or "")
            if tower is not None:
                trace["tower"] = tower.model_dump(mode="json")
                self._time(trace, "tower_transcript", tower.ptt_end, by="cartesia")
            self._time(trace, "proposed", env_.ts, by="ground")
            trace["status"] = "proposed"
            self._step(trace, "ground", "proposed",
                       f"Proposed \"{msg.instruction_text}\" ({msg.confidence}: {msg.confidence_method})",
                       blocked_words=msg.blocked_words, citation=msg.rule_citation)
        elif isinstance(msg, AuditRecord) and msg.stage == "policy":
            trace["policy"] = msg.payload
            auto = msg.payload.get("decision") == "auto_relay"
            self._time(trace, "policy", env_.ts, ms=msg.latency_ms, by="policy")
            if auto:
                self._step(trace, "policy", "auto_relay",
                           "Auto-relay: every check passed, this repeats the controller's own words")
            else:
                trace["status"] = "needs_you"
                trace["deadline_ms"] = env_.ts + int(self.gateway.pending_ttl_ms)
                self.flow("policy", "controller", "needs you", event_id)
                self.flow("gateway", "controller", "ProposedDirective", event_id)
                self._step(trace, "policy", "escalate", "Needs the controller: " + "; ".join(msg.payload.get("reasons", [])))
                self._spawn(self._prompt_controller(trace))
        elif isinstance(msg, ApprovedDirective):
            src = "policy" if msg.approved_via == "auto" else "controller"
            self.flow(src, "gateway", f"Approved ({msg.approved_via})", event_id)
            self.flow("gateway", f"cockpit:{cs}", "ApprovedDirective", event_id)
            trace["status"] = "auto_relayed" if msg.approved_via == "auto" else "approved"
            trace["decision"] = msg.model_dump(mode="json")
            self._step(trace, src, "approved", f"Approved by {msg.approved_by} ({msg.approved_via})")
            self._time(trace, "approved", env_.ts, by=src)
        elif isinstance(msg, RejectedDirective):
            self.flow("controller", "gateway", "Rejected", event_id)
            self.flow("gateway", f"cockpit:{cs}", "RejectedDirective", event_id)
            trace["status"] = "rejected"
            trace["decision"] = msg.model_dump(mode="json")
            self._step(trace, "controller", "rejected", f"Rejected by {msg.rejected_by}: cockpit asks to say again")
            self._time(trace, "rejected", env_.ts, by="controller")
        elif isinstance(msg, ReadbackResult):
            self.flow(f"cockpit:{cs}", "gateway", "ReadbackResult", event_id)
            self.flow("gateway", "monitor", "ReadbackResult", event_id)
            trace["readbacks"].append(msg.model_dump(mode="json"))
            trace["status"] = "confirmed" if msg.match else "readback_wrong"
            self._step(trace, f"cockpit:{cs}", "readback",
                       f"Readback {'correct' if msg.match else 'incorrect'}: \"{msg.readback_text}\"")
            self._time(trace, "readback", env_.ts, by=f"cockpit:{cs}")
        elif isinstance(msg, AuditRecord) and msg.stage == "directive_spoken":
            trace["status"] = "delivered" if trace["status"] in ("approved", "auto_relayed") else trace["status"]
            self._step(trace, f"cockpit:{cs}", "delivered", "Directive spoken in the pilot's left ear",
                       first_audio_ms=msg.latency_ms)
            self._time(trace, "spoken", env_.ts, ms=msg.latency_ms, by="cartesia")
        elif isinstance(msg, AuditRecord) and msg.stage == "readback_percolate":
            self.flow("gateway", "elastic", "percolate readback", event_id)
            agrees = msg.payload.get("match") == msg.payload.get("slot_check_match")
            self._step(trace, "elastic", "percolate",
                       f"Elastic {'matched' if msg.payload.get('match') else 'did not match'} the readback against "
                       f"the stored directive ({msg.actor}, {msg.latency_ms} ms): "
                       f"{'agrees with' if agrees else 'disagrees with'} the slot check", **msg.payload)
            self._time(trace, "elastic_check", env_.ts, ms=msg.latency_ms, by=msg.actor)
        elif isinstance(msg, AuditRecord) and msg.stage == "ground_agents":
            self.flow("ground", "elastic", "audit", event_id)
        else:
            return
        self.send_to(None, {"type": "trace", "trace": trace})

    async def _prompt_controller(self, trace: dict) -> None:
        p = trace.get("proposal") or {}
        text = f"Needs you. Blocked call to {trace.get('callsign')}: {p.get('instruction_text', '')}. Approve?"
        try:
            speech = await self._advisory_tts().speak(text)
            self.send_to({"atc"}, {"type": "controller_audio", "text": text,
                                   "audio": wav_b64(np.frombuffer(speech.pcm, dtype="<i2"), speech.sample_rate)})
        except Exception:
            log.exception("controller prompt failed")
            self.send_to({"atc"}, {"type": "controller_audio", "text": text, "audio": None})


def known_transcript(tx: Transmission, frequency: str, callsign: str | None) -> TowerTranscript:
    """Tower transcript from typed words (no Cartesia): exact text, word times from the speech."""
    text = tx.text or ""
    if tx.words:
        words = [Word(word=w, start=s, end=e) for w, s, e in tx.words]
    else:
        tokens = text.split()
        per = (tx.end_ms - tx.start_ms) / 1000 / max(1, len(tokens))
        words = [Word(word=w, start=i * per, end=(i + 1) * per) for i, w in enumerate(tokens)]
    return TowerTranscript(transcript_id=f"tx-{uuid.uuid4().hex}", frequency=frequency, callsign=callsign,
                           ptt_start=tx.start_ms, ptt_end=tx.end_ms, text=text, words=words)
