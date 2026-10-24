"""Live captions and waveform levels: interim STT text while the key is held, TTS word times for typed lines."""

import asyncio

from unstep.clock import now_ms
from unstep.cockpit.stt import Transcript

from tests.test_live_room import make_room, wait_for  # noqa: F401 (fixture)
from tests.test_stream_mic import FakeStream, frames


class PartialStream(FakeStream):
    """Like Cartesia with interim results: a growing partial after every few frames."""

    on_text = None

    async def send_audio(self, pcm):
        await super().send_audio(pcm)
        words = self.text.split()
        n = min(len(words), len(self.frames) // 3)
        if n and self.on_text and len(self.frames) % 3 == 0:
            self.on_text(" " + words[n - 1], " ".join(words[:n]))  # (delta, so_far) like CartesiaManualSTT

    async def finalize(self):
        self.final_at = len(self.frames)
        return Transcript(self.text)


def of(browser, kind):
    return [m for m in browser.messages if m["type"] == kind]


def test_interim_captions_while_held_then_the_final_one(make_room):
    async def go():
        room, atc, pilot = await make_room()
        room.stream_stt_factory = lambda s: PartialStream("Tower, Cessna one two three, request taxi to runway three three")
        for f in frames(1.5, now_ms() - 3000):
            await room.handle("N123AB", f)
        await asyncio.sleep(0.05)
        partials = [m for m in of(atc, "caption") if not m["final"]]
        assert partials and partials[0]["source"] == "stt" and partials[0]["lag_ms"] is not None
        assert len(partials[-1]["text"]) > len(partials[0]["text"])  # words added as they arrive
        assert of(atc, "level") and all(0 <= v <= 1 for m in of(atc, "level") for v in m["rms"])
        await room.handle("N123AB", {"type": "mic_end"})
        await wait_for(lambda: any(m["final"] for m in of(atc, "caption")))
        final = next(m for m in of(atc, "caption") if m["final"])
        assert final["text"].endswith("three three")
        kinds = {w["kind"] for w in final["words"]}
        assert {"callsign", "runway", "action"} <= kinds
        assert final["id"] == partials[0]["id"] and final["station"] == "N123AB"
        await room.stop()

    asyncio.run(go())


def test_typed_lines_get_captions_from_tts_word_times(make_room):
    async def go():
        room, atc, pilot = await make_room()
        tx = await room.say("atc", "Cessna one two three, hold short runway three three.")
        await wait_for(lambda: any(m["final"] for m in of(pilot, "caption")))
        caps = of(pilot, "caption")
        assert all(c["source"] == "tts" and c["id"] == tx.tx_id for c in caps)
        assert [len(c["words"]) for c in caps] == list(range(1, len(caps) + 1))  # one word at a time
        assert caps[-1]["words"][-1]["at_ms"] >= tx.start_ms
        assert any(m["id"] == tx.tx_id for m in of(pilot, "level"))
        await room.stop()

    asyncio.run(go())
