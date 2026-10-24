"""Advisory voice (task A6): chime, ATC pronunciation, Cartesia Sonic TTS, left ear only.

Every message starts with a chime and "Advisory" (PRD FR-8, FR-16). Pilot speech
interrupts the voice by cancelling the Cartesia context (FR-10).

`CartesiaTTS` talks to wss://api.cartesia.ai/tts/websocket directly. `FakeTTS`
makes tones for tests and offline runs.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol

import numpy as np

from unstep.cockpit.phraseology import normalize_for_speech

SAMPLE_RATE = 24000
from unstep.config import cartesia_tts_model, cartesia_version

CARTESIA_VERSION = cartesia_version()
TTS_URL = "wss://api.cartesia.ai/tts/websocket"
PRONUNCIATION_DICT = Path(__file__).resolve().parents[2] / "assets" / "pronunciation" / "atc.json"


# ---------------------------------------------------------------- messages


def advisory(text: str) -> str:
    """Prefix with "Advisory." (once) and apply ATC pronunciation."""
    text = text.strip()
    if not text.lower().startswith("advisory"):
        text = f"Advisory. {text}"
    return normalize_for_speech(text)


def msg_blocked_hint(hint_text: str) -> str:
    return advisory(f"Transmission blocked. Likely {hint_text}. Awaiting controller.")


def msg_blocked_no_hint() -> str:
    return advisory("Transmission blocked. Awaiting controller.")


def msg_say_again() -> str:
    return advisory("Transmission blocked, request say again.")


def msg_directive(instruction_text: str, source: str | None = "Tower") -> str:
    """Says who the lost words came from, so the pilot never mistakes Unstep for the controller."""
    said_by = f"From {source}: " if source else ""
    return advisory(f"{said_by}{instruction_text.rstrip('.')}. Read back.")


def msg_readback(say: str) -> str:
    return advisory(say)


def msg_pilot_answer(answer: str) -> str:
    return advisory(answer)


def msg_no_record() -> str:
    return advisory("No record found. Ask the controller.")


# ---------------------------------------------------------------- audio helpers


def chime(sample_rate: int = SAMPLE_RATE, ms: int = 220) -> np.ndarray:
    """Two-note rising chime, int16 mono. Distinct from any ATC sound."""
    n = int(sample_rate * ms / 1000)
    t = np.arange(n) / sample_rate
    half = n // 2
    freq = np.where(np.arange(n) < half, 880.0, 1320.0)
    wave = 0.35 * np.sin(2 * np.pi * freq * t)
    env = np.minimum(1.0, np.minimum(np.arange(n), n - np.arange(n)) / (0.01 * sample_rate))
    return (wave * env * 32767).astype(np.int16)


def to_left_stereo(mono: np.ndarray) -> np.ndarray:
    """(n,) int16 mono -> (n, 2) with the right channel silent (PRD FR-7)."""
    mono = np.asarray(mono, dtype=np.int16).reshape(-1)
    stereo = np.zeros((mono.shape[0], 2), dtype=np.int16)
    stereo[:, 0] = mono
    return stereo


def pcm_bytes_to_array(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16)


def load_pronunciation_dict(path: Path = PRONUNCIATION_DICT) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- TTS engines


@dataclass
class SpeechResult:
    pcm: bytes  # int16 mono, little endian
    sample_rate: int
    first_audio_ms: Optional[float]
    words: list[tuple[str, float, float]] = field(default_factory=list)  # (word, start s, end s)
    cancelled: bool = False
    context_id: str = ""


class TTSEngine(Protocol):
    async def speak(self, text: str, context_id: Optional[str] = None,
                    on_chunk: Optional[Callable[[bytes], None]] = None) -> SpeechResult: ...

    async def cancel(self, context_id: str) -> None: ...


class FakeTTS:
    """Offline TTS: a quiet tone per word, fake word timestamps, no network."""

    def __init__(self, sample_rate: int = SAMPLE_RATE, word_s: float = 0.25):
        self.sample_rate = sample_rate
        self.word_s = word_s
        self.spoken: list[str] = []
        self.cancelled: set[str] = set()

    async def speak(self, text, context_id=None, on_chunk=None, **_options) -> SpeechResult:
        context_id = context_id or str(uuid.uuid4())
        self.spoken.append(text)
        words = text.split()
        n = int(self.sample_rate * self.word_s)
        t = np.arange(n) / self.sample_rate
        tone = (0.05 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
        chunks, stamps = [], []
        for i, w in enumerate(words):
            if context_id in self.cancelled:
                break
            chunk = tone.tobytes()
            chunks.append(chunk)
            if on_chunk:
                on_chunk(chunk)
            stamps.append((w, i * self.word_s, (i + 1) * self.word_s))
            await asyncio.sleep(0)
        return SpeechResult(b"".join(chunks), self.sample_rate, 0.0, stamps,
                            cancelled=context_id in self.cancelled, context_id=context_id)

    async def cancel(self, context_id: str) -> None:
        self.cancelled.add(context_id)


# A stalled context must never leave a scene busy forever.
SPEAK_DEADLINE_S = 20.0


class CartesiaTTS:
    """Cartesia Sonic over WebSocket. One connection, one context per message."""

    def __init__(self, api_key: Optional[str] = None, voice_id: Optional[str] = None,
                 model_id: Optional[str] = None, sample_rate: int = SAMPLE_RATE,
                 pronunciation_dict_id: Optional[str] = None, speed: float = 1.1,
                 volume: float = 1.2, emotion: str = "calm"):
        self.api_key = api_key or os.environ.get("CARTESIA_API_KEY")
        self.voice_id = voice_id or os.environ.get("CARTESIA_VOICE_ID")
        if not self.api_key or not self.voice_id:
            raise RuntimeError("CARTESIA_API_KEY and CARTESIA_VOICE_ID are required")
        self.model_id = model_id or cartesia_tts_model()
        self.sample_rate = sample_rate
        self.pronunciation_dict_id = pronunciation_dict_id or os.environ.get("CARTESIA_PRONUNCIATION_DICT_ID")
        self.generation_config = {"speed": speed, "volume": volume, "emotion": emotion}
        self._ws = None
        self._cancelled: set[str] = set()

    async def connect(self):
        import websockets

        if self._ws is None:
            self._ws = await websockets.connect(
                f"{TTS_URL}?cartesia_version={CARTESIA_VERSION}",
                additional_headers={"X-API-Key": self.api_key},
                max_size=None,
            )
        return self._ws

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    def request(self, text: str, context_id: str, language: Optional[str] = None,
                speed: Optional[float] = None) -> dict:
        generation = dict(self.generation_config)
        if speed is not None:
            generation["speed"] = speed  # Sonic's documented range is 0.6 to 1.5
        req = {
            "model_id": self.model_id,
            "transcript": text,
            "voice": {"id": self.voice_id},
            "language": language or "en",
            "context_id": context_id,
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": self.sample_rate},
            "continue": False,
            "add_timestamps": True,
            "generation_config": generation,
        }
        if self.pronunciation_dict_id:
            req["pronunciation_dict_id"] = self.pronunciation_dict_id
        return req

    async def speak(self, text, context_id=None, on_chunk=None, language=None, speed=None) -> SpeechResult:
        """Retry once on a fresh connection: Cartesia closes the WebSocket after it sits
        idle (for example while a presenter pauses between scenes)."""
        from websockets.exceptions import ConnectionClosed

        heard: list[bytes] = []

        def track(pcm: bytes) -> None:
            heard.append(pcm)
            if on_chunk:
                on_chunk(pcm)

        try:
            return await asyncio.wait_for(self._speak_once(text, context_id, track, language, speed), SPEAK_DEADLINE_S)
        except (ConnectionClosed, OSError, asyncio.TimeoutError):
            self._ws = None
            if heard:
                # Audio already went out: retrying would say the line twice.
                raise
            return await asyncio.wait_for(self._speak_once(text, context_id, on_chunk, language, speed), SPEAK_DEADLINE_S)

    async def _speak_once(self, text, context_id=None, on_chunk=None, language=None, speed=None) -> SpeechResult:
        ws = await self.connect()
        context_id = context_id or str(uuid.uuid4())
        started = time.perf_counter()
        first_ms: Optional[float] = None
        chunks: list[bytes] = []
        words: list[tuple[str, float, float]] = []
        await ws.send(json.dumps(self.request(text, context_id, language, speed)))
        while context_id not in self._cancelled:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.25)
            except asyncio.TimeoutError:
                continue  # re-check for cancel
            msg = json.loads(raw)
            if msg.get("context_id") not in (None, context_id):
                continue
            kind = msg.get("type")
            if kind == "chunk":
                if msg.get("data"):
                    if first_ms is None:
                        first_ms = (time.perf_counter() - started) * 1000
                    pcm = base64.b64decode(msg["data"])
                    chunks.append(pcm)
                    if on_chunk:
                        on_chunk(pcm)
                if msg.get("done"):
                    break
            elif kind == "timestamps":
                wt = msg.get("word_timestamps") or {}
                words += list(zip(wt.get("words", []), wt.get("start", []), wt.get("end", [])))
            elif kind == "done":
                break
            elif kind == "error":
                raise RuntimeError(f"Cartesia TTS error: {msg.get('title')}: {msg.get('message')}")
        return SpeechResult(b"".join(chunks), self.sample_rate, first_ms, words,
                            cancelled=context_id in self._cancelled, context_id=context_id)

    async def cancel(self, context_id: str) -> None:
        self._cancelled.add(context_id)
        if self._ws is not None:
            await self._ws.send(json.dumps({"context_id": context_id, "cancel": True}))


# ---------------------------------------------------------------- advisory voice


@dataclass
class Spoken:
    text: str
    stereo: np.ndarray  # (n, 2) int16, chime + speech, left channel only
    speech: SpeechResult


class AdvisoryVoice:
    """Chime + advisory text + left ear only. `interrupt()` stops the current message."""

    def __init__(self, tts: TTSEngine, sample_rate: int = SAMPLE_RATE,
                 play: Optional[Callable[[np.ndarray, int], None]] = None):
        self.tts = tts
        self.sample_rate = sample_rate
        self.play = play  # e.g. sounddevice.play; None keeps audio in memory only
        self.current: Optional[str] = None

    async def say(self, text: str, language: Optional[str] = None, speed: Optional[float] = None,
                  prefix: bool = True) -> Spoken:
        """`language`/`speed` go to Cartesia when set; `prefix=False` keeps a translated line
        free of the English "Advisory." (the translation carries its own)."""
        text = advisory(text) if prefix else text
        self.current = str(uuid.uuid4())
        ding = chime(self.sample_rate)
        if self.play:
            self.play(to_left_stereo(ding), self.sample_rate)
        options = {k: v for k, v in (("language", language), ("speed", speed)) if v is not None}
        # Only pass options when used, so TTS engines without them keep working.
        speech = await self.tts.speak(text, context_id=self.current, **options)
        self.current = None
        audio = np.concatenate([ding, pcm_bytes_to_array(speech.pcm)])
        stereo = to_left_stereo(audio)
        if self.play and speech.pcm:
            self.play(to_left_stereo(pcm_bytes_to_array(speech.pcm)), self.sample_rate)
        return Spoken(text, stereo, speech)

    async def interrupt(self) -> bool:
        """Call on Cartesia STT `turn.start` from the pilot mic."""
        if self.current is None:
            return False
        await self.tts.cancel(self.current)
        return True
