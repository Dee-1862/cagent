"""P3: push-to-talk audio streams to STT while the key is held; the old one-clip `mic` path still works."""

import asyncio
import base64

import numpy as np

from unstep.clock import now_ms
from unstep.cockpit.audio import SAMPLE_RATE
from unstep.cockpit.phraseology import callsigns_match
from unstep.cockpit.stt import Transcript
from unstep.contracts import TowerTranscript, Word
from unstep.live.room import Station

from tests.test_live_room import clip, make_room, only_trace, stepped_on, wait_for  # noqa: F401 (fixture)


class FakeStream:
    """Stands in for Cartesia: records frames as they arrive, answers at finalize."""

    def __init__(self, text):
        self.text, self.frames, self.opened, self.closed = text, [], False, False
        self.final_at = None

    async def __aenter__(self):
        self.opened = True
        return self

    async def __aexit__(self, *exc):
        self.closed = True

    async def send_audio(self, pcm):
        self.frames.append(pcm)

    async def finalize(self):
        self.final_at = len(self.frames)
        return Transcript(self.text)

    async def finish(self, ptt_start, ptt_end, frequency, callsign=None):
        self.final_at = len(self.frames)
        words = [Word(word=w, start=i * 0.3, end=i * 0.3 + 0.25) for i, w in enumerate(self.text.split())]
        return TowerTranscript(transcript_id="tx-streamed", frequency=frequency, callsign=callsign,
                               ptt_start=ptt_start, ptt_end=ptt_end, text=self.text, words=words)


def frames(seconds, start_ms):
    pcm = (np.clip(clip("correct_readback.wav")[: int(SAMPLE_RATE * seconds)], -1, 1) * 32767).astype("<i2").tobytes()
    step = SAMPLE_RATE * 2 // 10  # 100 ms
    return [{"type": "mic_frame", "start_ms": start_ms, "pcm": base64.b64encode(pcm[i:i + step]).decode()}
            for i in range(0, len(pcm), step)]


def test_streamed_readback_is_checked_without_replaying_the_clip(make_room):
    async def go():
        room, atc, pilot = await make_room()
        streams = {}

        def factory(s: Station):
            streams[s.id] = FakeStream("Hold short runway three three, Cessna one two three")
            return streams[s.id]

        room.stream_stt_factory = factory
        await stepped_on(room)
        await wait_for(lambda: only_trace(room) and only_trace(room)["status"] in ("needs_you", "delivered"))
        if only_trace(room)["status"] == "needs_you":
            await room.decide(only_trace(room)["event_id"], approve=True)
        await wait_for(lambda: only_trace(room)["status"] == "delivered")
        sent = frames(2.0, now_ms() - 8000)
        for f in sent:
            await room.handle("N123AB", f)
        await asyncio.sleep(0.05)
        assert "N123AB" in room.key_since  # streaming holds the key down for everyone to see
        await room.handle("N123AB", {"type": "mic_end"})
        await wait_for(lambda: only_trace(room)["status"] == "confirmed")
        s = streams["N123AB"]
        assert len(s.frames) == len(sent) and s.final_at == len(sent) and s.closed
        assert "N123AB" not in room.key_since and not room.stream_results
        await room.stop()

    asyncio.run(go())


def test_streamed_tower_call_becomes_the_tower_transcript(make_room):
    async def go():
        room, atc, pilot = await make_room()
        room.stream_stt_factory = lambda s: FakeStream("Cessna one two three, hold short runway three three.")
        for f in frames(1.5, now_ms() - 8000):
            await room.handle("atc", f)
        await room.handle("atc", {"type": "mic_end"})
        await wait_for(lambda: room.transcripts)
        t = next(iter(room.transcripts.values()))
        assert t.text == "Cessna one two three, hold short runway three three."
        assert callsigns_match(t.callsign, "N123AB")
        assert t.ptt_end - t.ptt_start == 1500
        await room.stop()

    asyncio.run(go())


def test_a_tap_is_not_a_call_and_offline_streams_still_go_on_air(make_room):
    async def go():
        room, atc, pilot = await make_room()
        start = now_ms()
        await room.handle("H456", frames(0.1, start)[0])
        await room.handle("H456", {"type": "mic_end"})
        assert not room.pending and "H456" not in room.key_since
        for f in frames(1.0, start + 500):  # offline: no STT stream, the clip still goes on air
            await room.handle("H456", f)
        tx = await room.mic_end("H456")
        assert tx is not None and tx.end_ms - tx.start_ms == 1000 and not room.stream_results
        await asyncio.sleep(0.05)
        assert any(m["type"] == "onair" and m["station"] == "H456" for m in pilot.messages)
        await room.stop()

    asyncio.run(go())


def test_a_failing_stream_falls_back_to_the_clip(make_room):
    async def go():
        room, atc, pilot = await make_room()

        class Broken(FakeStream):
            async def finalize(self):
                raise RuntimeError("finalize hung")

        room.stream_stt_factory = lambda s: Broken("x")
        for f in frames(1.0, now_ms() - 8000):
            await room.handle("N123AB", f)
        tx = await room.mic_end("N123AB")
        assert await room._streamed(tx) is None  # consumers take the old path
        await room.stop()

    asyncio.run(go())
