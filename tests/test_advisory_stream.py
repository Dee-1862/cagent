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

    def advisory_report(self, *args, **kw):
        self.reports = [*getattr(self, "reports", []), args]


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


def test_report_says_how_long_it_waited_spoke_and_overlapped(make_room):
    from unstep.clock import now_ms

    async def go():
        room, atc, pilot = await make_room()
        room.last_wait["N123AB"] = 812.0
        start = now_ms() - 2000
        room.key_log.append(("H456", start + 500, start + 900))  # someone keyed during the advisory
        report = room.advisory_report("N123AB", "ctx-9", start, 1500.0, cancelled=False)
        assert report["waited_ms"] == 812.0 and report["spoke_ms"] == 1500.0
        assert report["overlapped_ms"] == 400.0 and report["overlapped_by"] == ["H456"]
        clean = room.advisory_report("N123AB", "ctx-10", now_ms() - 10_000, 1000.0, cancelled=False)
        assert clean["overlapped_ms"] == 0 and clean["waited_ms"] == 0
        await asyncio.sleep(0.05)
        assert any(m["type"] == "advisory_report" for m in atc.messages)
        assert any(m["type"] == "advisory_report" for m in pilot.messages)
        await room.stop()

    asyncio.run(go())


def test_a_real_advisory_sends_a_report(make_room):
    async def go():
        room, atc, pilot = await make_room()
        await stepped_on(room)
        mine = lambda: [m for m in atc.messages if m["type"] == "advisory_report" and m["station"] == "N123AB"]  # noqa: E731
        await wait_for(lambda: mine())
        r = mine()[0]
        assert r["station"] == "N123AB" and r["spoke_ms"] > 220 and r["overlapped_ms"] >= 0
        await room.stop()

    asyncio.run(go())


def test_voice_options_reach_the_engine():
    """The cockpit asks for a slower correction (speed) and a language; the room's wrappers must pass them on."""
    from unstep.live.room import SerialTTS

    seen = {}

    class Engine:
        sample_rate = 24000

        async def speak(self, text, context_id=None, on_chunk=None, **options):
            seen.update(options)
            from unstep.cockpit.tts import SpeechResult
            return SpeechResult(b"\x00\x00" * 10, 24000, 0.0, [])

    asyncio.run(StreamingTTS(Engine(), Room(), "N123AB").speak("x", speed=0.85, language="es"))
    assert seen == {"speed": 0.85, "language": "es"}
    seen.clear()
    asyncio.run(SerialTTS(Engine()).speak("x", speed=0.85))
    assert seen == {"speed": 0.85}
