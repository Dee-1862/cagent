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
import os
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable, Optional
from urllib.parse import urlencode

from unstep.contracts import Word

CARTESIA_VERSION = "2026-08-14"
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
    return f"{base}?{urlencode(params)}"


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

    def __init__(self, api_key: Optional[str] = None, model: str = "ink-2",
                 sample_rate: int = 16000, keyterms: Iterable[str] = ()):
        self.api_key = api_key or os.environ.get("CARTESIA_API_KEY")
        if not self.api_key:
            raise RuntimeError("CARTESIA_API_KEY is required")
        params = [("model", model), ("encoding", "pcm_s16le"), ("sample_rate", str(sample_rate)),
                  ("cartesia_version", CARTESIA_VERSION)]
        params += [("keyterm", k) for k in keyterms]
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

    def __init__(self, api_key: Optional[str] = None, model: str = "ink-2",
                 sample_rate: int = 16000, keyterms: Iterable[str] = (),
                 turn_end_threshold: float = 0.2, turn_end_timeout_ms: int = 1500):
        self.api_key = api_key or os.environ.get("CARTESIA_API_KEY")
        if not self.api_key:
            raise RuntimeError("CARTESIA_API_KEY is required")
        # Readbacks and queries are short: close turns quickly.
        params = [("model", model), ("encoding", "pcm_s16le"), ("sample_rate", str(sample_rate)),
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
