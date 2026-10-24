"""R14 item 2: the pilot's phone gets the advisory chunk by chunk, not after the whole line."""

import asyncio
import base64

import numpy as np

from unstep.cockpit.tts import FakeTTS, chime
from unstep.live.room import StreamingTTS

from tests.test_live_room import make_room, stepped_on, wait_for  # noqa: F401 (fixture)


class Room:
    def __init__(self):
        self.sent, self.streamed_advisory = [], set()

    def send_to(self, stations, message):
        self.sent.append((stations, message))


def test_chunks_go_out_as_they_arrive_with_the_chime_first():
    room, tts = Room(), FakeTTS()
    stream = StreamingTTS(tts, room, "N123AB")
    seen = []

    async def go():
        return await stream.speak("Advisory hold short", context_id="ctx-1", on_chunk=seen.append)

    result = asyncio.run(go())
    msgs = [m for _, m in room.sent]
    chunks = [m for m in msgs if m["type"] == "advisory_chunk"]
    assert [c["seq"] for c in chunks] == [0, 1, 2] and all(c["id"] == "ctx-1" for c in chunks)
    assert all(st == {"N123AB"} for st, _ in room.sent)
    first = base64.b64decode(chunks[0]["pcm"])
    ding = chime(tts.sample_rate).tobytes()
    assert first.startswith(ding) and first[len(ding):] == seen[0]  # chime, then the first speech chunk
    assert b"".join(base64.b64decode(c["pcm"]) for c in chunks) == ding + result.pcm
    assert msgs[-1] == {"type": "advisory_end", "id": "ctx-1", "chunks": 3, "cancelled": False}
    assert room.streamed_advisory == {"N123AB"}


def test_a_cut_off_line_ends_cancelled_and_the_full_clip_still_plays():
    room, tts = Room(), FakeTTS()
    stream = StreamingTTS(tts, room, "N123AB")

    async def go():
        task = asyncio.create_task(stream.speak("one two three four five six", context_id="ctx-2"))
        await asyncio.sleep(0)
        await tts.cancel("ctx-2")
        return await task

    assert asyncio.run(go()).cancelled
    end = room.sent[-1][1]
    assert end["type"] == "advisory_end" and end["cancelled"] is True
    assert not room.streamed_advisory  # not marked: the replayed clip must play in full


def test_full_clip_is_flagged_streamed_once():
    from unstep.live.room import BrowserAudioOut

    room = Room()
    out = BrowserAudioOut(room, "N123AB")
    room.streamed_advisory.add("N123AB")
    stereo = np.zeros((10, 2), dtype=np.int16)
    out.add(stereo, 24000)
    out.add(stereo, 24000)
    flags = [m["streamed"] for _, m in room.sent]
    assert flags == [True, False]


def test_room_streams_the_private_advisory_to_the_pilot(make_room):
    async def go():
        room, atc, pilot = await make_room()
        await stepped_on(room)
        await wait_for(lambda: any(m["type"] == "advisory_audio" for m in pilot.messages))
        kinds = [m["type"] for m in pilot.messages if m["type"].startswith("advisory")]
        assert kinds.index("advisory_chunk") < kinds.index("advisory_end") < kinds.index("advisory_audio")
        assert next(m for m in pilot.messages if m["type"] == "advisory_audio")["streamed"] is True
        await room.stop()

    asyncio.run(go())
