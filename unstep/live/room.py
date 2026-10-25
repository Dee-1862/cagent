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
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable

import numpy as np
import soundfile as sf

from unstep import scenario
from unstep.clock import now_ms
from unstep.config import ROOT, env, idle_land_s, moss_aircraft, radio_sound, realtime_replay
from unstep.contracts import (AnomalyEvent, ApprovedDirective, AuditRecord, Insight, PilotQuery,
                              ProposedDirective, ReadbackResult, RejectedDirective, TowerTranscript,
                              VoiceApproval, Word, unwrap, wrap)
from unstep.cockpit.audio import SAMPLE_RATE, ArraySource
from unstep.cockpit.edge import AudioOut, CockpitEdge, Line
from unstep.cockpit.memory import LocalMemory, create_memory
from unstep.cockpit.monitor import FrequencyMonitor
from unstep.cockpit.phraseology import parse_callsign
from unstep.cockpit.stt import CartesiaManualSTT, FakeManualSTT, TurnEvent, build_keyterms
from unstep.cockpit.tts import SAMPLE_RATE as TTS_SAMPLE_RATE, FakeTTS, chime
from unstep.ground.mock_agents import propose
from unstep.ground.policy import PolicyAgent
from unstep.live.radio import (KeyedSquelch, LiveMix, Mix, Transmission, clusters, heard_text, mix, radio_voice,
                               to_mono16k)

log = logging.getLogger("unstep.live")

VOICES_FILE = ROOT / "assets" / "clips" / "real" / "voices.json"
GAP_MS = 300  # quiet time after the last transmission before a cluster is processed
LEVEL_MS = 50  # one waveform bar per 50 ms of audio
CHIME_MS = 220  # length of the advisory chime (unstep.cockpit.tts.chime default)
RECOVERY_STALE_MS = 30_000  # C1: a recovery line older than this is dropped, never spoken late
RECOVERY_WAIT_GAP_MS = 10_000  # how long a recovery waits for the controller to stop talking
TRANSCRIPT_WAIT_S = 12.0  # how long ground agents wait for the tower transcript
READBACK_WAIT_S = 45.0  # how long a cockpit waits for the pilot's readback
CLAIM_S = 20.0  # a seat handed out by join() stays reserved this long for its websocket
SEAT_FREE_S = 20.0  # a walk-up pilot's seat is freed when its phone has been gone this long
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
TEAM_STATIONS = {"N123AB", "H456"}  # the team's two planes: never freed or reset (R22)
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

    async def speak(self, text, context_id=None, on_chunk=None, **options):
        # options: the cockpit voice's language and speed (Rishit's d711e89), passed through untouched
        async with self._lock:
            return await self.engine.speak(text, context_id=context_id, on_chunk=on_chunk, **options)

    def __getattr__(self, name):
        return getattr(self.engine, name)


class StreamingTTS(SerialTTS):
    """SerialTTS that also streams each advisory to the pilot's phone as Cartesia sends it.

    Without this the phone got the advisory only after the whole line was synthesized
    (R14: about 1.5 s from approval to sound while first audio was 131 ms). Messages:
    `advisory_chunk {id, seq, sample_rate, pcm}` (mono pcm_s16le, base64; the first chunk
    starts with the advisory chime) and `advisory_end {id, cancelled}`. The full clip still
    follows as `advisory_audio` with `streamed: true`, for "play again" and older pages.
    """

    def __init__(self, engine, room: "LiveRoom", station: str):
        super().__init__(engine)
        self.room, self.station = room, station

    async def speak(self, text, context_id=None, on_chunk=None, **options):
        async with self._lock:
            sample_rate = getattr(self.engine, "sample_rate", TTS_SAMPLE_RATE)
            stream_id = context_id or uuid.uuid4().hex
            seq = 0

            def chunk(pcm: bytes) -> None:
                nonlocal seq
                if on_chunk:
                    on_chunk(pcm)
                if not pcm:
                    return
                if seq == 0:
                    pcm = chime(sample_rate).tobytes() + pcm
                self.room.send_to({self.station}, {"type": "advisory_chunk", "id": stream_id, "seq": seq,
                                                   "sample_rate": sample_rate,
                                                   "pcm": base64.b64encode(pcm).decode()})
                seq += 1

            cancelled = True
            started = now_ms()
            samples = 0
            original_chunk = chunk

            def counted(pcm: bytes) -> None:
                nonlocal samples
                samples += len(pcm) // 2
                original_chunk(pcm)

            try:
                result = await self.engine.speak(text, context_id=context_id, on_chunk=counted, **options)
                cancelled = bool(getattr(result, "cancelled", False))
                return result
            finally:
                if seq:
                    self.room.send_to({self.station}, {"type": "advisory_end", "id": stream_id,
                                                       "chunks": seq, "cancelled": cancelled})
                    if not cancelled:
                        self.room.streamed_advisory.add(self.station)
                    self.room.advisory_report(self.station, stream_id, started,
                                              samples * 1000 / sample_rate + CHIME_MS, cancelled)


class BrowserAudioOut(AudioOut):
    """Sends what the cockpit agent speaks to that pilot's browser (left ear already)."""

    def __init__(self, room: "LiveRoom", station: str):
        super().__init__(path=None)
        self.room, self.station = room, station

    def add(self, stereo: np.ndarray, sample_rate: int) -> None:
        streamed = self.station in self.room.streamed_advisory  # already heard chunk by chunk
        self.room.streamed_advisory.discard(self.station)
        self.room.send_to({self.station}, {"type": "advisory_audio", "audio": wav_b64(stereo, sample_rate),
                                           "streamed": streamed})


class LiveEdge(CockpitEdge):
    """CockpitEdge that also shows its transcript lines in the pilot's browser."""

    room: "LiveRoom | None" = None

    async def audit(self, event_id: str, stage: str, latency_ms=None, **payload) -> None:
        if self.room is not None and stage in ("held", "released"):  # C5: how long it waited for a gap
            self.room.last_wait[self.callsign] = float(payload.get("waited_ms") or 0.0)
        await super().audit(event_id, stage, latency_ms, **payload)

    def _note(self, party: str, text: str, **latency: float) -> Line:
        line = super()._note(party, text, **latency)
        if self.room is not None:
            self.room.send_to({self.callsign}, {"type": "cockpit_line", **asdict(line)})
        return line


class GroundAgents:
    """Intercept and Compliance for the live room.

    Matches each blocked call with the controller's own transmission and proposes
    the directive with unstep.ground.mock_agents.propose. With UNSTEP_ELASTIC_AGENTS=1
    the Elastic Workflow's agents (B5, unstep.ground.elastic_agents) then add the FAA
    citation and can lower the confidence; they never write the instruction.
    """

    def __init__(self, send, wait_s: float = TRANSCRIPT_WAIT_S, elastic=None):
        self.send, self.wait_s = send, wait_s
        self.elastic = elastic  # unstep.ground.elastic_agents.ElasticAgents, or None for local only
        self.on_late = None  # async (event_id, merged proposal, AgentsResult): the room draws a late citation
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
        agents = None
        late = False
        rule = None
        if self.elastic is not None and transcript is not None:
            from unstep.cockpit.phraseology import is_restrictive
            from unstep.ground.elastic_agents import merge, with_closest_rule, with_stored_rule

            # Hybrid search (+ rerank) of the FAA order: the closest rule in the time of a search, before any
            # language model. The card shows it as a search result; the Compliance agent can still replace it.
            hit = await self.elastic.rule_for(proposal.instruction_text)
            if hit is not None and hit.paragraph:
                rule = {"paragraph": hit.paragraph, "title": hit.title}
                proposal = with_stored_rule(proposal, hit)
            else:  # no stored rule for this instruction: fall back to the hybrid search
                rule = await self.elastic.cite(proposal.instruction_text)
                proposal = with_closest_rule(proposal, rule)

            # The agents can veto (Intercept says no match). If the policy might relay this by itself
            # (restrictive and high confidence), the proposal still waits for them, as before. Otherwise
            # a person decides anyway, so the card goes out at once and the citation follows (3a).
            might_auto_relay = is_restrictive(proposal.slots.action) and proposal.confidence == "high"
            if might_auto_relay or self.on_late is None:
                agents = await self.elastic.blocked_call(event, transcript, proposal, rule=rule)
                proposal = merge(proposal, agents)
            else:
                late = True
        await self.send(proposal)
        await self.send(self._audit(event, transcript, proposal, started, agents,
                                    "Elastic agents pending (late)" if late else None))
        if late:
            task = asyncio.create_task(self._late(event, transcript, proposal, started, rule))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    @staticmethod
    def _audit(event, transcript, proposal, started, agents, note=None) -> AuditRecord:
        return AuditRecord(event_id=event.event_id, stage="ground_agents", actor="agents",
                           latency_ms=now_ms() - started, payload={
                               "matched_transcript": transcript.transcript_id if transcript else None,
                               "tower_text": transcript.text if transcript else None,
                               "blocked_words": proposal.blocked_words,
                               "confidence": proposal.confidence,
                               "confidence_method": proposal.confidence_method,
                               "agents": ("Elastic Workflow unstep-blocked-call" if agents
                                          else note or "local intercept + compliance"),
                               **({"workflow_execution_id": agents.execution_id,
                                   "workflow_ms": agents.took_ms,
                                   "intercept": agents.intercept, "compliance": agents.compliance,
                                   "citation": proposal.rule_citation} if agents else {})})

    async def _late(self, event, transcript, proposal, started, rule=None) -> None:
        """The card is already on screen; add the agents' citation when it arrives. The instruction never changes."""
        from unstep.ground.elastic_agents import late_wait_s, merge

        try:
            agents = await self.elastic.blocked_call(event, transcript, proposal, wait_s=late_wait_s(), rule=rule)
            if agents is None:
                return
            merged = merge(proposal, agents)
            await self.send(self._audit(event, transcript, merged, started, agents))
            await self.on_late(event.event_id, merged, agents)
        except Exception:
            log.exception("late Elastic agents for %s failed; the local proposal stands", event.event_id)


class LiveRoom:
    def __init__(self, gateway, *, live: bool, stations: list[Station] | None = None,
                 tts_factory: Callable[[str | None], Any] | None = None, advisory_tts=None,
                 tower_transcriber=None, frequency: str = scenario.FREQUENCY,
                 stream_stt_factory: Callable[[Station], Any] | None = None,
                 caption_turns_factory: Callable[[Station], Any] | None = None):
        self.gateway, self.live, self.frequency = gateway, live, frequency
        self.stations = {s.id: s for s in (stations or DEFAULT_STATIONS)}
        self.voices = station_voices()
        self.tts_factory = tts_factory or self._default_tts
        self.advisory_tts = advisory_tts
        self.tower_transcriber = tower_transcriber
        self.stream_stt_factory = stream_stt_factory
        self._voice_tts: dict[str, Any] = {}  # voice id -> shared Cartesia speech connection
        self._controller_voice = None
        # Live caption source: "manual" shows the text deltas of the same ink-2 stream that makes the final
        # text (about every 0.5 s); "turns" also streams the audio to Cartesia's turns endpoint and shows its
        # turn.update text, for display only. Measure both with scripts/caption_probe.py before switching.
        self.caption_source = (env("UNSTEP_CAPTION_SOURCE") or "manual").strip().lower()
        self.caption_turns_factory = caption_turns_factory
        self.streams: dict[str, dict] = {}  # station -> push-to-talk stream in progress (P3)
        self.stream_results: dict[str, asyncio.Task] = {}  # tx_id -> streamed transcript
        self.key_log: list[tuple[str, int, int]] = []  # (station, down_ms, up_ms), recent key presses
        self.last_wait: dict[str, float] = {}  # callsign -> ms its last advisory waited for a gap (C5)
        self.advisory_reports: list[dict] = []
        self._cue_cache: dict[tuple[str, str], str] = {}  # (station, phrase) -> WAV base64
        self.languages: dict[str, str | None] = {}
        # Recording-session mode (unstep/live/recording.py): who is speaking, and who consented
        self.recorder = None
        self.speakers: dict[str, dict] = {}  # station -> {name, consent}
        self.prompt_at_press: dict[str, dict | None] = {}  # station -> pilot language for the private repeat
        self.streamed_advisory: set[str] = set()
        # R27 3a: the frequency as it is on air, fed to each cockpit's STT during the call
        self.live_mix: LiveMix | None = None
        self.mix_streams: dict[str, dict] = {}  # callsign -> {queue, task}
        self.mix_stt_factory: Callable[[str], Any] | None = None  # tests; live uses Cartesia
        self.mix_final_ms: dict[str, int] = {}  # callsign -> ms from cluster end to its on-air STT final  # stations whose last advisory was streamed (R14)
        self.alignments: dict[str, dict] = {}
        self.stt_final: dict[str, tuple[int, int]] = {}  # transcript_id -> (final at ms, ms it took) (S1)  # transcript_id -> tower word alignment report (P7b)
        # W3: replays to the manual STT endpoint go as fast as possible unless UNSTEP_REALTIME_REPLAY=1
        self.realtime_replay = realtime_replay()
        self.radio_sound = radio_sound()  # listeners hear VHF-shaped audio; STT gets the clean mix
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
        self.elastic_agents = None  # Elastic Workflow ground agents when UNSTEP_ELASTIC_AGENTS=1 (B5)
        self.monitor: FrequencyMonitor | None = None
        self.flight_log = None  # unstep.live.flightlog.FlightLog, created in start()  # writes the hub's freq-<frequency> session
        self.graph = [dict(n) for n in GRAPH_NODES]
        self.key_since: dict[str, int] = {}  # station -> hub time its radio key went down
        self.stepons: list[dict] = []  # live two-keys-down detections, matched to events for timings
        self.claims: dict[str, float] = {}  # station -> hub time join() handed it out
        self._join_lock = asyncio.Lock()
        self._moss_used = 0
        self.last_active: dict[str, float] = {}  # station -> time.monotonic() of its last input
        self._shared_moss = None
        self.reset_at = 0  # hub time of the last presenter reset; /live/stats never counts before it

    # ------------------------------------------------------------ setup

    def _default_tts(self, voice_id: str | None):
        """One Cartesia connection per station voice, reused for every typed line. A new, never-closed
        connection per line leaked sockets until Cartesia answered HTTP 429 (Rishit's benchmark hit it)."""
        if self.live and env("CARTESIA_API_KEY") and voice_id:
            tts = self._voice_tts.get(voice_id)
            if tts is None:
                from unstep.cockpit.tts import CartesiaTTS

                tts = self._voice_tts[voice_id] = SerialTTS(CartesiaTTS(voice_id=voice_id))
            return tts
        return FakeTTS(sample_rate=SAMPLE_RATE)

    def _controller_tts(self):
        """The controller's spoken prompts share one connection too (one per proposal leaked before)."""
        if self.advisory_tts is not None:
            return self.advisory_tts
        if self._controller_voice is None:
            self._controller_voice = SerialTTS(self._advisory_tts())
        return self._controller_voice

    @staticmethod
    async def _close_engine(edge) -> None:
        """Close the speech connection a cockpit agent opened for itself (walk-up planes come and go, and
        every one that leaves must hand its connection back or Cartesia answers HTTP 429 later)."""
        engine = getattr(edge, "tts", None)
        for _ in range(4):  # TimedTTS -> StreamingTTS -> engine
            inner = getattr(engine, "engine", None)
            if inner is None:
                break
            engine = inner
        close = getattr(engine, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                log.debug("closing a cockpit speech connection failed", exc_info=True)

    async def _close_voices(self) -> None:
        """Close every Cartesia speech connection the hub opened (on stop)."""
        engines = [t.engine for t in self._voice_tts.values()]
        if self._controller_voice is not None:
            engines.append(self._controller_voice.engine)
        for engine in engines:
            close = getattr(engine, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    log.debug("closing a speech connection failed", exc_info=True)
        self._voice_tts.clear()
        self._controller_voice = None

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
            from unstep.ground.elastic_agents import elastic_agents_from_env

            self.elastic_agents = elastic_agents_from_env() if self.live else None
            ground = GroundAgents(lambda m: self.links["agents"].send(m), elastic=self.elastic_agents)
            ground.on_late = self._agents_cited
            self.links["agents"] = InProcLink(gw, "agents", ground.on_message)
            self.policy = PolicyAgent(lambda m: self.links["policy"].send(m))
            self.links["policy"] = InProcLink(gw, "policy", self.policy.on_message,
                                              on_error=lambda t: self._status(f"policy: {t}"))
            # The hub's frequency session (freq-<frequency>): a Moss session when live, written
            # only by the Frequency Monitor, never pushed. Local memory offline or if Moss fails.
            if self.live and self._shared_moss is None:
                self._shared_moss = create_memory()  # one client for the monitor and every plane
            monitor = self.monitor = FrequencyMonitor(self._shared_moss if self.live else LocalMemory())
            from unstep.live.flightlog import FlightLog

            # Flight log: each plane's memory is copied here when its flight ends; the only session we push
            self.flight_log = FlightLog(self._shared_moss if self.live else LocalMemory(), self.frequency)

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
            self._spawn(self._landing_sweeper())
            self._started = True

    async def _start_edge(self, s: Station) -> None:
        """One cockpit agent per aircraft, with its own flight session."""
        turns = StationTurns()
        # A Moss session indexes in memory and only reaches the cloud index on push_index(),
        # which per-aircraft sessions never call, so the plan's index limit does not cap them
        # (six real sessions checked by Rishit, R3). UNSTEP_MOSS_AIRCRAFT (default 6) planes get Moss.
        use_moss = self.live and self._moss_used < moss_aircraft()
        # One Moss client (one embedding model in memory) shared by every plane; each plane still
        # has its own flight session. A client per plane ran Render's 512 MB instance out of memory.
        if use_moss and self._shared_moss is None:
            self._shared_moss = create_memory()
        memory = self._shared_moss if use_moss else LocalMemory()
        self._moss_used += 1

        def build(mem):
            e = LiveEdge(callsign=s.callsign, frequency=self.frequency,
                         link=InProcLink(self.gateway, "cockpit"), memory=mem,
                         tts=StreamingTTS(self._advisory_tts(), self, s.id), turn_stt_factory=turns.factory,
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
        if self.languages.get(s.id):
            edge.set_language(self.languages[s.id])
        if self.key_since:  # joined while someone is talking: hold its advisories too
            self._spawn(self._frequency_busy(edge, True))
        node = f"cockpit:{s.callsign}"
        if not any(n["id"] == node for n in self.graph):
            self.graph.append({"id": node, "label": f"Cockpit agent {s.callsign}",
                               "sub": "Cartesia + " + getattr(memory, "backend", "local")})

    def stations_info(self) -> list[dict]:
        return [asdict(s) for s in self.stations.values()]

    async def say_cue(self, station: str, name: str) -> dict | None:
        """C2: a short spoken cue line for an eyes-free pilot, in Unstep's voice, left ear only.
        Only the agreed phrases (R20) can be spoken; nothing the client sends is read out."""
        s = self.stations.get(station)
        if s is None or s.kind != "aircraft":
            return None
        phrases = {"joined": f"You are {s.name or s.spoken or s.callsign}.", "busy": "Frequency busy.",
                   "talked_over": "You were talked over.", "back_online": "Back online.",
                   "mic_off": "Tap a line to talk."}
        text = phrases.get(name)
        if text is None:
            return None
        key = (station, text)
        audio = self._cue_cache.get(key)
        if audio is None:
            try:
                speech = await self._controller_tts().speak(text)
            except Exception:
                log.exception("cue speech failed for %s", station)
                return None
            mono = np.frombuffer(speech.pcm, dtype="<i2")
            stereo = np.zeros((len(mono), 2), dtype=np.int16)
            stereo[:, 0] = mono  # left ear only, like every Unstep message
            audio = self._cue_cache[key] = wav_b64(stereo, speech.sample_rate)
        msg = {"type": "cue_audio", "name": name, "text": text, "audio": audio}
        self.send_to({station}, msg)
        return msg

    def advisory_report(self, station: str, stream_id: str, started_ms: int, spoke_ms: float,
                        cancelled: bool) -> dict:
        """C5: one line per private advisory for the console: how long it waited for a gap,
        how long it spoke, and how much of it overlapped anyone talking on the frequency."""
        end = started_ms + spoke_ms
        overlapped, by = 0.0, set()
        now = now_ms()
        for st, down, up in [*self.key_log, *((k, v, now) for k, v in self.key_since.items())]:
            o = min(end, up) - max(started_ms, down)
            if o > 0:
                overlapped += o
                by.add(st)
        s = self.stations.get(station)
        report = {"type": "advisory_report", "station": station, "id": stream_id,
                  "waited_ms": round(self.last_wait.pop(s.callsign if s else station, 0.0), 1),
                  "spoke_ms": round(spoke_ms, 1), "overlapped_ms": round(overlapped, 1),
                  "overlapped_by": sorted(by), "cancelled": cancelled, "ts": now}
        self.advisory_reports = [*self.advisory_reports[-49:], report]
        self.send_to({"atc", "observer", station} & set(self.stations), report)
        return report

    # ------------------------------------------------------------ recording-session mode

    def set_speaker(self, station: str, name: str, consent: bool) -> None:
        if station not in self.stations:
            return
        self.speakers[station] = {"name": name.strip() or station, "consent": consent}
        if self.recorder is not None:
            self._send_prompt(station)
            self.send_to(None, self.recorder.status())

    async def set_recording(self, on: bool, session: str | None, tower_name: str, consent: bool) -> None:
        from unstep.live.recording import Recorder

        if on and self.recorder is None:
            if not consent:
                self._status("Recording needs the tower speaker's consent tick.", to={"atc"})
                return
            self.recorder = Recorder(session)
            self.speakers["atc"] = {"name": tower_name, "consent": True}
            for sid in self.stations:
                self._send_prompt(sid)
            self.send_to(None, self.recorder.status())
        elif not on and self.recorder is not None:
            final = {**self.recorder.status(), "on": False}
            self.recorder = None
            self.send_to(None, final)

    def _consented(self, station: str) -> bool:
        return bool(self.speakers.get(station, {}).get("consent"))

    def _send_prompt(self, station: str, cue: str | None = None) -> None:
        s = self.stations.get(station)
        if self.recorder is None or s is None or s.kind == "observer" or not self._consented(station):
            return
        msg = self.recorder.prompt(station, s.spoken)
        if cue:
            msg["cue"] = cue
        self.send_to({station, "atc"} & set(self.stations) if station != "atc" else {"atc"}, msg)

    def _open_event(self, callsign: str | None) -> str | None:
        """The newest blocked call for this plane that has a decision: what its next readback answers."""
        for trace in reversed(list(self.traces.values())):
            if callsign and trace.get("callsign") == callsign and trace.get("decision"):
                return trace["event_id"]
        return None

    def _key_overlaps(self, station: str, start_ms: int, end_ms: int) -> list[dict]:
        """Other stations keyed during [start, end], from key timing (the dataset's ground truth)."""
        now = now_ms()
        out = []
        for st, down, up in [*self.key_log, *((k, v, now) for k, v in self.key_since.items())]:
            if st == station:
                continue
            a, b = max(start_ms, down), min(end_ms, up)
            if b > a:
                out.append({"with": st, "start_ms": int(a), "end_ms": int(b)})
        return out

    async def _record_clip(self, tx: Transmission, script: dict | None) -> None:
        rec = self.recorder
        if rec is None or not self._consented(tx.station):
            return
        transcript = await self._peek_streamed(tx) if self.live else None
        s = self.stations.get(tx.station)
        readback_of = directive = None
        if s is not None and s.kind == "aircraft":
            for trace in reversed(list(self.traces.values())):
                if trace.get("callsign") == s.callsign and trace.get("decision"):
                    readback_of, directive = trace["event_id"], trace["decision"].get("instruction_text")
                    break
        row = rec.save_clip(station=tx.station, speaker=self.speakers[tx.station]["name"], pcm=tx.pcm,
                            start_ms=tx.start_ms, end_ms=tx.end_ms, script_line=(script or {}).get("line"),
                            script_kind=(script or {}).get("kind", "instruction" if tx.station == "atc" else None),
                            transcript=transcript if isinstance(transcript, str) else
                            getattr(transcript, "text", None), overlaps=self._key_overlaps(tx.station, tx.start_ms, tx.end_ms),
                            readback_of=readback_of, readback_directive=directive)
        if row is not None and self.recorder is rec:
            rec.advance(tx.station)
            self._send_prompt(tx.station)
        if self.recorder is rec:
            self.send_to(None, rec.status())

    def set_language(self, station: str, language: str | None) -> str | None:
        """The pilot's language for the private repeat of directives (R17 a). Only languages
        the cockpit has checked live are kept (unstep.cockpit.translate.LANGUAGES); anything
        else means English only. Returns what was kept."""
        from unstep.cockpit.translate import LANGUAGES

        code = (language or "").strip().lower()[:8] or None
        code = code if code in LANGUAGES else None
        self.languages[station] = code
        s = self.stations.get(station)
        edge = self.edges.get(s.callsign) if s is not None and s.callsign else None
        if edge is not None:
            edge.set_language(code)
        return code

    async def claim_aircraft(self, language: str | None = None) -> Station | None:
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
                self.set_language(s.id, language)
                return self.stations[s.id]
            return None

    @staticmethod
    def fleet_limit() -> set[str]:
        n = int(env("UNSTEP_MAX_AIRCRAFT") or len(scenario.FLEET))
        return {f[0] for f in scenario.FLEET[:max(1, n)]}

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await self._close_voices()
        if self.flight_log is not None and self.edges:  # every flight ends with the hub: archive, push once
            for callsign, edge in list(self.edges.items()):
                try:
                    await self.flight_log.archive(callsign, edge.memory, edge.flight_idx, "hub stopped")
                except Exception:
                    log.exception("archiving %s at stop failed", callsign)
            try:
                await asyncio.wait_for(self.flight_log.push(), 10)
            except Exception:
                log.warning("flight log push at stop did not finish; the log stays local")
        for edge in self.edges.values():
            await self._close_engine(edge)
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
        self.last_active[station] = time.monotonic()
        self.clients[station].add(ws)
        self.claims.pop(station, None)
        await ws.send_json(self.snapshot(station))
        if self.recorder is not None:
            self._send_prompt(station)
        self.presence()

    def leave(self, station: str, ws) -> None:
        self.clients.get(station, set()).discard(ws)
        if not self.clients.get(station) and station in self.key_since:
            self._key(station, False)  # a phone that drops mid-call must not hold the key down
        if not self.clients.get(station) and self.is_walk_up(station):
            self._spawn(self._free_later(station))
        self.presence()

    # ------------------------------------------------------------ walk-up seats (R22)

    @staticmethod
    def is_team_station(station: str) -> bool:
        return station in TEAM_STATIONS

    def is_walk_up(self, station: str) -> bool:
        s = self.stations.get(station)
        return s is not None and s.kind == "aircraft" and not self.is_team_station(station)

    async def _landing_sweeper(self) -> None:
        """A walk-up pilot who is still connected but has done nothing for UNSTEP_IDLE_LAND_S has landed: free
        the seat the same way a gone phone is (archive the flight to the flight log, push once, close its
        cockpit agent and open events), so a demo room does not keep stale planes running."""
        limit = idle_land_s()
        if limit <= 0:
            return
        while True:
            await asyncio.sleep(min(15.0, max(0.5, limit / 4)))
            now = time.monotonic()
            for station in list(self.stations):
                if not self.is_walk_up(station) or station in self.key_since or station in self.streams:
                    continue
                if now - self.last_active.get(station, now) >= limit:
                    await self.free_seat(station, f"landed: no activity for {round(limit / 60, 1):g} min")

    async def _free_later(self, station: str) -> None:
        await asyncio.sleep(SEAT_FREE_S)
        claimed = now_ms() - self.claims.get(station, -1e12) < CLAIM_S * 1000
        if not self.clients.get(station) and not claimed:
            await self.free_seat(station, "phone gone for 20 s")

    async def _push_flight_log(self) -> None:
        if self.flight_log is None:
            return
        await self.flight_log.push()  # in the background: never on the radio path
        self.send_to(None, self.flight_log.status())

    async def free_seat(self, station: str, reason: str, push: bool = True) -> bool:
        """Give a walk-up plane back to the fleet: its key, stream, cockpit agent and open
        events end cleanly and it leaves /live/stations. The team planes are never freed."""
        if not self.is_walk_up(station):
            return False
        s = self.stations[station]
        st = self.streams.pop(station, None)
        if st is not None:  # end a stream that was still open; the pump sees the end and stops
            st.setdefault("end_ms", now_ms())
            st["queue"].put_nowait(None)
        if station in self.key_since:
            self._key(station, False)
        for trace in self.traces.values():
            if trace.get("callsign") == s.callsign and trace["status"] in ("detected", "proposed", "needs_you"):
                trace["status"] = "cancelled"
                self._step(trace, "room", "cancelled", f"{s.name or s.callsign} left: {reason}. Nothing was sent")
                self.send_to(None, {"type": "trace", "trace": trace})
        edge = self.edges.pop(s.callsign, None)
        if edge is not None and self.flight_log is not None:
            await self.flight_log.archive(s.callsign, edge.memory, edge.flight_idx, reason)
            if push:
                self._spawn(self._push_flight_log())
        if edge is not None:
            await self._close_engine(edge)
            try:
                await edge.stop()
            except Exception:
                log.exception("stopping the cockpit agent for %s failed", station)
            self._moss_used = max(0, self._moss_used - 1)
        self.turns.pop(s.callsign, None)
        for d in (self.languages, self.claims, self.last_wait):
            d.pop(station, None)
        for ws in list(self.clients.pop(station, ())):
            try:
                await ws.send_json({"type": "seat_freed", "reason": reason})
                await ws.close()
            except Exception:
                pass
        self.stations.pop(station, None)
        self.graph = [n for n in self.graph if n["id"] != f"cockpit:{s.callsign}"]
        log.info("freed seat %s (%s)", station, reason)
        if reason.startswith("landed"):  # the console's "Agents at work" feed shows what the monitor did
            self.send_to({"atc", "observer"}, {
                "type": "agent_action", "id": f"landed-{s.callsign}-{now_ms()}", "ts": now_ms(), "agent": "Monitor",
                "kind": "rule", "station": s.callsign, "event_id": None, "status": "done",
                "text": f"{s.name or s.callsign} landed after {reason.removeprefix('landed: no activity for ')} with no "
                        "activity; seat freed", "detail": "Flight archived to the flight log", "sponsor": None})
        self.send_to(None, {"type": "stations", "stations": self.stations_info(), "graph": self.graph})
        self.presence()
        return True

    async def reset(self) -> None:
        """Presenter "reset room" (atc only): free every walk-up seat and clear traces, lanes,
        reports and the stats window. The team planes (N123AB, H456) stay."""
        for station in [sid for sid in list(self.stations) if self.is_walk_up(sid)]:
            await self.free_seat(station, "room reset by the presenter", push=False)
        self._spawn(self._push_flight_log())  # one push for every flight the reset ended
        self.traces.clear()
        self.transcripts.clear()
        self.radio_log.clear()
        self.insights.clear()
        self.stepons = []
        self.advisory_reports = []
        self.key_log = []
        self.reset_at = now_ms()
        self.send_to(None, {"type": "room_reset", "ts": self.reset_at, "stations": self.stations_info(),
                            "graph": self.graph})

    def snapshot(self, station: str) -> dict:
        return {"type": "hello", "you": station, "now_ms": now_ms(), "live": self.live,
                "frequency": self.frequency,
                "stations": self.stations_info(), "keyed": dict(self.key_since),
                "graph": self.graph, "autonomy": self.policy.enabled if self.policy else True,
                "traces": list(self.traces.values()), "radio": self.radio_log[-30:],
                "insights": self.insights[-20:], "mic": self.live and bool(env("CARTESIA_API_KEY")),
                "recording": self.recorder.status() if self.recorder else {"on": False},
                "flightlog": self.flight_log.status() if self.flight_log else None}

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
        self.last_active[station] = time.monotonic()  # any input but a ping counts as the pilot being there
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
        elif kind == "reset" and station == "atc":
            await self.reset()
        elif kind == "cue":
            self._spawn(self.say_cue(station, str(data.get("name", ""))))
        elif kind == "recording" and station == "atc":
            await self.set_recording(bool(data.get("on")), str(data.get("session") or "") or None,
                                     str(data.get("name") or "Tower")[:60], bool(data.get("consent")))
        elif kind == "speaker":
            self.set_speaker(station, str(data.get("name") or "")[:60], bool(data.get("consent")))
        elif kind == "language":
            kept = self.set_language(station, data.get("code"))
            self.send_to({station}, {"type": "language", "code": kept})
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

    def _caption_turns_stt(self, s: Station):
        """A turns-endpoint stream for captions only, when UNSTEP_CAPTION_SOURCE=turns; else None."""
        if self.caption_source != "turns":
            return None
        if self.caption_turns_factory is not None:
            return self.caption_turns_factory(s)
        if not (self.live and env("CARTESIA_API_KEY")):
            return None
        from unstep.cockpit.stt import CartesiaTurnSTT

        planes = [x for x in self.stations.values() if x.kind == "aircraft"]
        names = [c for x in planes for c in (x.spoken, x.callsign) if c] if s.kind == "atc" \
            else [s.spoken or s.callsign, s.callsign]
        return CartesiaTurnSTT(keyterms=build_keyterms(callsigns=names, runways=("33", "28L")))

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
        self._send_levels(station, f"{station}-{start_ms}", start_ms + st["bytes"] * 1000 // (SAMPLE_RATE * 2), pcm)
        self._mix_add(f"{station}-{start_ms}", station, start_ms, to_mono16k(pcm, SAMPLE_RATE))
        st["chunks"].append(pcm)
        st["bytes"] += len(pcm)
        st["queue"].put_nowait(pcm)

    # ------------------------------------------------------------ live captions and levels (display only)

    def _send_levels(self, station: str, stream_id: str, t_ms: int, pcm) -> None:
        """`level`: one RMS value (0..1) per 50 ms of audio, hub time of the first one. Numbers only."""
        samples = (np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
                   if isinstance(pcm, (bytes, bytearray)) else np.asarray(pcm, dtype=np.float32))
        step = SAMPLE_RATE * LEVEL_MS // 1000
        rms = [round(float(np.sqrt(np.mean(samples[i:i + step] ** 2))), 4)
               for i in range(0, len(samples) - step + 1, step)]
        if rms:
            self.send_to(None, {"type": "level", "station": station, "id": stream_id, "t_ms": int(t_ms),
                                "step_ms": LEVEL_MS, "rms": rms})

    def _caption(self, station: str, stream_id: str, text: str, final: bool, source: str,
                 lag_ms: float | None = None, at_ms: list[int | None] | None = None) -> None:
        """`caption`: the words so far (Cartesia interim or final), keywords tagged by kind."""
        from unstep.live.captions import tag

        words = tag(text)
        for k, w in enumerate(words):
            w["at_ms"] = at_ms[k] if at_ms and k < len(at_ms) else None
        self.send_to(None, {"type": "caption", "station": station, "id": stream_id, "text": text, "final": final,
                            "source": source, "lag_ms": None if lag_ms is None else round(lag_ms, 1),
                            "words": words, "ts": now_ms()})

    async def _tts_captions(self, tx: Transmission) -> None:
        """Typed lines have no STT stream: show each word at its spoken time, from Cartesia TTS word times."""
        words = [(w, tx.start_ms + int(start * 1000)) for w, start, _ in tx.words if str(w).strip()]
        for k in range(len(words)):
            await asyncio.sleep(max(0.0, (words[k][1] - now_ms()) / 1000))
            text = " ".join(str(w).strip() for w, _ in words[:k + 1])
            self._caption(tx.station, tx.tx_id, text, final=k == len(words) - 1, source="tts",
                          at_ms=[t for _, t in words[:k + 1]])

    # ------------------------------------------------------------ transcribe while on air (R27 3a)

    def _mix_enabled(self) -> bool:
        return self.mix_stt_factory is not None or bool(self.live and env("CARTESIA_API_KEY"))

    def _mix_stt(self, callsign: str):
        if self.mix_stt_factory is not None:
            return self.mix_stt_factory(callsign)
        terms = build_keyterms(callsigns=[callsign, scenario.SPOKEN_CALLSIGN], runways=["33", "28L"])
        return CartesiaManualSTT(keyterms=terms)

    def _mix_add(self, key: str, station: str, start_ms: int, samples) -> None:
        """Put audio on the live mix; the first transmission of a cluster opens one STT stream per cockpit."""
        if not self._mix_enabled():
            return
        if self.live_mix is None:
            self.live_mix = LiveMix(start_ms)
            for s in self.stations.values():
                if s.kind == "aircraft" and s.callsign in self.edges:
                    q: asyncio.Queue = asyncio.Queue()
                    self.mix_streams[s.callsign] = {"queue": q, "task": self._spawn(self._mix_pump(s.callsign, q))}
            self._spawn(self._mix_feed(self.live_mix))
        self.live_mix.add(key, station, start_ms, samples)

    async def _mix_feed(self, mx: LiveMix) -> None:
        """Every 100 ms, the newly mixed audio (up to 150 ms ago) goes to every cockpit's stream."""
        while self.live_mix is mx:
            chunk = mx.pull(now_ms() - 150)
            if len(chunk):
                data = pcm16(chunk)
                for st in self.mix_streams.values():
                    st["queue"].put_nowait(data)
            await asyncio.sleep(0.1)

    async def _mix_pump(self, callsign: str, q: asyncio.Queue) -> str | None:
        try:
            async with self._mix_stt(callsign) as stt:
                while (data := await q.get()) is not None:
                    await stt.send_audio(data)
                return (await stt.finalize()).text
        except Exception:
            log.exception("live-mix STT failed for %s; the cluster will be transcribed after it ends", callsign)
            return None

    async def _mix_finish(self, cluster: list[Transmission]) -> dict[str, str]:
        """At cluster end: the rest of the audio goes out, every cockpit's stream finalizes."""
        mx, streams = self.live_mix, self.mix_streams
        self.live_mix, self.mix_streams = None, {}
        if mx is None:
            return {}
        keys = {k for t in cluster for k in (t.tx_id, f"{t.station}-{t.start_ms}")}
        if not set(mx.parts) <= keys:  # the mix also holds a newer call: don't trust it, use the old path
            for st in streams.values():
                st["queue"].put_nowait(None)
                st["task"].cancel()
            return {}
        for key in mx.parts:
            mx.close(key)
        rest = mx.pull()
        out: dict[str, str] = {}
        for callsign, st in streams.items():
            if len(rest):
                st["queue"].put_nowait(pcm16(rest))
            st["queue"].put_nowait(None)
        asked = now_ms()
        for callsign, st in streams.items():
            try:
                text = await asyncio.wait_for(asyncio.shield(st["task"]), STREAM_FINAL_S)
            except Exception:
                text = None
            if text is not None:
                out[callsign] = text
                self.mix_final_ms[callsign] = now_ms() - asked  # shown as cockpit_stt_final on the trace
        return out

    def _stream_typed_tower(self, tx: Transmission) -> None:
        """A typed tower line: its audio streams to the tower transcriber at real-time pace from the
        moment it goes on air, so the transcript is final at its end instead of seconds later."""
        s = self.stations.get(tx.station)
        if s is None or s.kind != "atc":
            return
        stt = (self.stream_stt_factory or self._stream_stt)(s)
        if stt is None:
            return
        st = {"start_ms": tx.start_ms, "end_ms": tx.end_ms, "queue": asyncio.Queue(), "captions": False}
        self.stream_results[tx.tx_id] = self._spawn(self._pump(s, stt, st))
        self._spawn(self._pace(st, pcm16(tx.pcm), tx.start_ms))

    @staticmethod
    async def _pace(st: dict, data: bytes, start_ms: int) -> None:
        step = SAMPLE_RATE * 2 // 10  # 100 ms
        for i in range(0, len(data), step):
            await asyncio.sleep(max(0.0, (start_ms + i * 1000 // (SAMPLE_RATE * 2) - now_ms()) / 1000))
            st["queue"].put_nowait(data[i:i + step])
        st["queue"].put_nowait(None)

    async def _pump(self, s: Station, stt, st: dict):
        stream_id = f"{s.id}-{st['start_ms']}"
        st["sent_end_ms"] = st["start_ms"]

        def on_text(delta: str, so_far: str) -> None:
            # ink-2 streams final-text deltas while the key is still held (Rishit's live check, R26);
            # show the whole utterance so far, never the raw delta (deltas can split a word).
            if so_far:
                self._caption(s.id, stream_id, so_far, final=False, source="stt",
                              lag_ms=now_ms() - st["sent_end_ms"])

        turns = self._caption_turns_stt(s) if st.get("captions", True) else None
        tq: asyncio.Queue | None = asyncio.Queue() if turns is not None else None
        turn_task = self._spawn(self._turn_captions(s, stream_id, st, turns, tq)) if turns is not None else None
        # set before `async with`: read when the socket opens. With the turns source, that stream owns the captions.
        if hasattr(stt, "on_text") and st.get("captions", True) and turns is None:
            stt.on_text = on_text
        try:
            async with stt:
                sent = 0
                while (pcm := await st["queue"].get()) is not None:
                    await stt.send_audio(pcm)
                    if tq is not None:
                        tq.put_nowait(pcm)
                    sent += len(pcm)
                    st["sent_end_ms"] = st["start_ms"] + sent * 1000 // (SAMPLE_RATE * 2)
                released = now_ms()
                if s.kind == "atc":
                    result = await stt.finish(st["start_ms"], st["end_ms"], self.frequency)
                    if getattr(stt, "last_alignment", None):
                        self.alignments[result.transcript_id] = stt.last_alignment
                else:
                    result = (await stt.finalize()).text
                log.info("streamed STT for %s final %d ms after release", s.id, now_ms() - released)
                final_text = result.text if s.kind == "atc" else result
                st["captions_done"] = True  # a late interim from the turns stream must not undo the final text
                if final_text:
                    self._caption(s.id, stream_id, final_text, final=True, source="stt", lag_ms=now_ms() - released)
                if s.kind == "atc":  # S1: how long after the key came up the tower's words were final
                    self.stt_final[result.transcript_id] = (now_ms(), now_ms() - released)
                return result
        except Exception:
            log.exception("streamed STT failed for %s; the clip will be transcribed instead", s.id)
            return None
        finally:
            if tq is not None:
                tq.put_nowait(None)
                try:
                    await asyncio.wait_for(asyncio.shield(turn_task), 1.5)
                except Exception:
                    turn_task.cancel()

    async def _turn_captions(self, s: Station, stream_id: str, st: dict, turns, tq: asyncio.Queue) -> None:
        """Display-only captions from Cartesia's turns endpoint: the same audio, and `turn.update` text as it comes."""
        committed = ""

        async def read() -> None:
            nonlocal committed
            async for ev in turns.events():
                text = (ev.transcript or "").strip()
                if ev.type == "turn.end":
                    committed = f"{committed} {text}".strip() if text else committed
                    text = ""
                elif ev.type not in ("turn.update", "turn.eager_end") or not text:
                    continue
                shown = f"{committed} {text}".strip()
                if shown and not st.get("captions_done"):
                    self._caption(s.id, stream_id, shown, final=False, source="stt",
                                  lag_ms=now_ms() - st.get("sent_end_ms", st["start_ms"]))

        try:
            async with turns:
                reader = asyncio.create_task(read())
                while (pcm := await tq.get()) is not None:
                    await turns.send_audio(pcm)
                await asyncio.sleep(0.2)  # let the last partial arrive before the final text replaces it
                reader.cancel()
        except Exception:
            log.exception("turns caption stream failed for %s; captions fall back to the final text", s.id)

    async def mic_end(self, station: str) -> Transmission | None:
        st = self.streams.pop(station, None)
        self._key(station, False)
        if st is None:
            return None
        pcm = b"".join(st["chunks"])
        key = f"{station}-{st['start_ms']}"
        if len(pcm) < 0.3 * SAMPLE_RATE * 2:  # a tap, not a call
            if st["pump"] is not None:
                st["pump"].cancel()
            if self.live_mix is not None:
                self.live_mix.drop(key)
            return None
        if self.live_mix is not None:
            self.live_mix.close(key)
        st["end_ms"] = st["start_ms"] + round(len(pcm) / 2 * 1000 / SAMPLE_RATE)
        st["queue"].put_nowait(None)
        tx = Transmission(station, st["start_ms"], to_mono16k(pcm, SAMPLE_RATE))
        if st["pump"] is not None:
            self.stream_results[tx.tx_id] = st["pump"]
        await self.transmit(tx)
        if self.recorder is not None:
            self._spawn(self._record_clip(tx, self.prompt_at_press.pop(station, None)))
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
                                 "start_ms": tx.start_ms, "end_ms": tx.end_ms, "radio": self.radio_sound,
                                 "audio": wav_b64(radio_voice(tx.pcm) if self.radio_sound else tx.pcm,
                                                  SAMPLE_RATE)})
        self.send_to({tx.station}, {"type": "transmitting", "tx_id": tx.tx_id, "text": tx.text,
                                    "end_ms": tx.end_ms})
        self.flow(tx.station if tx.station == "atc" else f"pilot:{tx.station}", "radio", "voice")
        if tx.text is not None:  # typed line: its whole audio is known now, so it goes on the live mix at once
            self._mix_add(tx.tx_id, tx.station, tx.start_ms, tx.pcm)
            if self.live_mix is not None:
                self.live_mix.close(tx.tx_id)
            self._stream_typed_tower(tx)
        if tx.text and tx.words:  # typed line: captions and levels from the TTS audio and word times
            self._send_levels(tx.station, tx.tx_id, tx.start_ms, tx.pcm)
            self._spawn(self._tts_captions(tx))
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
            since = self.key_since.pop(station, None)
            if since is None:
                return
            self.key_log = [*self.key_log[-199:], (station, since, received)]
            self.keyed.discard(station)
        if down and self.recorder is not None and self._consented(station):
            s = self.stations.get(station)
            self.prompt_at_press[station] = self.recorder.prompt(station, s.spoken if s else None)
            if station == "atc":
                planes = [sid for sid, st in self.stations.items()
                          if st.kind == "aircraft" and self._consented(sid) and self.clients.get(sid)]
                target = self.recorder.talk_over_target(planes)
                if target:
                    self._send_prompt(target, cue="talk_now")
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
        heard_live = await self._mix_finish(cluster)
        if self.recorder is not None and mx.overlaps:
            self.recorder.save_mix(pcm=mx.pcm, stations=[t.station for t in cluster], start_ms=mx.t0,
                                   end_ms=max(t.end_ms for t in cluster),
                                   overlaps=[{"stations": o.stations, "start_ms": o.start_ms, "end_ms": o.end_ms}
                                             for o in mx.overlaps])
            self.send_to(None, self.recorder.status())
        jobs = [self._tower(t) for t in cluster if self.stations[t.station].kind == "atc"]
        towers = [t for t in cluster if self.stations[t.station].kind == "atc"]
        for s in self.stations.values():
            if s.kind == "aircraft" and mx.heard_by(s.id):
                jobs.append(self._cockpit_hears(s.callsign, mx, towers, heard_live.get(s.callsign)))
        for t in cluster:
            if self.stations[t.station].kind == "aircraft":
                jobs.append(self._pilot_spoke(t, clean=not mx.overlaps))
        if towers and mx.overlaps:
            jobs.append(self._recover_for_tower(cluster, mx))
        if mx.overlaps:
            self._notify_blocked_callers(cluster, mx)
        await asyncio.gather(*jobs, return_exceptions=False)

    async def _peek_streamed(self, tx: Transmission) -> str | None:
        """A pilot's streamed transcript without taking it from the readback path."""
        task = self.stream_results.get(tx.tx_id)
        if task is None:
            return None
        try:
            result = await asyncio.wait_for(asyncio.shield(task), STREAM_FINAL_S)
        except Exception:
            return None
        return result if isinstance(result, str) else None

    def _notify_blocked_callers(self, cluster: list[Transmission], mx: Mix) -> None:
        """C1, blocked caller: a pilot whose own call was stepped on hears "Your last call was
        blocked. Say again." through their cockpit agent (busy hold and priority are Rishit's
        CockpitEdge.notify_blocked: a directive for that plane always goes first)."""
        for t in cluster:
            s = self.stations.get(t.station)
            edge = self.edges.get(s.callsign) if s is not None and s.kind == "aircraft" else None
            if edge is None or not any(o.start_ms < t.end_ms and o.end_ms > t.start_ms for o in mx.overlaps):
                continue
            if now_ms() - t.end_ms > RECOVERY_STALE_MS:
                continue
            self._spawn(self._notify_one(edge, t))

    async def _notify_one(self, edge, t: Transmission) -> None:
        try:
            await edge.notify_blocked(f"rec-{t.tx_id}")
        except Exception:
            log.exception("blocked-caller notice failed for %s", t.station)
            return
        delivered = now_ms() - t.end_ms
        await self.links["tower"].send(AuditRecord(
            event_id=f"rec-{t.tx_id}", stage="recovery", actor="tower", latency_ms=delivered,
            payload={"to": t.station, "from": "unstep", "kind": "blocked_caller_notice", "priority": 1,
                     "delivered_ms": delivered}))

    async def _recover_for_tower(self, cluster: list[Transmission], mx: Mix) -> None:
        """C1, tower side: the controller was transmitting, so they never heard the call that
        stepped on them. Unstep tells them, in their ear, who it was and what they said."""
        for t in cluster:
            s = self.stations.get(t.station)
            if s is None or s.kind != "aircraft":
                continue
            if not any(o.start_ms < t.end_ms and o.end_ms > t.start_ms for o in mx.overlaps):
                continue
            words = t.text or await self._peek_streamed(t)
            who = s.spoken or s.callsign or s.id
            text = (f"{who} was blocked: {words.strip().rstrip('.')}." if words and words.strip()
                    else f"{who} was blocked. Ask them to say again.")
            deadline = now_ms() + RECOVERY_WAIT_GAP_MS
            while "atc" in self.key_since and now_ms() < deadline:  # speak in a gap, never over the controller
                await asyncio.sleep(0.1)
            if now_ms() - t.end_ms > RECOVERY_STALE_MS:
                log.info("tower recovery for %s dropped: older than %d ms", t.station, RECOVERY_STALE_MS)
                continue
            audio = None
            try:
                speech = await self._controller_tts().speak("Advisory. " + text)
                audio = wav_b64(to_mono16k(speech.pcm, speech.sample_rate), SAMPLE_RATE) if speech.pcm else None
            except Exception:
                log.exception("tower recovery speech failed; sending text only")
            sent_at = now_ms()
            self.send_to({"atc"}, {"type": "recovery", "to": "atc", "from_station": t.station,
                                   "kind": "blocked_caller", "priority": 2, "text": text, "tx_id": t.tx_id,
                                   "ts": sent_at, "audio": audio})
            await self.links["tower"].send(AuditRecord(
                event_id=f"rec-{t.tx_id}", stage="recovery", actor="tower",
                latency_ms=sent_at - t.end_ms,
                payload={"to": "atc", "from": t.station, "kind": "blocked_caller", "priority": 2,
                         "text": text, "delivered_ms": sent_at - t.end_ms}))

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
            asked = now_ms()
            transcript = await transcriber.transcribe(pcm16(tx.pcm), tx.start_ms, tx.end_ms,
                                                      self.frequency, callsign)
            self.stt_final[transcript.transcript_id] = (now_ms(), now_ms() - asked)
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

    async def _cockpit_hears(self, callsign: str, mx: Mix, towers: list[Transmission],
                             heard_live: str | None = None) -> None:
        edge = self.edges[callsign]
        if heard_live is not None:
            # R27 3a: this cockpit's STT ran while the call was on air; its text is final now
            edge.manual_stt_factory = lambda h=heard_live: FakeManualSTT([h])
        elif self.live and env("CARTESIA_API_KEY"):
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
        edge.radio_speakers = [t.station for t in mx.transmissions]  # metadata for its Moss session (P4)
        await edge.run_audio(ArraySource(mx.pcm, t0=mx.t0, squelch=KeyedSquelch(mx.any_keyed)),
                             realtime=self.live and self.realtime_replay)

    async def _pilot_spoke(self, tx: Transmission, clean: bool) -> None:
        turns = self.turns.get(tx.station)
        edge = self.edges.get(tx.station)
        if turns is None or not clean or turns.listening == 0:
            self.stream_results.pop(tx.tx_id, None)
            if edge is not None and tx.text:  # what the pilot said, even if nobody heard it (P4)
                await edge.index_heard(tx.text, tx.station, tx.start_ms, stepped_on=not clean, kind="readback",
                                       event_id=self._open_event(tx.station))
            return  # a stepped-on readback is lost, as it would be on the radio
        text = tx.text or await self._streamed(tx)
        if edge is not None and text:
            await edge.index_heard(text, tx.station, tx.start_ms, stepped_on=False, kind="readback",
                                   event_id=self._open_event(tx.station))
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
                           f"in {hint.moss_ms} ms", source_text=hint.source_text, moss_ms=hint.moss_ms,
                           backend=getattr(getattr(self.edges.get(msg.callsign), "memory", None), "backend", "local"))
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
                final = self.stt_final.get(tower.transcript_id)
                if final is not None:  # S1: tower STT final, ms after release (stream) or after the clip was sent
                    self._time(trace, "tower_stt_final", final[0], ms=final[1], by="cartesia")
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
            if not msg.match and getattr(self, "elastic_agents", None) is not None:  # B5: audit off the radio path
                instruction = (trace.get("decision") or {}).get("instruction_text", "")
                self._spawn(self.elastic_agents.readback_audit(event_id, instruction, msg.readback_text, msg.attempt))
            trace["status"] = "confirmed" if msg.match else "readback_wrong"
            self._step(trace, f"cockpit:{cs}", "readback",
                       f"Readback {'correct' if msg.match else 'incorrect'}: \"{msg.readback_text}\"")
            self._time(trace, "readback", env_.ts, by=f"cockpit:{cs}")
        elif isinstance(msg, AuditRecord) and msg.stage == "cockpit_stt":
            # S1: the cockpit's own STT finalize on what it heard (ms from close to final text)
            on_air = self.mix_final_ms.pop(cs, None) if cs else None
            self._time(trace, "cockpit_stt_final", env_.ts, ms=on_air if on_air is not None else msg.latency_ms,
                       by=f"cockpit:{cs}" + (" (streamed on air)" if on_air is not None else ""))
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
                       f"the stored directive ({msg.actor}, "
                       f"{round(msg.latency_ms, 2) if isinstance(msg.latency_ms, (int, float)) else msg.latency_ms} ms): "
                       f"{'agrees with' if agrees else 'disagrees with'} the slot check", **msg.payload)
            self._time(trace, "elastic_check", env_.ts, ms=msg.latency_ms, by=msg.actor)
        elif isinstance(msg, AuditRecord) and msg.stage == "hint_search":
            p = msg.payload
            found = (f"top hit \"{p.get('top_hit_text')}\" (score {p.get('score')})" if p.get("top_hit_text")
                     else "no matching clearance")
            if p.get("below_floor"):
                found = (f"best match {p.get('best_score')} is below the {p.get('floor')} floor, so no hit is shown")
            agree = {True: ", the newest clearance", False: ", older than the newest clearance"}.get(p.get("agrees"), "")
            no_hint = f". No hint: {p['no_hint']}" if p.get("no_hint") else ""
            self._step(trace, f"cockpit:{cs}", "moss_search",
                       f"Moss searched this plane's session for \"{p.get('query')}\": {found}{agree}, "
                       f"in {p.get('search_ms')} ms{no_hint}", **p)
            self._time(trace, "moss_search", env_.ts, ms=p.get("search_ms"), by="moss")
        elif isinstance(msg, AuditRecord) and msg.stage == "ground_agents":
            self.flow("ground", "elastic", "audit", event_id)
        else:
            return
        self.send_to(None, {"type": "trace", "trace": trace})

    async def _agents_cited(self, event_id: str, merged, agents) -> None:
        """3a: the Elastic agents answered after the card was shown. Add their citation (and a lower confidence,
        never a higher one) to the open trace and say so. The instruction itself never changes."""
        trace = self.traces.get(event_id)
        if trace is None or not trace.get("proposal"):
            return
        proposal = trace["proposal"]
        citation = merged.rule_citation
        lowered = merged.confidence == "low" and proposal.get("confidence") != "low"
        if not citation and not lowered:
            return
        if citation:
            proposal["rule_citation"] = citation
        if lowered:
            proposal["confidence"] = "low"
        proposal["confidence_method"] = merged.confidence_method
        after = " and after the decision" if trace.get("status") in ("approved", "auto_relayed", "delivered") else ""
        seconds = round((agents.took_ms or 0) / 1000, 1)
        self._time(trace, "agents_cited", now_ms(), ms=agents.took_ms, by="elastic")
        self._step(trace, "ground", "agents_cited",
                   f"Elastic's agents checked the fix and cited {citation or 'no paragraph'} "
                   f"({seconds} s, after the card was shown{after})",
                   citation=citation, workflow_ms=agents.took_ms, confidence=proposal.get("confidence"))
        self.send_to(None, {"type": "trace", "trace": trace})

    async def _prompt_controller(self, trace: dict) -> None:
        p = trace.get("proposal") or {}
        text = f"Needs you. Blocked call to {trace.get('callsign')}: {p.get('instruction_text', '')}. Approve?"
        try:
            speech = await self._controller_tts().speak(text)
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
