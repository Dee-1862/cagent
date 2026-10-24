"""UNSTEP_CAPTION_SOURCE=turns: captions come from a second, display-only Cartesia turns stream."""

import asyncio
import base64

from unstep.clock import now_ms
from unstep.cockpit.stt import TurnEvent

from tests.test_live_room import make_room, wait_for  # noqa: F401 (fixture)
from tests.test_stream_mic import FakeStream, frames


class FakeManual(FakeStream):
    on_text = None  # like CartesiaManualSTT: the room sets it when the manual stream owns the captions


class FakeTurns:
    """Emits one partial per 3 audio frames it hears, then ends the turn when the audio stops."""

    def __init__(self):
        self.frames, self.q, self.words = 0, asyncio.Queue(), ["Tower", "hold", "short", "runway", "three", "three"]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def send_audio(self, pcm):
        self.frames += 1
        if self.frames % 3 == 0 and self.frames // 3 <= len(self.words):
            self.q.put_nowait(TurnEvent("turn.update", " ".join(self.words[: self.frames // 3])))

    async def events(self):
        while True:
            yield await self.q.get()


def captions(browser, station):
    return [m for m in browser.messages if m.get("type") == "caption" and m["station"] == station]


def test_turns_source_shows_partials_while_the_key_is_held_and_the_final_wins(make_room, monkeypatch):
    async def go():
        monkeypatch.setenv("UNSTEP_CAPTION_SOURCE", "turns")
        room, atc, pilot = await make_room()
        manual = FakeManual("Hold short runway three three")
        room.stream_stt_factory = lambda s: manual
        turns = FakeTurns()
        room.caption_turns_factory = lambda s: turns
        room.caption_source = "turns"
        start = now_ms() - 8000
        for f in frames(1.2, start):
            await room.handle("N123AB", f)
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)
        partial = captions(pilot, "N123AB")
        assert len(partial) >= 3 and all(not c["final"] for c in partial)
        assert [len(c["text"].split()) for c in partial] == sorted(len(c["text"].split()) for c in partial)
        assert manual.on_text is None  # the manual stream does not also write captions
        await room.mic_end("N123AB")
        await wait_for(lambda: any(c["final"] for c in captions(pilot, "N123AB")))
        n = len(captions(pilot, "N123AB"))
        await asyncio.sleep(0.4)
        assert len(captions(pilot, "N123AB")) == n  # nothing interim arrives after the final
        assert captions(pilot, "N123AB")[-1]["final"]
        await room.stop()

    asyncio.run(go())


def test_default_source_still_uses_the_manual_stream(make_room, monkeypatch):
    async def go():
        monkeypatch.delenv("UNSTEP_CAPTION_SOURCE", raising=False)
        room, atc, pilot = await make_room()
        assert room.caption_source == "manual"
        manual = FakeManual("Hold short runway three three")
        room.stream_stt_factory = lambda s: manual
        room.caption_turns_factory = lambda s: (_ for _ in ()).throw(AssertionError("turns stream must not open"))
        for f in frames(0.5, now_ms() - 8000):
            await room.handle("N123AB", f)
        await asyncio.sleep(0.1)
        assert callable(manual.on_text)  # the room attached its caption callback to the manual stream
        await room.mic_end("N123AB")
        await room.stop()

    asyncio.run(go())
