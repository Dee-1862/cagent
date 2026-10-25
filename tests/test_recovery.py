"""C1, tower side: the controller hears who stepped on them and what they said."""

import asyncio

from unstep.contracts import AuditRecord

from tests.test_live_room import make_room, stepped_on, wait_for  # noqa: F401 (fixture)


def test_controller_hears_who_was_blocked_and_what_they_said(make_room):
    async def go():
        room, atc, pilot = await make_room()
        sent = []
        link = room.links["tower"]
        original = link.send

        async def send(msg):
            sent.append(msg)
            return await original(msg)

        link.send = send
        await stepped_on(room)
        await wait_for(lambda: any(m["type"] == "recovery" for m in atc.messages))
        rec = next(m for m in atc.messages if m["type"] == "recovery")
        assert rec["from_station"] == "H456" and rec["to"] == "atc" and rec["kind"] == "blocked_caller"
        assert "request transition" in rec["text"] and rec["text"].startswith("Helicopter")
        assert rec["audio"]  # spoken in Unstep's own voice
        assert not any(m["type"] == "recovery" for m in pilot.messages)  # only the controller
        await wait_for(lambda: any(isinstance(m, AuditRecord) and m.stage == "recovery" for m in sent))
        await room.stop()

    asyncio.run(go())


def test_stale_recovery_is_dropped(make_room, monkeypatch):
    from unstep.live import room as room_mod

    monkeypatch.setattr(room_mod, "RECOVERY_STALE_MS", -1)

    async def go():
        room, atc, pilot = await make_room()
        await stepped_on(room)
        await asyncio.sleep(1.0)
        assert not any(m["type"] == "recovery" for m in atc.messages)
        await room.stop()

    asyncio.run(go())


def test_blocked_pilot_is_told_to_say_again(make_room):
    async def go():
        room, atc, pilot = await make_room()
        calls = []
        for cs, edge in room.edges.items():
            async def notify(event_id, cs=cs, **kw):
                calls.append((cs, event_id))
            edge.notify_blocked = notify
        await stepped_on(room)
        await wait_for(lambda: calls)
        assert [c[0] for c in calls] == ["H456"]  # the helicopter's own call was blocked; tower is not a cockpit
        assert calls[0][1].startswith("rec-tx-")
        await room.stop()

    asyncio.run(go())


def test_spoken_cues_are_fixed_phrases_in_the_left_ear(make_room):
    import base64
    import io

    import soundfile as sf

    async def go():
        room, atc, pilot = await make_room()
        msg = await room.say_cue("N123AB", "joined")
        assert msg["text"] == "You are Plane A." and msg["type"] == "cue_audio"
        audio, _ = sf.read(io.BytesIO(base64.b64decode(msg["audio"])), dtype="int16")
        assert audio.shape[1] == 2 and not audio[:, 1].any()  # right channel silent
        assert await room.say_cue("N123AB", "say something rude") is None  # only agreed phrases
        assert await room.say_cue("atc", "busy") is None  # pilots only
        await room.handle("N123AB", {"type": "cue", "name": "busy"})
        await wait_for(lambda: any(m["type"] == "cue_audio" and m["name"] == "busy" for m in pilot.messages))
        await room.stop()

    asyncio.run(go())


def test_cue_and_recovery_speech_share_one_connection_instead_of_opening_one_per_line(make_room):
    """A fresh, never-closed Cartesia connection per line leaked sockets until HTTP 429 (R29). Cues and the
    tower's recovery line must go through the shared controller voice."""
    async def go():
        room, atc, pilot = await make_room()
        opened = []

        class Engine:
            sample_rate = 24000

            def __init__(self):
                opened.append(self)

            async def speak(self, text, context_id=None, on_chunk=None, **kw):
                from unstep.cockpit.tts import SpeechResult
                return SpeechResult(b"\x00\x00" * 2400, 24000, 0.0, [])

        room.advisory_tts = None
        room._advisory_tts = lambda: opened[0] if opened else Engine()  # one engine, however often it is asked for
        for name in ("joined", "busy", "talked_over"):
            await room.say_cue("N123AB", name)
        shared = room._controller_tts()
        assert shared is room._controller_tts() and len(opened) == 1
        await room.stop()

    asyncio.run(go())
