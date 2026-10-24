"""Voice and phraseology layer: normalizer, slot parsing, readback loop, TTS/STT plumbing."""

import asyncio
import os

import numpy as np
import pytest

from unstep.contracts import Slots
from unstep.cockpit import phraseology as ph
from unstep.cockpit.readback import ReadbackSession, check_readback, correction_text
from unstep.cockpit.stt import (
    MAX_KEYTERM_CHARS,
    MAX_KEYTERMS,
    FakeManualSTT,
    FakeTurnSTT,
    build_keyterms,
)
from unstep.cockpit.tts import (
    AdvisoryVoice,
    FakeTTS,
    advisory,
    chime,
    load_pronunciation_dict,
    msg_blocked_hint,
    msg_blocked_no_hint,
    msg_directive,
    msg_no_record,
    msg_pilot_answer,
    msg_readback,
    msg_say_again,
    to_left_stereo,
)

DIRECTIVE = Slots(callsign="N123AB", action="hold short", runway="33")


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- normalizer


@pytest.mark.parametrize("text,expected", [
    ("Runway 33", "runway tree tree"),
    ("runway 28L", "runway two eight left"),
    ("Runway 9R", "runway niner right"),
    ("Cessna 1-2-3, hold short Runway 33", "Cessna one two tree, hold short runway tree tree"),
    ("N123AB", "November one two tree alpha bravo"),
    ("issued 14:02", "issued one four zero two"),
    ("squawk 7500", "squawk seven fife zero zero"),
    ("climb 5", "climb fife"),
])
def test_normalize_for_speech(text, expected):
    assert ph.normalize_for_speech(text) == expected


# ---------------------------------------------------------------- parsing


@pytest.mark.parametrize("text,callsign,action,runway", [
    ("Cessna 1-2-3, hold short Runway 33", "Cessna 123", "hold short", "33"),
    ("hold short runway three three cessna one two three", "Cessna 123", "hold short", "33"),
    ("Hold short runway tree tree, Cessna one two tree", "Cessna 123", "hold short", "33"),
    ("Hold short Runway 23, Cessna 1-2-3", "Cessna 123", "hold short", "23"),
    ("hold short runway two three", "", "hold short", "23"),
    ("N123AB cleared for takeoff runway 28 left", "N123AB", "cleared for takeoff", "28L"),
    ("november one two three alpha bravo cleared to land runway niner", "N123AB", "cleared to land", "9"),
    ("Cessna 1-2-3 runway 33 line up and wait", "Cessna 123", "line up and wait", "33"),
    ("Cessna 1-2-3 go around", "Cessna 123", "go around", None),
    ("Cessna 1-2-3, runway 33, taxi via Bravo", "Cessna 123", "taxi", "33"),
    ("Cessna 1-2-3 cross runway 28R", "Cessna 123", "cross", "28R"),
    ("Cessna 1-2-3 hold position", "Cessna 123", "hold position", None),
])
def test_parse_instruction(text, callsign, action, runway):
    slots = ph.parse_instruction(text)
    assert slots is not None
    assert (slots.callsign, slots.action, slots.runway) == (callsign, action, runway)


def test_parse_instruction_none_without_action():
    assert ph.parse_instruction("Cessna 1-2-3 [static]") is None


def test_cleared_to_land_keeps_to():
    slots = ph.parse_instruction("Cessna one two three cleared to land runway two eight")
    assert slots.action == "cleared to land" and slots.runway == "28"


def test_restrictive_classification():
    assert ph.is_restrictive("hold short") and ph.is_restrictive("go around")
    assert not ph.is_restrictive("cleared for takeoff") and not ph.is_restrictive("cross")
    assert not ph.is_restrictive(None)


def test_callsigns_match():
    assert ph.callsigns_match("N123AB", "Cessna 123")
    assert ph.callsigns_match("N123AB", "N123AB")
    assert not ph.callsigns_match("N123AB", "Cessna 456")
    assert not ph.callsigns_match("N123AB", "")


# ---------------------------------------------------------------- readback


def test_check_readback_match():
    match, slots, reason = check_readback(DIRECTIVE, "Hold short Runway 33, Cessna 1-2-3")
    assert match and reason == "" and slots.runway == "33"


@pytest.mark.parametrize("text,reason_part", [
    ("Hold short Runway 23, Cessna 1-2-3", "runway 23"),
    ("Cleared for takeoff Runway 33, Cessna 1-2-3", "action"),
    ("Hold short Runway 33", "callsign missing"),
    ("Hold short Runway 33, Cessna 4-5-6", "callsign"),
    ("say again", "no instruction"),
])
def test_check_readback_mismatch(text, reason_part):
    match, _, reason = check_readback(DIRECTIVE, text)
    assert not match and reason_part in reason


def test_correction_text():
    _, heard, _ = check_readback(DIRECTIVE, "Hold short Runway 23, Cessna 1-2-3")
    assert correction_text(DIRECTIVE, heard) == "Readback incorrect. Runway tree tree."
    _, heard, _ = check_readback(DIRECTIVE, "Cleared for takeoff runway 33 Cessna 123")
    assert correction_text(DIRECTIVE, heard) == "Readback incorrect. Hold short runway tree tree."


def test_readback_session_wrong_then_right():
    s = ReadbackSession("evt-1", DIRECTIVE)
    step = s.on_readback("Hold short Runway 23, Cessna 1-2-3")
    assert step.action == "repeat" and step.result.attempt == 1 and not step.result.match
    assert step.say == "Readback incorrect. Runway tree tree."
    step = s.on_readback("Hold short Runway 33, Cessna 1-2-3")
    assert step.action == "confirmed" and step.result.match and step.result.attempt == 2
    with pytest.raises(RuntimeError):
        s.on_readback("again")


def test_readback_session_flags_controller_after_max_repeats():
    s = ReadbackSession("evt-2", DIRECTIVE, max_repeats=2)
    actions = [s.on_readback("Hold short Runway 23, Cessna 1-2-3").action for _ in range(3)]
    assert actions == ["repeat", "repeat", "flag_controller"]
    assert s.done


# ---------------------------------------------------------------- TTS


def test_every_message_starts_with_advisory():
    msgs = [
        msg_blocked_hint("hold short Runway 33"), msg_blocked_no_hint(), msg_say_again(),
        msg_directive("Cessna 1-2-3, hold short Runway 33"), msg_readback("Readback correct."),
        msg_pilot_answer("Hold short Runway 33, issued 14:02"), msg_no_record(),
        advisory("Advisory. already prefixed"),
    ]
    for m in msgs:
        assert m.startswith("Advisory.")
        assert m.count("Advisory") == 1


def test_directive_message_text():
    assert msg_directive("Cessna 1-2-3, hold short Runway 33") == \
        "Advisory. Cessna one two tree, hold short runway tree tree. Read back."


def test_left_channel_only():
    mono = (np.arange(100) - 50).astype(np.int16)
    st = to_left_stereo(mono)
    assert st.shape == (100, 2)
    assert np.array_equal(st[:, 0], mono)
    assert not st[:, 1].any()


def test_chime_is_short_and_audible():
    c = chime(24000)
    assert 0.1 < len(c) / 24000 < 0.5
    assert np.abs(c).max() > 5000


def test_advisory_voice_with_fake_tts():
    tts = FakeTTS()
    voice = AdvisoryVoice(tts)
    spoken = run(voice.say("Cessna 1-2-3, hold short Runway 33. Read back."))
    assert spoken.text.startswith("Advisory.")
    assert tts.spoken == [spoken.text]
    assert spoken.stereo.shape[1] == 2 and not spoken.stereo[:, 1].any()
    assert len(spoken.stereo) > len(chime())
    assert spoken.speech.words[0][0] == "Advisory."


def test_interrupt_cancels_current_message():
    tts = FakeTTS()
    voice = AdvisoryVoice(tts)

    async def scenario():
        task = asyncio.create_task(voice.say("Cessna 1-2-3, hold short Runway 33. Read back."))
        await asyncio.sleep(0)  # let it start
        interrupted = await voice.interrupt()
        spoken = await task
        return interrupted, spoken

    interrupted, spoken = run(scenario())
    assert interrupted and spoken.speech.cancelled
    assert run(voice.interrupt()) is False  # nothing playing


def test_pronunciation_dict_entries():
    entries = load_pronunciation_dict()
    texts = {e["text"] for e in entries}
    assert {"niner", "tree", "fife"} <= texts
    assert all(set(e) == {"text", "pronunciation"} for e in entries)


# ---------------------------------------------------------------- STT


def test_keyterms_order_and_limits():
    terms = build_keyterms(callsigns=["N123AB", "Cessna 1-2-3"], runways=["33", "28L"], taxiways=["Bravo"])
    assert terms[:2] == ["N123AB", "Cessna 1-2-3"]
    assert "Runway 33" in terms and "Taxiway Bravo" in terms
    assert terms.index("hold short") < terms.index("Runway 33") < terms.index("Taxiway Bravo")


def test_keyterms_respect_cartesia_limits():
    many = [f"Taxiway {chr(65 + i % 26)}{i}" for i in range(300)]
    terms = build_keyterms(callsigns=["N123AB"], taxiways=many)
    assert len(terms) <= MAX_KEYTERMS
    assert sum(len(t) for t in terms) <= MAX_KEYTERM_CHARS
    assert terms[0] == "N123AB"
    assert len({t.lower() for t in terms}) == len(terms)


def test_fake_manual_stt():
    async def go():
        async with FakeManualSTT(["Cessna 1-2-3 [static]"]) as stt:
            for _ in range(5):
                await stt.send_audio(b"\x00" * 320)
            return stt.frames, await stt.finalize(), await stt.finalize()

    frames, first, second = run(go())
    assert frames == 5 and first.text == "Cessna 1-2-3 [static]" and second.text == ""


def test_fake_turn_stt_drives_readback():
    async def go():
        session = ReadbackSession("evt-3", DIRECTIVE)
        voice = AdvisoryVoice(FakeTTS())
        steps, starts = [], 0
        stt = FakeTurnSTT(["Hold short Runway 23, Cessna 1-2-3", "Hold short Runway 33, Cessna 1-2-3"])
        async with stt:
            async for ev in stt.events():
                if ev.type == "turn.start":
                    starts += 1
                    await voice.interrupt()
                elif ev.type == "turn.end":
                    step = session.on_readback(ev.transcript)
                    steps.append(step.action)
                    await voice.say(step.say)
        return steps, starts

    steps, starts = run(go())
    assert steps == ["repeat", "confirmed"] and starts == 2


# ---------------------------------------------------------------- real API (skipped offline)

needs_key = pytest.mark.skipif(
    not (os.environ.get("CARTESIA_API_KEY") and os.environ.get("CARTESIA_VOICE_ID")),
    reason="CARTESIA_API_KEY and CARTESIA_VOICE_ID not set",
)


@needs_key
def test_real_cartesia_tts_first_audio():
    from unstep.cockpit.tts import CartesiaTTS

    async def go():
        tts = CartesiaTTS()
        try:
            return await tts.speak(msg_directive("Cessna 1-2-3, hold short Runway 33"))
        finally:
            await tts.close()

    res = run(go())
    assert res.pcm and res.first_audio_ms is not None


# ---------------------------------------------------------------- replaying clips into turn STT (no network)


class _ScriptedTurnConn:
    """Stands in for one CartesiaTurnSTT connection: ends the turn once speech has arrived."""

    def __init__(self, text, speech_bytes, early=None):
        self.text, self.speech_bytes, self.early = text, speech_bytes, early
        self.got = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def send_audio(self, pcm):
        self.got += len(pcm)

    async def events(self):
        from unstep.cockpit.stt import TurnEvent

        yield TurnEvent("turn.start")
        if self.early:  # a pause mid-clip closes a turn before all speech is sent
            yield TurnEvent("turn.end", self.early)
        while self.got < self.speech_bytes:
            await asyncio.sleep(0.01)
        yield TurnEvent("turn.update", self.text)
        yield TurnEvent("turn.end", "")  # transcript only in the last update


def test_replay_turn_stt_one_turn_per_clip_and_merges_early_turn_end():
    from unstep.cockpit.stt import ReplayTurnSTT

    clip = b"\x01\x00" * 3200  # 0.2 s at 16 kHz
    conns = iter([
        _ScriptedTurnConn("Cessna one two three", len(clip), early="Hold short runway tree tree"),
        _ScriptedTurnConn("Hold short runway three three, Cessna one two three", len(clip)),
    ])
    stt = ReplayTurnSTT(lambda: next(conns), [clip, clip], trailing_silence_s=0.1, timeout_s=5)

    async def collect():
        return [ev.transcript async for ev in stt.events() if ev.type == "turn.end"]

    ends = run(collect())
    assert ends == ["Hold short runway tree tree Cessna one two three",
                    "Hold short runway three three, Cessna one two three"]
    assert len(stt.turn_end_ms) == 2
