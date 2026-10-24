"""Controller Unstep-key approval with repeat-back and dashboard fallback (B10)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import time
import uuid
from collections import deque
from contextlib import aclosing
from pathlib import Path
from typing import Callable, Literal

import websockets

from unstep.config import gateway_url, ws_url
from unstep.cockpit.phraseology import normalize_for_speech
from unstep.cockpit.stt import CartesiaTurnSTT, FakeTurnSTT, ReplayTurnSTT, build_keyterms
from unstep.cockpit.tts import CartesiaTTS, FakeTTS, TTSEngine, chime, pcm_bytes_to_array, to_left_stereo
from unstep.contracts import ApprovedDirective, AuditRecord, ProposedDirective, RejectedDirective, VoiceApproval, unwrap, wrap

log = logging.getLogger("unstep.voice_approval")
Decision = Literal["approve", "reject", "unclear"]
APPROVE = {"approve", "approved", "affirm", "send it", "yes approve"}
REJECT = {"reject", "negative", "cancel", "ill reissue"}


class ApprovalLoop:
    """Pure state machine. Speech completion explicitly gates the decision."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.queue: deque[ProposedDirective] = deque()
        self.seen: set[str] = set()
        self.current: ProposedDirective | None = None
        self.attempt = 1
        self.deadline: float | None = None
        self.pending: VoiceApproval | None = None

    @staticmethod
    def classify(text: str) -> Decision:
        text = text.lower().replace("’", "'").replace("'", "")
        text = " ".join(re.sub(r"[^a-z0-9\s]", " ", text).split())
        if text in APPROVE:
            return "approve"
        if text in REJECT:
            return "reject"
        return "unclear"

    def enqueue(self, proposal: ProposedDirective) -> None:
        if proposal.event_id not in self.seen:
            self.seen.add(proposal.event_id)
            self.queue.append(proposal)

    def start_next(self) -> str | None:
        if self.current is not None or not self.queue:
            return None
        self.current = self.queue.popleft()
        self.attempt, self.deadline, self.pending = 1, None, None
        p = self.current
        return f"Blocked call to {p.slots.callsign}: {p.instruction_text.rstrip('. ')}. Approve?"

    def prompted(self) -> None:
        if self.current is not None and self.deadline is None:
            self.deadline = self.clock() + 10.0

    def _finish(self, text: str, decision: Decision) -> VoiceApproval:
        assert self.current is not None
        result = VoiceApproval(event_id=self.current.event_id, heard_text=text,
                               decision=decision, attempt=self.attempt)
        self.current, self.pending, self.deadline = None, None, None
        return result

    def timeout(self) -> VoiceApproval | None:
        if self.current and self.pending is None and self.deadline is not None and self.clock() >= self.deadline:
            return self._finish("", "unclear")
        return None

    def heard(self, event_id: str, text: str) -> str | VoiceApproval | None:
        if self.current is None or self.pending is not None or self.deadline is None:
            return None
        expired = self.timeout()
        if expired:
            return expired
        decision = self.classify(text) if event_id == self.current.event_id else "unclear"
        if decision == "unclear":
            if self.attempt == 1:
                self.attempt = 2
                return "Say again, approve or reject?"
            return self._finish(text, "unclear")
        self.pending = VoiceApproval(event_id=self.current.event_id, heard_text=text,
                                     decision=decision, attempt=self.attempt)
        if decision == "approve":
            return f"Approved, sending to {self.current.slots.callsign}."
        return "Rejected. Reissue by voice."

    def repeated(self) -> VoiceApproval | None:
        if self.current is None or self.pending is None:
            return None
        return self._finish(self.pending.heard_text, self.pending.decision)

    def decided(self, message: ApprovedDirective | RejectedDirective) -> bool:
        self.seen.add(message.event_id)
        self.queue = deque(p for p in self.queue if p.event_id != message.event_id)
        if self.current is None or self.current.event_id != message.event_id:
            return False
        self.current, self.pending, self.deadline = None, None, None
        return True


class ControllerVoice:
    """Cancellable headset playback; fake TTS stays silent and needs no device."""

    def __init__(self, tts: TTSEngine):
        self.tts = tts
        self.context: str | None = None

    async def _play(self, mono, sample_rate: int) -> None:
        if isinstance(self.tts, FakeTTS):
            return
        import sounddevice as sd

        sd.play(to_left_stereo(mono), sample_rate)
        try:
            while sd.get_stream().active:
                await asyncio.sleep(0.02)
        finally:
            sd.stop()

    async def say(self, text: str) -> None:
        self.context = str(uuid.uuid4())
        try:
            await self._play(chime(self.tts.sample_rate), self.tts.sample_rate)
            result = await self.tts.speak(normalize_for_speech(text), context_id=self.context)
            if result.cancelled:
                raise RuntimeError("controller speech cancelled")
            await self._play(pcm_bytes_to_array(result.pcm), result.sample_rate)
        except BaseException:
            await self.tts.cancel(self.context)
            raise
        finally:
            self.context = None


async def _until_deadline(loop: ApprovalLoop) -> None:
    """Sleep until the deadline has really passed. asyncio may wake a timer up to
    its clock resolution early (about 15 ms on Windows), and loop.timeout() only
    acts once clock() >= deadline, so a single sleep can miss the timeout."""
    while loop.deadline is not None and loop.clock() < loop.deadline:
        await asyncio.sleep(loop.deadline - loop.clock())


async def _answer(loop: ApprovalLoop, prompt: str, voice: ControllerVoice, stt_factory, send) -> None:
    assert loop.current is not None
    event_id = loop.current.event_id
    started = time.monotonic()

    async def emit(message: VoiceApproval) -> None:
        await send(wrap(message))
        await send(wrap(AuditRecord(event_id=event_id, stage="controller_voice", actor="controller_voice",
                                   latency_ms=(time.monotonic() - started) * 1000,
                                   payload=message.model_dump(mode="json"))))

    await voice.say(prompt)
    loop.prompted()
    try:
        async with asyncio.timeout(max(0, loop.deadline - loop.clock())):
            async with stt_factory() as stt:
                async with aclosing(stt.events()) as events:
                    async for event in events:
                        if event.type == "error":
                            raise RuntimeError("controller STT failed")
                        if event.type != "turn.end":
                            continue
                        action = loop.heard(event.raw.get("event_id", event_id), event.transcript)
                        if isinstance(action, VoiceApproval):
                            await emit(action)
                            return
                        if isinstance(action, str):
                            if loop.pending is not None:
                                break
                            await voice.say(action)
                    else:
                        await _until_deadline(loop)
                        action = loop.timeout()
            if loop.pending is None:
                if isinstance(action, VoiceApproval):
                    await emit(action)
                return
    except TimeoutError:
        await _until_deadline(loop)
        action = loop.timeout()
        if action:
            await emit(action)
        return
    # A timely answer may take longer to repeat aloud than the listening window.
    await voice.say(action)
    decision = loop.repeated()
    if decision:
        await emit(decision)


async def run(url: str, tts: TTSEngine, stt_factory) -> None:
    """Listen only to the injected controller-key STT source, never radio audio."""
    loop, voice, ready = ApprovalLoop(), ControllerVoice(tts), asyncio.Event()
    active: asyncio.Task | None = None
    async with websockets.connect(ws_url("controller_voice", url)) as ws:
        async def worker() -> None:
            nonlocal active
            while True:
                await ready.wait()
                ready.clear()
                while (prompt := loop.start_next()) is not None:
                    active = asyncio.create_task(_answer(loop, prompt, voice, stt_factory, ws.send))
                    try:
                        await active
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():
                            raise
                    active = None

        async with asyncio.TaskGroup() as tasks:
            task = tasks.create_task(worker())
            try:
                async for raw in ws:
                    env, msg = unwrap(raw)
                    if msg is None:
                        log.warning("gateway error: %s", env.data.get("message"))
                    elif isinstance(msg, ProposedDirective):
                        loop.enqueue(msg)
                        ready.set()
                    elif isinstance(msg, (ApprovedDirective, RejectedDirective)):
                        if loop.decided(msg) and active:
                            active.cancel()
                        ready.set()
            finally:
                task.cancel()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=None, help="gateway URL (default: UNSTEP_GATEWAY_URL)")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--answer-clip", type=Path)
    args = parser.parse_args()
    if args.live:
        if args.answer_clip is None:
            parser.error("--live requires --answer-clip with a controller Unstep-key recording")
        from dotenv import load_dotenv
        import numpy as np
        from unstep.cockpit.audio import read_wav

        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        pcm = (np.clip(read_wav(args.answer_clip), -1, 1) * 32767).astype("<i2").tobytes()
        terms = build_keyterms(extra=sorted(APPROVE | REJECT))
        tts = CartesiaTTS()
        factory = lambda: ReplayTurnSTT(lambda: CartesiaTurnSTT(keyterms=terms), [pcm, pcm])
    else:
        tts = FakeTTS()
        factory = lambda: FakeTurnSTT(["Approve"])

    async def go() -> None:
        try:
            await run(args.url or gateway_url(), tts, factory)
        finally:
            if isinstance(tts, CartesiaTTS):
                await tts.close()

    asyncio.run(go())


if __name__ == "__main__":
    main()
