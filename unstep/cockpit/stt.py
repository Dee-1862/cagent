"""Cartesia Ink-2 speech-to-text for the cockpit (tasks A3, A7, A10).

Two modes, as in docs/08-advice.md section 4.1:

- `CartesiaManualSTT` (wss://api.cartesia.ai/stt/websocket): stream audio while
  the channel is open and send `finalize` when the squelch closes. Returns text
  and word timestamps. Used for what the cockpit heard.
- `CartesiaTurnSTT` (wss://api.cartesia.ai/stt/turns/websocket): the model finds
  turns and emits turn.start / turn.update / turn.eager_end / turn.resume / turn.end.
  Used for readbacks and pilot queries. `turn.start` interrupts the advisory voice.

Key terms are set when the connection opens and can't change mid-stream.
`FakeManualSTT` and `FakeTurnSTT` replay scripted transcripts for tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable, Optional
from urllib.parse import quote, urlencode

from unstep.contracts import Word

log = logging.getLogger("unstep.stt")

from unstep.config import cartesia_stt_model, cartesia_version

CARTESIA_VERSION = cartesia_version()
STT_URL = "wss://api.cartesia.ai/stt/websocket"
TURNS_URL = "wss://api.cartesia.ai/stt/turns/websocket"

MAX_KEYTERMS = 100
MAX_KEYTERM_CHARS = 1200

CRITICAL_PHRASES = [
    "hold short", "line up and wait", "cleared for takeoff", "cleared to land",
    "go around", "hold position", "cross runway", "readback", "say again", "Unstep",
]
ATC_WORDS = ["niner", "tree", "fife", "fower", "squawk", "NOTAM", "Unstep, what was my last clearance"]


def build_keyterms(callsigns: Iterable[str] = (), runways: Iterable[str] = (),
                   taxiways: Iterable[str] = (), extra: Iterable[str] = (),
                   max_terms: int = MAX_KEYTERMS, max_chars: int = MAX_KEYTERM_CHARS) -> list[str]:
    """Most important first: callsigns, critical phrases, runways, taxiways, ATC words, extras.

    Stays within Cartesia's limits (100 terms, 1200 characters total). Lower
    priority terms are dropped first.
    """
    ordered: list[str] = []
    ordered += [c for c in callsigns]
    ordered += CRITICAL_PHRASES
    ordered += [r if r.lower().startswith("runway") else f"Runway {r}" for r in runways]
    ordered += [t if t.lower().startswith("taxiway") else f"Taxiway {t}" for t in taxiways]
    ordered += ATC_WORDS
    ordered += list(extra)

    out, seen, chars = [], set(), 0
    for term in ordered:
        term = term.strip()
        key = term.lower()
        if not term or key in seen:
            continue
        if len(out) >= max_terms or chars + len(term) > max_chars:
            continue
        out.append(term)
        seen.add(key)
        chars += len(term)
    return out


def _url(base: str, params: list[tuple[str, str]]) -> str:
    return f"{base}?{urlencode(params, quote_via=quote)}"


@dataclass
class Transcript:
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class TurnEvent:
    type: str  # turn.start, turn.update, turn.eager_end, turn.resume, turn.end, error
    transcript: str = ""
    raw: dict = field(default_factory=dict)


class CartesiaManualSTT:
    """Manual finalize. Usage:

        async with CartesiaManualSTT(keyterms=[...]) as stt:
            for frame in frames_while_squelch_open:
                await stt.send_audio(frame)
            transcript = await stt.finalize()
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 sample_rate: int = 16000, keyterms: Iterable[str] = (),
                 timestamp_granularities: Iterable[str] = ()):
        self.api_key = api_key or os.environ.get("CARTESIA_API_KEY")
        if not self.api_key:
            raise RuntimeError("CARTESIA_API_KEY is required")
        params = [("model", model or cartesia_stt_model()), ("encoding", "pcm_s16le"), ("sample_rate", str(sample_rate)),
                  ("cartesia_version", CARTESIA_VERSION)]
        params += [("keyterm", k) for k in keyterms]
        params += [("timestamp_granularities", value) for value in timestamp_granularities]
        self.url = _url(STT_URL, params)
        self._ws = None

    async def __aenter__(self):
        import websockets

        self._ws = await websockets.connect(self.url, additional_headers={"X-API-Key": self.api_key}, max_size=None)
        return self

    async def __aexit__(self, *exc):
        if self._ws is not None:
            try:
                await self._ws.send("close")
            finally:
                await self._ws.close()

    async def send_audio(self, pcm: bytes) -> None:
        await self._ws.send(pcm)

    async def finalize(self, timeout_s: float = 10.0) -> Transcript:
        """Send `finalize` and collect final transcript chunks until `flush_done`."""
        await self._ws.send("finalize")
        text, words = "", []
        while True:
            msg = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=timeout_s))
            kind = msg.get("type")
            if kind == "transcript" and msg.get("is_final"):
                text += msg.get("text", "")  # deltas: don't strip or add spaces
                words += [Word(word=w["word"], start=w["start"], end=w["end"]) for w in msg.get("words") or []]
            elif kind in ("flush_done", "done"):
                return Transcript(text.strip(), words)
            elif kind == "error":
                raise RuntimeError(f"Cartesia STT error: {msg.get('title')}: {msg.get('message')}")


class CartesiaTurnSTT:
    """Turn-based STT. Send audio with `send_audio`, read `events()`."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 sample_rate: int = 16000, keyterms: Iterable[str] = (),
                 turn_end_threshold: float = 0.2, turn_end_timeout_ms: int = 1500):
        self.api_key = api_key or os.environ.get("CARTESIA_API_KEY")
        if not self.api_key:
            raise RuntimeError("CARTESIA_API_KEY is required")
        # Readbacks and queries are short: close turns quickly.
        params = [("model", model or cartesia_stt_model()), ("encoding", "pcm_s16le"), ("sample_rate", str(sample_rate)),
                  ("cartesia_version", CARTESIA_VERSION),
                  ("turn_end_threshold", str(turn_end_threshold)),
                  ("turn_end_timeout_ms", str(turn_end_timeout_ms))]
        params += [("keyterm", k) for k in keyterms]
        self.url = _url(TURNS_URL, params)
        self._ws = None

    async def __aenter__(self):
        import websockets

        self._ws = await websockets.connect(self.url, additional_headers={"X-API-Key": self.api_key}, max_size=None)
        return self

    async def __aexit__(self, *exc):
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "close"}))
            finally:
                await self._ws.close()

    async def send_audio(self, pcm: bytes) -> None:
        await self._ws.send(pcm)

    async def configure(self, **turn) -> None:
        """Change turn settings mid-stream, e.g. configure(end_threshold=0.1)."""
        await self._ws.send(json.dumps({"type": "config", "turn": turn}))

    async def events(self) -> AsyncIterator[TurnEvent]:
        async for raw in self._ws:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            kind = msg.get("type", "")
            if kind == "connected":
                continue
            yield TurnEvent(kind, msg.get("transcript", ""), msg)


# ---------------------------------------------------------------- fakes


class FakeManualSTT:
    """Returns scripted transcripts in order, one per finalize()."""

    def __init__(self, transcripts: Iterable[Transcript | str]):
        self._queue = [t if isinstance(t, Transcript) else Transcript(t) for t in transcripts]
        self.frames = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def send_audio(self, pcm: bytes) -> None:
        self.frames += 1

    async def finalize(self, timeout_s: float = 10.0) -> Transcript:
        if not self._queue:
            return Transcript("")
        return self._queue.pop(0)


class FakeTurnSTT:
    """Each scripted utterance becomes turn.start, turn.update, turn.end."""

    def __init__(self, utterances: Iterable[str]):
        self.utterances = list(utterances)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def send_audio(self, pcm: bytes) -> None:
        return None

    async def configure(self, **turn) -> None:
        return None

    async def events(self) -> AsyncIterator[TurnEvent]:
        for text in self.utterances:
            yield TurnEvent("turn.start")
            half = " ".join(text.split()[: max(1, len(text.split()) // 2)])
            yield TurnEvent("turn.update", half)
            yield TurnEvent("turn.end", text)
            await asyncio.sleep(0)


# ---------------------------------------------------------------- replay of recorded clips


async def send_paced(stt, pcm: bytes, sample_rate: int = 16000, chunk_ms: int = 100,
                     trailing_silence_s: float = 0.0, on_speech_sent=None) -> float:
    """Send pcm_s16le in `chunk_ms` chunks at real time, then optional silence.

    Real-time pacing matters: the turns endpoint returns empty transcripts when
    audio arrives faster than real time (docs/09 CF-10). Returns the
    perf_counter time at which the last speech chunk was sent, and also passes
    it to `on_speech_sent` as soon as that happens (before the silence).
    """
    import time

    step = sample_rate * 2 * chunk_ms // 1000
    data = pcm + b"\x00\x00" * int(trailing_silence_s * sample_rate)
    speech_end = len(pcm)
    started = time.perf_counter()
    speech_sent = started
    for n, i in enumerate(range(0, len(data), step)):
        await stt.send_audio(data[i:i + step])
        if i + step >= speech_end and i < speech_end:
            speech_sent = time.perf_counter()
            if on_speech_sent:
                on_speech_sent(speech_sent)
        delay = started + (n + 1) * chunk_ms / 1000 - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
    return speech_sent


class ReplayTurnSTT:
    """Plays recorded clips (one per pilot turn) into a turn STT, paced at real time.

    Opens one connection per clip from `factory` (e.g. CartesiaTurnSTT) and
    yields its events until that clip's `turn.end`. A clip is only sent when
    the consumer asks for the next event, so the cockpit can speak in between.
    `turn_end_ms[i]` is the time from the end of clip i's speech to its turn.end.
    """

    def __init__(self, factory, clips: Iterable[bytes], sample_rate: int = 16000,
                 trailing_silence_s: float = 2.5, timeout_s: float = 20.0):
        self.factory = factory
        self.clips = list(clips)
        self.sample_rate = sample_rate
        self.trailing_silence_s = trailing_silence_s
        self.timeout_s = timeout_s
        self.turn_end_ms: list[float] = []
        self.last_pcm: bytes | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def send_audio(self, pcm: bytes) -> None:
        return None

    async def configure(self, **turn) -> None:
        return None

    async def events(self) -> AsyncIterator[TurnEvent]:
        import time

        while self.clips:
            pcm = self.clips.pop(0)
            self.last_pcm = pcm
            async with self.factory() as stt:
                sent = asyncio.get_running_loop().create_future()

                async def sender():
                    await send_paced(stt, pcm, self.sample_rate, trailing_silence_s=self.trailing_silence_s,
                                     on_speech_sent=sent.set_result)

                task = asyncio.create_task(sender())
                last, parts = "", []
                deadline = time.perf_counter() + self.timeout_s + len(pcm) / (2 * self.sample_rate)
                try:
                    it = stt.events().__aiter__()
                    while True:
                        try:
                            ev = await asyncio.wait_for(it.__anext__(), max(0.1, deadline - time.perf_counter()))
                        except (asyncio.TimeoutError, StopAsyncIteration):
                            text = " ".join(parts + ([last] if last else []))
                            if not text:
                                raise RuntimeError("turn STT: no turn.end and no transcript for clip")
                            log.warning("turn STT: no final turn.end; using partial transcript %r", text)
                            yield TurnEvent("turn.end", text, {})
                            break
                        if ev.type == "error":
                            raise RuntimeError(f"turn STT error: {ev.raw.get('title')}: {ev.raw.get('message')}")
                        if ev.transcript:
                            last = ev.transcript
                        if ev.type == "turn.end":
                            text = (ev.transcript or last).strip()
                            if not sent.done():
                                # A pause mid-clip ended a turn early: keep it and wait for the rest.
                                if text:
                                    parts.append(text)
                                last = ""
                                continue
                            self.turn_end_ms.append(round((time.perf_counter() - sent.result()) * 1000, 1))
                            yield TurnEvent("turn.end", " ".join(parts + ([text] if text else [])), ev.raw)
                            break
                        if ev.type == "turn.start" and parts:
                            continue
                        log.debug("turn STT %s %r", ev.type, ev.transcript)
                        yield ev
                finally:
                    task.cancel()
