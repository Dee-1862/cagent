"""P7b: ink-2's words carry ink-whisper's times (unstep/ground/tower.py align_words)."""

import asyncio

from unstep.cockpit.stt import FakeManualSTT, Transcript
from unstep.contracts import Word
from unstep.ground import tower
from unstep.ground.blocked import blocked_words


def W(word, start, end):
    return Word(word=word, start=start, end=end)


WHISPER = [W(" Cessna", 0.0, 0.4), W(" one", 0.4, 0.6), W(" two", 0.6, 0.8), W(" three,", 0.8, 1.0),
           W(" hold", 1.1, 1.3), W(" short", 1.3, 1.6), W(" runway", 1.6, 2.0), W(" three", 2.0, 2.2),
           W(" three.", 2.2, 2.4)]


def test_ink2_words_take_whisper_times_across_digit_styles():
    words, report = tower.align_words("Cessna 1-2-3, hold short runway 33.", WHISPER)
    assert [w.word for w in words] == ["Cessna", "1-2-3", "hold", "short", "runway", "33"]
    by = {w.word: (w.start, w.end) for w in words}
    assert by["1-2-3"] == (0.4, 1.0)  # spans "one two three"
    assert by["33"] == (2.0, 2.4)
    assert by["hold"] == (1.1, 1.3)
    assert report["matched"] == 6 and report["interpolated"] == []
    assert report["text_words"] == 6 and report["timed_words"] == 9


def test_one_timed_word_with_two_digits_is_split_between_two_text_words():
    words, report = tower.align_words("runway three three", [W("runway", 0.0, 0.5), W("33", 0.5, 1.0)])
    assert [(w.start, w.end) for w in words] == [(0.0, 0.5), (0.5, 0.75), (0.75, 1.0)]
    assert not report["interpolated"]


def test_unmatched_words_are_interpolated_between_neighbours_and_flagged():
    timed = [W("hold", 1.0, 1.2), W("short", 1.2, 1.5), W("runway", 2.0, 2.4)]
    words, report = tower.align_words("hold short of runway", timed)
    of = words[2]
    assert of.word == "of" and (of.start, of.end) == (1.5, 2.0)
    assert report["interpolated"] == [{"index": 2, "word": "of"}] and report["matched"] == 3


def test_edges_and_no_timings():
    words, report = tower.align_words("Cessna hold short", [W("hold", 1.0, 1.2), W("short", 1.2, 1.4)], 2.0)
    assert (words[0].start, words[0].end) == (0.0, 1.0)  # before the first anchor: from 0
    words, report = tower.align_words("hold short now", [W("hold", 0.0, 0.2), W("short", 0.2, 0.4)], 1.0)
    assert (words[2].start, words[2].end) == (0.4, 1.0)  # after the last anchor: to the end of the call
    words, report = tower.align_words("hold short", [], None)
    assert all(w.start == w.end == 0 for w in words) and len(report["interpolated"]) == 2
    assert tower.align_words("", WHISPER)[0] == []


def test_blocked_words_use_ink2_spelling():
    words, _ = tower.align_words("Cessna 1-2-3, hold short runway 33.", WHISPER)
    t = tower.TowerTranscript(transcript_id="tx-1", frequency="118.7", ptt_start=10_000, ptt_end=12_400,
                              text="Cessna 1-2-3, hold short runway 33.", words=words)
    assert blocked_words(t, 11_100, 12_400) == ["hold", "short", "runway", "33"]


class Pair:
    """Fake ink-2 (text) and ink-whisper (times) streams."""

    def __init__(self, text, timed):
        self.text, self.timed = text, timed

    def __call__(self, **kw):
        if kw.get("model") == "ink-whisper":
            return FakeManualSTT([Transcript("cessna one two three hold short runway three three", self.timed)])
        return FakeManualSTT([Transcript(self.text)])


def test_tower_stream_aligns_and_reports():
    async def go():
        stream = tower.TowerStream(stt_factory=Pair("Cessna 1-2-3, hold short runway 33.", WHISPER))
        async with stream:
            await stream.send_audio(b"\x00\x00" * 1600)
            t = await stream.finish(10_000, 12_400, "118.7", "N123AB")
        assert [w.word for w in t.words][-1] == "33" and t.words[-1].start == 2.0
        assert stream.last_alignment["matched"] == 6
        audit = tower.alignment_audit(t, stream.last_alignment)
        assert audit.stage == "tower_word_alignment" and audit.event_id == t.transcript_id
        assert audit.payload["transcript_id"] == t.transcript_id and audit.payload["interpolated"] == []

    asyncio.run(go())


def test_tower_transcriber_aligns(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(tower.asyncio, "sleep", no_sleep)
    tr = tower.TowerTranscriber(stt_factory=Pair("Cessna 1-2-3, hold short of runway 33.", WHISPER))
    t = asyncio.run(tr.transcribe(b"\x00\x00" * 1600, 10_000, 12_400, "118.7", "N123AB"))
    assert [w.word for w in t.words] == ["Cessna", "1-2-3", "hold", "short", "of", "runway", "33"]
    assert tr.last_alignment["interpolated"] == [{"index": 4, "word": "of"}]
