"""Live push-to-talk microphone for presenter mode (`python -m unstep.demo --live --mic`).

The browser streams 16 kHz mono PCM16 frames over /demo/mic while the presenter
holds V, then sends {"type": "end"} on release. The V release is the end of the
turn (the Unstep key release in the PRD), so each utterance goes to Cartesia's
manual endpoint and is finalized on release.

`MicSource` queues utterances. `MicTurns` is a turn-STT-like source (`async with`,
`events()`, `last_pcm`, `sample_rate`) that presenter scenes use in place of the
recorded clips. If nobody speaks within the wait, that turn falls back to the
recorded clip and says so on screen and in the audit.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable

from unstep import scenario
from unstep.cockpit.stt import TurnEvent

log = logging.getLogger("unstep.demo.mic")

SAMPLE_RATE = 16000
MAX_FRAME_BYTES = 64_000          # 2 s of PCM16 per frame; the browser sends about 100 ms
MAX_UTTERANCE_S = 20.0            # a stuck V key can't stream forever
FRAME_GAP_S = 5.0                 # no frame and no "end" for this long ends the utterance
MIC_WAIT_S = 30.0                 # presenter silence before falling back to the clip
LIVE_MIC = "live mic"
RECORDED = "recorded clip"


def live_mic_stt():
    """Cartesia ink-2, manual endpoint, ATC key terms for this demo."""
    from unstep.cockpit.stt import CartesiaManualSTT, build_keyterms

    return CartesiaManualSTT(keyterms=build_keyterms(
        callsigns=[scenario.CALLSIGN, scenario.SPOKEN_CALLSIGN], runways=["33", "23"],
        extra=["approve", "reject"]))


@dataclass
class Utterance:
    frames: asyncio.Queue = field(default_factory=asyncio.Queue)


class MicSource:
    """Receives browser frames and hands out whole utterances, one at a time."""

    def __init__(self, stt_factory: Callable[[], object] = live_mic_stt):
        self.stt_factory = stt_factory
        self.utterances: asyncio.Queue[Utterance] = asyncio.Queue()
        self.current: Utterance | None = None
        self.waiting = False
        self.role: str | None = None
        self.hint = ""
        self.status = ""
        self.transcript = ""
        self.notify: Callable[[], Awaitable[None]] | None = None

    def state(self) -> dict:
        return {"enabled": True, "waiting": self.waiting, "role": self.role, "hint": self.hint,
                "status": self.status, "transcript": self.transcript}

    async def _changed(self) -> None:
        if self.notify:
            await self.notify()

    # Browser side (the /demo/mic WebSocket).

    def feed(self, frame: bytes) -> None:
        """Frames are dropped unless a scene is waiting for speech."""
        if not self.waiting or not frame or len(frame) > MAX_FRAME_BYTES or len(frame) % 2:
            return
        if self.current is None:
            self.current = Utterance()
            self.utterances.put_nowait(self.current)
        self.current.frames.put_nowait(frame)

    def end(self) -> None:
        if self.current is not None:
            self.current.frames.put_nowait(None)
            self.current = None

    # Scene side.

    async def expect(self, role: str, hint: str) -> None:
        while not self.utterances.empty():  # speech from before this prompt is stale
            self.utterances.get_nowait()
        self.current = None
        self.waiting, self.role, self.hint = True, role, hint
        self.status, self.transcript = "Hold V to talk", ""
        await self._changed()

    async def finish(self, status: str, transcript: str = "") -> None:
        self.waiting, self.status, self.transcript = False, status, transcript
        self.current = None
        await self._changed()

    def reset(self) -> None:
        self.waiting, self.role, self.hint, self.status, self.transcript = False, None, "", "", ""
        self.current = None
        while not self.utterances.empty():
            self.utterances.get_nowait()

    async def transcribe(self, utterance: Utterance) -> tuple[bytes, str]:
        """Stream the utterance into a fresh STT connection; finalize on V release."""
        pcm = bytearray()
        async with self.stt_factory() as stt:
            while len(pcm) < MAX_UTTERANCE_S * SAMPLE_RATE * 2:
                try:
                    frame = await asyncio.wait_for(utterance.frames.get(), FRAME_GAP_S)
                except asyncio.TimeoutError:
                    break
                if frame is None:
                    break
                pcm += frame
                await stt.send_audio(frame)
            transcript = await stt.finalize()
        return bytes(pcm), transcript.text.strip()


class MicTurns:
    """One turn per hint, spoken live; each silent turn falls back to clip `fallback(i)`.

    `say_again`, if given, is spoken on an empty transcript and the same turn is
    asked again once. Without it (controller approval) the empty transcript is
    passed on, so ApprovalLoop answers "Say again" itself.
    """

    sample_rate = SAMPLE_RATE

    def __init__(self, mic: MicSource, role: str, hints: list[str], fallback: Callable[[int], object], *,
                 wait_s: float = MIC_WAIT_S, say_again: Callable[[], Awaitable[None]] | None = None,
                 on_turn: Callable[[str, bool], None] | None = None,
                 on_fallback: Callable[[str], None] | None = None):
        self.mic, self.role, self.hints, self.fallback = mic, role, list(hints), fallback
        self.wait_s, self.say_again = wait_s, say_again
        self.on_turn, self.on_fallback = on_turn, on_fallback
        self.last_pcm: bytes | None = None
        self.last_input: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        if self.mic.waiting:
            await self.mic.finish("")
        return None

    async def send_audio(self, pcm: bytes) -> None:
        return None

    async def configure(self, **turn) -> None:
        return None

    async def events(self) -> AsyncIterator[TurnEvent]:
        for index, hint in enumerate(self.hints):
            retried = False
            while True:
                await self.mic.expect(self.role, hint)
                try:
                    utterance = await asyncio.wait_for(self.mic.utterances.get(), self.wait_s)
                except asyncio.TimeoutError:
                    async for event in self._recorded(index, f"no speech in {self.wait_s:g} s"):
                        yield event
                    break
                yield TurnEvent("turn.start", "", {"input": LIVE_MIC})
                self.mic.status = "Transcribing"
                await self.mic._changed()
                try:
                    pcm, text = await self.mic.transcribe(utterance)
                except Exception as exc:  # STT down: the scene still runs, on the clip, labeled
                    log.warning("live mic STT failed: %s", exc)
                    async for event in self._recorded(index, f"mic STT failed ({type(exc).__name__})"):
                        yield event
                    break
                self.last_pcm, self.last_input = pcm, {"input": LIVE_MIC}
                if not text and self.say_again and not retried:
                    retried = True
                    await self.mic.finish("Unclear: say again")
                    await self.say_again()
                    continue
                if self.on_turn:  # before the broadcast, so the screen labels it live at once
                    self.on_turn(self.role, True)
                await self.mic.finish("Heard" if text else "Unclear", text)
                yield TurnEvent("turn.end", text, {"input": LIVE_MIC})
                break

    async def _recorded(self, index: int, reason: str) -> AsyncIterator[TurnEvent]:
        label = f"Mic fallback: {reason}, recorded {self.role} clip used"
        if self.on_fallback:
            self.on_fallback(label)
        await self.mic.finish(label)
        source = self.fallback(index)
        async with source:
            async for event in source.events():
                if event.type == "turn.end":
                    self.last_pcm = getattr(source, "last_pcm", None)
                    self.last_input = {"input": RECORDED, "mic_fallback": reason}
                    if self.on_turn:
                        self.on_turn(self.role, False)
                    yield event
                    return
                yield event
