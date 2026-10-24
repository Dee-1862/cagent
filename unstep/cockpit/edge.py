"""Cockpit edge agent: the real pipeline for one aircraft (replaces mock_cockpit.py).

Audio frames -> overlap detector -> on squelch close: cockpit STT -> local hint
from Moss -> advisory voice -> AnomalyEvent to the gateway. Then:

- ApprovedDirective for our callsign: speak it, record it in the flight session,
  run the readback loop on the pilot turn STT (turn.start interrupts the voice),
  send a ReadbackResult per attempt, speak the correction on a mismatch.
- RejectedDirective: "Advisory. Request say again."
- `ask(question)`: pilot query from the flight session, spoken, sent as PilotQuery.
- Gateway unreachable: the pre-generated offline alert plays and the cockpit keeps
  working locally (hint, queries). Unsent messages wait in `outbox`.

Logic lives in `CockpitEdge`; network IO is `GatewayLink` and audio output is
`AudioOut`, both swappable for tests. Every stage sends an AuditRecord with its
measured latency.

Run: python -m unstep.cockpit.edge assets/clips/stepped_on_call.wav [--url <gateway>]  (default: UNSTEP_GATEWAY_URL)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Iterable, Optional

import numpy as np
import soundfile as sf
from pydantic import BaseModel

from unstep.demo_audio import DEFAULT_DEMO_AUDIO_DIR, save_audio, speech_payload
from unstep import scenario
from unstep.clock import now_ms
from unstep.config import gateway_url, ws_url
from unstep.cockpit.audio import AudioSource, WavFileSource
from unstep.cockpit.hint import advisory_text, derive_hint
from unstep.cockpit.inference import Answerer, create_answerer
from unstep.cockpit.translate import Translator, create_translator, translate_advisory
from unstep.cockpit.memory import Doc, LocalMemory, Memory, airport_index, create_memory, flight_index
from unstep.cockpit.overlap import OverlapDetector, OverlapWindow
from unstep.cockpit.phraseology import display_text
from unstep.cockpit.queries import answer_query, record
from unstep.cockpit.readback import ReadbackSession
from unstep.cockpit.seed import AIRPORT_ICAO, COCKPIT, seed
from unstep.cockpit.stt import FakeManualSTT, FakeTurnSTT, TurnEvent
from unstep.cockpit.tts import (
    AdvisoryVoice,
    FakeTTS,
    SpeechResult,
    msg_directive,
    msg_say_again,
)
from unstep.contracts import (
    AnomalyEvent,
    ApprovedDirective,
    AuditRecord,
    Gps,
    RejectedDirective,
    unwrap,
    wrap,
)

log = logging.getLogger("unstep.edge")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WAV_OUT = ROOT / "data" / "cockpit_audio.wav"

BLOCKED_NO_HINT = "Advisory. Transmission blocked. Awaiting controller."
REQUEST_SAY_AGAIN = "Advisory. Request say again."
DEMO_HEARD = "Cessna 1-2-3 [static]"
DEMO_READBACKS = ("Hold short runway two three, Cessna 1-2-3", "Hold short runway three three, Cessna 1-2-3")


# ---------------------------------------------------------------- IO: audio out


class AudioOut:
    """Collects everything spoken (stereo int16, left ear only) and writes one WAV.

    `live=True` also plays each message through sounddevice, blocking until done.
    """

    def __init__(self, path: Optional[Path] = DEFAULT_WAV_OUT, live: bool = False, gap_ms: int = 300):
        self.path = Path(path) if path else None
        self.live = live
        self.gap_ms = gap_ms
        self.clips: list[tuple[np.ndarray, int]] = []

    def add(self, stereo: np.ndarray, sample_rate: int) -> None:
        self.clips.append((stereo, sample_rate))
        if self.live:
            try:
                import sounddevice as sd

                sd.play(stereo, sample_rate)
                sd.wait()
            except Exception as e:  # no device: keep going, the WAV still has it
                log.warning("live playback failed: %s", e)

    def render(self) -> tuple[np.ndarray, int]:
        if not self.clips:
            return np.zeros((0, 2), dtype=np.int16), 24000
        sr = self.clips[0][1]
        gap = np.zeros((sr * self.gap_ms // 1000, 2), dtype=np.int16)
        parts = []
        for stereo, _ in self.clips:
            parts += [stereo, gap]
        return np.concatenate(parts), sr

    def save(self) -> Optional[Path]:
        if self.path is None or not self.clips:
            return None
        audio, sr = self.render()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(self.path), audio, sr, subtype="PCM_16")
        return self.path


# ---------------------------------------------------------------- IO: gateway


class GatewayLink:
    """WebSocket to /ws/cockpit. `send` returns False when the gateway is down."""

    def __init__(self, url: str | None = None, connect_timeout_s: float = 2.0):
        self.url = (url or gateway_url()).rstrip("/")
        self.connect_timeout_s = connect_timeout_s
        self.ws = None
        self._reader: Optional[asyncio.Task] = None
        self.on_message: Callable[[Any], Any] = lambda msg: None

    @property
    def online(self) -> bool:
        return self.ws is not None

    async def connect(self) -> bool:
        import websockets

        try:
            self.ws = await asyncio.wait_for(websockets.connect(ws_url("cockpit", self.url)), self.connect_timeout_s)
        except Exception as e:
            log.warning("gateway unreachable at %s: %s", self.url, e)
            self.ws = None
            return False
        self._reader = asyncio.create_task(self._read())
        return True

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                env, msg = unwrap(raw)
                if msg is None:
                    log.warning("gateway error: %s", env.data.get("message"))
                    continue
                res = self.on_message(msg)
                if asyncio.iscoroutine(res):
                    await res
        except Exception as e:
            log.warning("gateway connection lost: %s", e)
        finally:
            self.ws = None

    async def send(self, msg: BaseModel) -> bool:
        if self.ws is None:
            return False
        try:
            await self.ws.send(wrap(msg))
            return True
        except Exception as e:
            log.warning("send failed: %s", e)
            self.ws = None
            return False

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
        self.ws = None


# ---------------------------------------------------------------- timing helpers


class TimedTTS:
    """Wraps a TTS engine and measures our own first-audio time (PRD section 9)."""

    def __init__(self, engine):
        self.engine = engine
        self.last_first_audio_ms: Optional[float] = None

    async def speak(self, text, context_id=None, on_chunk=None, **options) -> SpeechResult:
        """`options` (language, speed) are forwarded only when given."""
        started = time.perf_counter()
        first: list[float] = []

        def chunk(pcm: bytes) -> None:
            if not first:
                first.append((time.perf_counter() - started) * 1000)
            if on_chunk:
                on_chunk(pcm)

        res = await self.engine.speak(text, context_id=context_id, on_chunk=chunk, **options)
        self.last_first_audio_ms = first[0] if first else None
        return res

    async def cancel(self, context_id: str) -> None:
        await self.engine.cancel(context_id)


@dataclass
class Line:
    """One line of the demo transcript: who heard or said what, and when."""

    ts: int
    party: str  # RADIO, PILOT EAR, PILOT, SYSTEM
    text: str
    latency: dict[str, float] = field(default_factory=dict)


def readable(text: str) -> str:
    """On-screen form of an advisory: the same words as spoken, with digits and the prefix."""
    text = text.strip()
    if not text.lower().startswith("advisory"):
        text = f"Advisory. {text}"
    return display_text(text)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _pcm16(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


# ---------------------------------------------------------------- engine factories


def default_manual_stt(heard: Iterable[str] = (DEMO_HEARD,)):
    """Cartesia manual-finalize STT when CARTESIA_API_KEY is set, else a scripted fake."""
    heard = list(heard)
    if os.getenv("CARTESIA_API_KEY"):
        from unstep.cockpit.stt import CartesiaManualSTT, build_keyterms

        terms = build_keyterms(callsigns=[scenario.SPOKEN_CALLSIGN, scenario.CALLSIGN], runways=["33", "28L"])
        return lambda: CartesiaManualSTT(keyterms=terms)
    fake = FakeManualSTT(heard * 100)
    return lambda: fake


def default_tts():
    if os.getenv("CARTESIA_API_KEY") and os.getenv("CARTESIA_VOICE_ID"):
        from unstep.cockpit.tts import CartesiaTTS

        return CartesiaTTS()
    return FakeTTS()


# ---------------------------------------------------------------- the agent


@dataclass
class _Advisory:
    text: str
    event_id: str
    display: str | None
    latency: dict
    kind: str
    done: asyncio.Future
    held_at: float | None = None
    replay: bool = False
    cached: Any = None
    language: str | None = None   # Cartesia language for a translated advisory
    speed: float | None = None    # Cartesia speed, e.g. slower for corrections
    prefix: bool = True           # English "Advisory." prefix (off for translations)


CORRECTION_SPEED = 0.85  # within Sonic's documented 0.6 to 1.5
BLOCKED_NOTICE = "Your last call was blocked. Say again."
NOTICE_KINDS = {"blocked_caller"}  # lower priority than a directive


class CockpitEdge:
    def __init__(
        self,
        callsign: str = scenario.CALLSIGN,
        frequency: str = scenario.FREQUENCY,
        link: Optional[GatewayLink] = None,
        memory: Optional[Memory] = None,
        tts=None,
        manual_stt_factory: Optional[Callable[[], Any]] = None,
        turn_stt_factory: Optional[Callable[[], Any]] = None,
        audio_out: Optional[AudioOut] = None,
        detector: Optional[OverlapDetector] = None,
        gps: Optional[Gps] = None,
        taxiway_node: Optional[str] = "B4",
        answerer: Optional[Answerer] = None,
        translator: Optional[Translator] = None,
        language: Optional[str] = None,
        demo_audio_dir: Path | None = None,
    ):
        self.demo_audio_dir = demo_audio_dir
        self.callsign = callsign
        self.frequency = frequency
        self.link = link or GatewayLink()
        self.link.on_message = self.on_message
        self.memory = memory or create_memory()
        self.answerer = answerer
        self.translator = translator
        if self.translator is None and self.memory.backend == "moss":
            self.translator = create_translator()  # Moss Inference, same keys as the memory
        self.language = language  # pilot's language for the private repeat; None = English only
        if self.answerer is None and self.memory.backend == "moss":
            self.answerer = create_answerer()
        self.tts = TimedTTS(tts or default_tts())
        self.voice = AdvisoryVoice(self.tts)
        self.manual_stt_factory = manual_stt_factory or default_manual_stt()
        self.turn_stt_factory = turn_stt_factory or (lambda: FakeTurnSTT(DEMO_READBACKS))
        self.out = audio_out if audio_out is not None else AudioOut()
        self.detector = detector or OverlapDetector()
        self.gps = gps or Gps(lat=37.6188, lon=-122.3750)
        self.taxiway_node = taxiway_node

        self.airport_idx = ""
        self.flight_idx = ""
        # Who is on the radio for the next run_audio() call, set by whoever feeds the audio
        # (the live room knows the keyed stations). Only used as index metadata (P4).
        self.radio_speakers: list[str] = []
        self.offline_alert = None  # pre-generated Spoken
        self.lines: list[Line] = []
        self.latency: dict[str, list[float]] = {}
        self.outbox: list[BaseModel] = []
        self.sent: list[BaseModel] = []
        self.events: list[AnomalyEvent] = []
        self.outcomes: dict[str, str] = {}  # event_id -> approved/rejected/confirmed/flagged
        self._resolved: dict[str, asyncio.Event] = {}
        self._sent_at: dict[str, float] = {}
        self._tasks: set[asyncio.Task] = set()
        self._seq = 0
        self._frequency_busy = False
        self._advisories: list[_Advisory] = []
        self._speech_worker: asyncio.Task | None = None
        self._active_advisory: _Advisory | None = None

    # ------------------------------------------------------------ lifecycle

    async def start(self, connect: bool = True) -> bool:
        # Open Moss sessions now, while online: opening checks credentials with Moss
        # Cloud, so a lazy open mid-flight would fail once the link is gone.
        opener = getattr(self.memory, "open", None)
        if opener is not None:
            try:
                await opener(airport_index(AIRPORT_ICAO), flight_index(self.callsign))
            except Exception:
                log.exception("memory open failed at startup")
        self.airport_idx, self.flight_idx = await seed(self.memory, self.callsign, t0=now_ms())
        # Pre-generate the offline alert so it plays even with no network (PRD 6.2).
        self.offline_alert = await self.voice.say(msg_say_again())
        online = await self.link.connect() if connect else False
        self._note("SYSTEM", f"cockpit edge {self.callsign} up, gateway {'online' if online else 'OFFLINE'}, "
                             f"memory {getattr(self.memory, 'backend', '?')}")
        return online

    async def stop(self) -> None:
        for t in list(self._tasks):
            try:
                await asyncio.wait_for(t, 5)
            except (asyncio.TimeoutError, Exception):
                t.cancel()
        await self.link.close()
        self.out.save()

    # ------------------------------------------------------------ helpers

    async def index_heard(self, text: str, speaker: str, ts: int, stepped_on: bool = False,
                          kind: str = "heard", event_id: str | None = None,
                          speakers: list[str] | None = None) -> str | None:
        """Index one transmission into this plane's own flight session as it arrives (P4).

        `kind` is "heard" (what this cockpit heard on the radio, static included) or
        "readback" (the pilot's own words). Written through the cockpit writer, the only
        writer of flight-<callsign>; the session is never pushed. Returns the doc id, or
        None if there was nothing to index or memory failed (logged, never fatal).
        """
        if not text or not text.strip() or not self.flight_idx:
            return None
        doc_id = f"{kind}-{ts}-{speaker}"
        meta = {"callsign": self.callsign, "type": kind, "speaker": speaker, "ts": int(ts),
                "stepped_on": "true" if stepped_on else "false"}
        if speakers:
            meta["speakers"] = ",".join(speakers)
        if event_id:
            meta["event_id"] = event_id
        try:
            await self.memory.add_docs(self.flight_idx, [Doc(id=doc_id, text=text.strip(), metadata=meta)],
                                       writer=COCKPIT)
            return doc_id
        except Exception:
            log.exception("could not index %s in %s", doc_id, self.flight_idx)
            return None

    async def _record(self, doc_id: str, text: str, kind: str) -> None:
        """Write to the flight session; a memory failure is logged, never fatal mid-event."""
        try:
            await record(self.memory, self.flight_idx, self.callsign, doc_id, text, kind)
        except Exception:
            log.exception("could not record %s in %s", doc_id, self.flight_idx)

    def _note(self, party: str, text: str, **latency: float) -> Line:
        line = Line(now_ms(), party, text, {k: v for k, v in latency.items() if v is not None})
        self.lines.append(line)
        log.info("%-9s %s %s", party, text, line.latency or "")
        return line

    def _measure(self, name: str, ms: Optional[float]) -> None:
        if ms is not None:
            self.latency.setdefault(name, []).append(ms)

    async def set_frequency_busy(self, busy: bool) -> None:
        """Hold/cancel speech while ATC is busy; await False to drain held speech.

        Call on the edge's asyncio loop. Concurrent speak() calls wait for actual
        delivery (or return None for a superseded hint). A new busy signal stops
        draining; cancelled speech restarts with a fresh voice context.
        """
        self._frequency_busy = busy
        if busy:
            newly_held = []
            for item in self._advisories:
                if item.held_at is None:
                    item.held_at = time.perf_counter()
                    newly_held.append(item)
            active = self._active_advisory
            if active is not None and self.voice.current is not None:
                active.replay = True
                await self.voice.interrupt()  # same cancellation as turn.start
            for item in newly_held:
                await self.audit(item.event_id, "held", waited_ms=0.0, text=item.text)
        else:
            self._ensure_speech_worker()
            if self._speech_worker is not None:
                await asyncio.shield(self._speech_worker)

    def _ensure_speech_worker(self) -> None:
        if not self._frequency_busy and self._advisories:
            if self._speech_worker is None or self._speech_worker.done():
                self._speech_worker = self._spawn(self._drain_advisories())

    async def speak(self, text: str, event_id: str = "", display: str | None = None,
                    *, kind: str = "advisory", _cached=None, language: str | None = None,
                    speed: float | None = None, prefix: bool = True, **latency: float):
        """Speak in request order; wait while busy. Only explicit hints may expire."""
        item = _Advisory(text, event_id, display, latency, kind,
                         asyncio.get_running_loop().create_future(), cached=_cached,
                         language=language, speed=speed, prefix=prefix)
        # Replace a held hint in its original position, preserving event order.
        replaced = False
        if event_id and kind in {"directive", "rejection"}:
            for i, old in enumerate(self._advisories):
                if old.event_id == event_id and old.kind == "hint" and old.held_at is not None:
                    item.held_at = old.held_at
                    self._advisories[i] = item
                    old.done.set_result(None)
                    replaced = True
                    break
        if not replaced:
            self._advisories.insert(self._queue_slot(kind), item)
        if self._frequency_busy or item.held_at is not None:
            item.held_at = item.held_at or time.perf_counter()
            await self.audit(event_id, "held", waited_ms=_ms(item.held_at), text=text)
        self._ensure_speech_worker()
        return await asyncio.shield(item.done)

    def _queue_slot(self, kind: str) -> int:
        """A restrictive directive goes ahead of queued notices; never ahead of the one speaking."""
        if kind == "directive":
            for i, old in enumerate(self._advisories):
                if old.kind in NOTICE_KINDS and old is not self._active_advisory:
                    return i
        return len(self._advisories)

    async def notify_blocked(self, event_id: str, text: str = BLOCKED_NOTICE):
        """Tell this pilot their own call was blocked (C1). Waits while busy; directives go first."""
        return await self.speak(text, event_id, kind="blocked_caller")

    async def _drain_advisories(self) -> None:
        while self._advisories and not self._frequency_busy:
            item = self._advisories[0]
            if item.held_at is not None:
                await self.audit(item.event_id, "released", waited_ms=_ms(item.held_at), text=item.text)
                if self._frequency_busy:
                    break
                if self._advisories[0] is not item:
                    continue
                item.held_at = None
            item.replay = False
            self._active_advisory = item
            try:
                spoken = item.cached if item.cached is not None else await self.voice.say(
                    item.text, **{k: v for k, v in (("language", item.language), ("speed", item.speed)) if v is not None},
                    **({} if item.prefix else {"prefix": False}))
                if item.replay:
                    continue
                await self._speech_finished(spoken, item.text, item.event_id, item.display, **item.latency)
                if not item.done.done():
                    item.done.set_result(spoken)
            except Exception as exc:
                if not item.done.done():
                    item.done.set_exception(exc)
            finally:
                self._active_advisory = None
            if self._advisories and self._advisories[0] is item:
                self._advisories.pop(0)

    async def _speech_finished(self, spoken, text, event_id, display, **latency):
        first = self.tts.last_first_audio_ms
        self._measure("tts_first_audio_ms", first)
        self.out.add(spoken.stereo, self.voice.sample_rate)
        suffix = " [cut off by pilot]" if spoken.speech.cancelled else ""
        self._note("PILOT EAR", "[chime] " + spoken.text + suffix, tts_first_audio_ms=first, **latency)
        await self.audit(event_id, "speech", first, display_text=readable(display or text), **speech_payload(
            spoken.text, "pilot_ear", spoken.speech, spoken.stereo, self.demo_audio_dir,
            offset=(len(spoken.stereo) - len(spoken.speech.pcm) // 2) / spoken.speech.sample_rate))
        return spoken

    async def send(self, msg: BaseModel) -> bool:
        ok = await self.link.send(msg)
        (self.sent if ok else self.outbox).append(msg)
        return ok

    async def audit(self, event_id: str, stage: str, latency_ms: Optional[float] = None, **payload) -> None:
        payload.setdefault("party", "pilot_ear")
        await self.send(AuditRecord(event_id=event_id, stage=stage, actor="cockpit",
                                    latency_ms=latency_ms, payload=payload))

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _resolve(self, event_id: str, outcome: str) -> None:
        self.outcomes[event_id] = outcome
        self._resolved.setdefault(event_id, asyncio.Event()).set()

    async def wait_resolved(self, event_id: str, timeout_s: float = 30.0) -> str:
        ev = self._resolved.setdefault(event_id, asyncio.Event())
        try:
            await asyncio.wait_for(ev.wait(), timeout_s)
        except asyncio.TimeoutError:
            return "timeout"
        return self.outcomes.get(event_id, "timeout")

    # ------------------------------------------------------------ audio in

    async def run_audio(self, source: AudioSource, realtime: bool = False) -> list[AnomalyEvent]:
        """Process a whole audio source. Returns the AnomalyEvents raised.

        `realtime=True` paces frames at real time, as a live radio would deliver
        them (needed when replaying a file into Cartesia STT, docs/09 CF-10).
        """
        raised: list[AnomalyEvent] = []
        stt = None
        windows: list[OverlapWindow] = []
        squelch_open_ts = last_end = None
        frame_ms: list[float] = []
        self.detector.reset()
        paced_start = time.perf_counter()
        audio_s = 0.0
        radio_samples = []
        clip_audio = (save_audio(self.demo_audio_dir, source.pcm, source.sample_rate)
                      if hasattr(source, "pcm") else {})

        async def close_transmission(close_ts: int):
            nonlocal stt, windows, radio_samples
            windows += self.detector.flush()
            if windows:
                ev = await self._on_blocked(stt, windows, squelch_open_ts, close_ts)
                heard, radio_id = ev.heard_text, ev.event_id
                if ev:
                    raised.append(ev)
            else:
                heard = (await stt.finalize()).text
                radio_id = f"radio-{squelch_open_ts}"
            audio = clip_audio or (save_audio(self.demo_audio_dir, np.concatenate(radio_samples), source.sample_rate)
                                   if radio_samples else {})
            await self.audit(radio_id, "radio_received", heard_text=heard, party="radio", **audio)
            speakers = list(self.radio_speakers)
            await self.index_heard(heard, ("atc" if "atc" in speakers else speakers[0]) if speakers else "radio",
                                   squelch_open_ts, stepped_on=bool(windows), speakers=speakers,
                                   event_id=radio_id if windows else None)
            radio_samples = []
            if stt is not None and hasattr(stt, "__aexit__"):
                await stt.__aexit__(None, None, None)
            stt, windows = None, []

        for frame in source:
            if frame.squelch_open and stt is None:
                stt = self.manual_stt_factory()
                await stt.__aenter__()
                squelch_open_ts = frame.ts
                windows = []
            if stt is not None and frame.squelch_open:
                if self.demo_audio_dir is not None and not clip_audio:
                    radio_samples.append(frame.samples.copy())
                await stt.send_audio(_pcm16(frame.samples))
            t = time.perf_counter()
            windows += self.detector.process(frame)
            frame_ms.append((time.perf_counter() - t) * 1000)
            last_end = frame.end_ts
            if realtime:
                audio_s += len(frame.samples) / source.sample_rate
                delay = paced_start + audio_s - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
            if not frame.squelch_open and stt is not None:
                await close_transmission(frame.ts)
        if stt is not None:
            await close_transmission(last_end or now_ms())

        if frame_ms:
            self.latency.setdefault("detect_frame_ms", []).extend(frame_ms)
            self._note("SYSTEM", f"overlap detector: {len(frame_ms)} frames, "
                                 f"mean {np.mean(frame_ms):.3f} ms, max {np.max(frame_ms):.3f} ms per frame, "
                                 f"{len(raised)} blocked call(s)")
        return raised

    async def _on_blocked(self, stt, windows: list[OverlapWindow], open_ts: int, close_ts: int) -> AnomalyEvent:
        self._seq += 1
        event_id = f"evt-{self.callsign}-{now_ms()}-{self._seq}"
        t = time.perf_counter()
        heard = (await stt.finalize()).text if stt is not None else ""
        stt_ms = _ms(t)
        self._measure("stt_final_ms", stt_ms)
        self._note("RADIO", f"heard: {heard!r} (stepped-on {windows[0].start - open_ts}-"
                            f"{windows[-1].end - open_ts} ms into the call)", stt_final_ms=stt_ms)

        t = time.perf_counter()
        search: dict = {}
        hint = await derive_hint(self.memory, self.callsign, heard, self.flight_idx, self.airport_idx,
                                 evidence=search)
        hint_ms = _ms(t)
        self._measure("moss_ms", hint.moss_ms)

        event = AnomalyEvent(
            event_id=event_id, callsign=self.callsign, frequency=self.frequency,
            squelch_open=open_ts, squelch_close=close_ts,
            overlap_start=windows[0].start, overlap_end=windows[-1].end,
            heard_text=heard, local_hint=hint, gps=self.gps, taxiway_node=self.taxiway_node,
        )
        self.events.append(event)
        self._resolved.setdefault(event_id, asyncio.Event())
        self._sent_at[event_id] = time.perf_counter()
        # The event goes to the ground before the hint is spoken, so the controller's side
        # starts while the pilot is still hearing the hint.
        online = await self.send(event)
        if online:
            await self.audit(event_id, "detection", None, windows=[[w.start, w.end] for w in windows], heard_text=heard, party="radio")
            await self.audit(event_id, "cockpit_stt", stt_ms, heard_text=heard, party="radio")
            if search.get("query"):  # M3: what Moss found for the garbled fragment, for the console
                await self.audit(event_id, "hint_search", search.get("search_ms"), **search)
            await self.audit(event_id, "local_hint", hint.moss_ms, kind=hint.kind,
                             source_doc_id=hint.source_doc_id, total_ms=hint_ms, spoken_text=advisory_text(hint),
                             display_text=readable(advisory_text(hint)))
        # Local hint rules: advisory_text only says "Likely" for a restrictive hint with a source.
        await self.speak(advisory_text(hint), event_id=event_id, kind="hint", moss_ms=hint.moss_ms)
        await self._record(f"adv-{event_id}", advisory_text(hint), "advisory")
        if not online:
            await self.offline()
            self._resolve(event_id, "offline")
        return event

    async def offline(self) -> None:
        """Gateway unreachable: play the pre-generated alert and keep working locally."""
        if self.offline_alert is not None:
            if self._frequency_busy or self._advisories:
                await self.speak(msg_say_again(), event_id="offline", _cached=self.offline_alert)
                return
            self.out.add(self.offline_alert.stereo, self.voice.sample_rate)
            self._note("PILOT EAR", "[chime] " + self.offline_alert.text + " [offline alert, gateway unreachable]")
            spoken = self.offline_alert
            await self.audit("offline", "speech", display_text=readable(msg_say_again()), **speech_payload(
                spoken.text, "pilot_ear", spoken.speech, spoken.stereo, self.demo_audio_dir, offset=0.22))

    # ------------------------------------------------------------ gateway in

    async def on_message(self, msg) -> None:
        if isinstance(msg, ApprovedDirective) and msg.slots.callsign == self.callsign:
            self._spawn(self._on_approved(msg))
        elif isinstance(msg, RejectedDirective) and self._is_ours(msg.event_id):
            self._spawn(self._on_rejected(msg))

    def _is_ours(self, event_id: str) -> bool:
        return any(e.event_id == event_id for e in self.events)

    def _round_trip(self, event_id: str) -> Optional[float]:
        started = self._sent_at.get(event_id)
        if started is None:
            return None
        ms = _ms(started)
        self._measure("round_trip_ms", ms)
        return ms

    async def _on_rejected(self, msg: RejectedDirective) -> None:
        rt = self._round_trip(msg.event_id)
        spoken = await self.speak(REQUEST_SAY_AGAIN, event_id=msg.event_id, kind="rejection", round_trip_ms=rt)
        await self.audit(msg.event_id, "rejected_spoken", rt, rejected_via=msg.rejected_via, spoken_text=spoken.text,
                         display_text=readable(REQUEST_SAY_AGAIN))
        self._resolve(msg.event_id, "rejected")

    def set_language(self, language: Optional[str]) -> None:
        """The pilot's language for the private repeat of directives (None or "en": English only)."""
        self.language = language

    async def _say_translation(self, event_id: str, english: str) -> None:
        """Repeat an approved directive in the pilot's language, only if every number survived."""
        translated = await translate_advisory(self.translator, english, self.language)
        if translated is None:
            return
        await self.speak(translated, event_id=event_id, display=translated, kind="translation",
                         language=self.language, prefix=False)
        await self.audit(event_id, "translation_spoken", self.tts.last_first_audio_ms, language=self.language,
                         spoken_text=translated, display_text=translated, english=english, party="pilot_ear")

    async def _on_approved(self, msg: ApprovedDirective) -> None:
        rt = self._round_trip(msg.event_id)
        display = f"{msg.instruction_text.rstrip('.')}. Read back."
        spoken = await self.speak(msg_directive(msg.instruction_text), event_id=msg.event_id,
                                  display=display, kind="directive", round_trip_ms=rt)
        await self.audit(msg.event_id, "directive_spoken", self.tts.last_first_audio_ms,
                         round_trip_ms=rt, approved_via=msg.approved_via, spoken_text=spoken.text,
                         display_text=readable(display))
        await self._record(f"clr-{msg.event_id}", msg.instruction_text, "clearance")
        await self._say_translation(msg.event_id, display)
        outcome = await self.readback(msg)
        self._resolve(msg.event_id, outcome)

    # ------------------------------------------------------------ readback

    async def on_turn(self, ev: TurnEvent) -> None:
        if ev.type == "turn.start":
            if await self.voice.interrupt():
                self._note("SYSTEM", "pilot started talking: advisory voice cut off")

    async def readback(self, msg: ApprovedDirective) -> str:
        session = ReadbackSession(msg.event_id, msg.slots)
        stt = self.turn_stt_factory()
        async with stt:
            events: AsyncIterator[TurnEvent] = stt.events()
            async for ev in events:
                await self.on_turn(ev)
                if ev.type != "turn.end" or not ev.transcript:
                    continue
                t = time.perf_counter()
                step = session.on_readback(ev.transcript)
                verdict_ms = _ms(t)
                self._measure("readback_verdict_ms", verdict_ms)
                self._note("PILOT", f"reads back: {ev.transcript!r} -> "
                                    f"{'match' if step.result.match else 'MISMATCH: ' + step.reason}",
                           verdict_ms=verdict_ms)
                await self.send(step.result)
                await self.audit(msg.event_id, "readback", verdict_ms, attempt=step.result.attempt,
                                 match=step.result.match, reason=step.reason, heard_text=ev.transcript, party="pilot",
                                 **(getattr(stt, "last_input", None) or {}),
                                 **(save_audio(self.demo_audio_dir, np.frombuffer(stt.last_pcm, dtype="<i2"), stt.sample_rate)
                                    if getattr(stt, "last_pcm", None) else {}))
                # Corrections are spoken slower so the right number lands (Cartesia speed).
                await self.speak(step.say, event_id=msg.event_id,
                                 speed=CORRECTION_SPEED if not step.result.match else None)
                if session.done:
                    return "confirmed" if step.action == "confirmed" else "flagged"
        return "no_readback"

    # ------------------------------------------------------------ pilot query

    async def ask(self, question: str, audio: bytes | None = None, sample_rate: int = 16000):
        self._note("PILOT", f"asks: {question!r}")
        t = time.perf_counter()
        metrics: dict[str, float] = {}
        q = await answer_query(self.memory, self.flight_idx, self.callsign, question,
                               airport_index=self.airport_idx, answerer=self.answerer, metrics=metrics)
        self._measure("llm_first_token_ms", metrics.get("llm_first_token_ms"))
        answer_ms = _ms(t)
        self._measure("moss_ms", q.moss_ms)
        await self.speak(q.answer, event_id=q.query_id, moss_ms=q.moss_ms)
        self._measure("query_to_audio_ms", answer_ms + (self.tts.last_first_audio_ms or 0.0))
        await self.send(q)
        await self.audit(q.query_id, "pilot_query", q.moss_ms, source_doc_id=q.source_doc_id,
                         heard_text=question, answer=q.answer, party="pilot", **metrics,
                         **(save_audio(self.demo_audio_dir, np.frombuffer(audio, dtype="<i2"), sample_rate)
                            if audio else {}))
        return q

    # ------------------------------------------------------------ reporting

    def latency_summary(self) -> dict[str, dict[str, float]]:
        out = {}
        for k, v in self.latency.items():
            if v:
                out[k] = {"n": len(v), "mean": round(float(np.mean(v)), 3), "max": round(float(np.max(v)), 3)}
        return out


async def _main(args) -> int:
    edge = CockpitEdge(link=GatewayLink(args.url), audio_out=AudioOut(live=args.play),
                       memory=LocalMemory() if args.local else None, demo_audio_dir=args.demo_audio_dir)
    await edge.start()
    events = await edge.run_audio(WavFileSource(args.wav), realtime=bool(os.getenv("CARTESIA_API_KEY")))
    for ev in events:
        print(ev.event_id, await edge.wait_resolved(ev.event_id, args.timeout))
    await edge.stop()
    return 0


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("wav", nargs="?", default=str(ROOT / "assets" / "clips" / "stepped_on_call.wav"))
    p.add_argument("--url", default=None, help="gateway URL (default: UNSTEP_GATEWAY_URL)")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--demo-audio-dir", type=Path, nargs="?", const=DEFAULT_DEMO_AUDIO_DIR)
    p.add_argument("--play", action="store_true", help="also play through sounddevice")
    p.add_argument("--local", action="store_true", help="force local memory even if Moss keys exist")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(asyncio.run(_main(p.parse_args())))
