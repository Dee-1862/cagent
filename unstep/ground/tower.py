"""Tower transcription with keyed text and a separate word timing stream (B2)."""

from __future__ import annotations

import argparse
import asyncio
import difflib
import re
import time
import uuid
from pathlib import Path

import numpy as np
import websockets

from unstep import scenario
from unstep.clock import now_ms
from unstep.config import cartesia_stt_model, cartesia_stt_timestamp_model, ws_url
from unstep.cockpit.audio import read_wav
from unstep.cockpit.phraseology import AMBIGUOUS_DIGIT_WORDS, SPOKEN_DIGITS
from unstep.cockpit.stt import CartesiaManualSTT, build_keyterms
from unstep.contracts import AuditRecord, TowerTranscript, Word, wrap

# ------------------------------------------------------------ word alignment (P7b)
#
# Cartesia gives key terms only on ink-2 and word times only on ink-whisper (see
# docs/09-cartesia-feedback.md item 2), so the tower runs both and the two texts can
# differ ("Cessna 1-2-3" vs "Cessna one two three", or a word one model missed).
# align_words() keeps ink-2's words and borrows ink-whisper's times: both texts are
# cut into comparison keys (lowercase, digits split one per key, spoken digits as
# digits), matched with difflib, and each ink-2 word takes the span of the keys it
# matched. Words with no match get times interpolated between their neighbours and
# are listed in the alignment report, which goes out as an AuditRecord
# (stage "tower_word_alignment"), so the contract stays the same.


def _keys(word: str) -> list[str]:
    """Comparison keys for one word: 'Runway' -> ['runway'], '33.' -> ['3', '3'], 'tree' -> ['3']."""
    out = []
    for t in re.sub(r"[^a-z0-9]+", " ", word.lower()).split():
        if t.isdigit():
            out.extend(t)
        elif t in SPOKEN_DIGITS and t not in AMBIGUOUS_DIGIT_WORDS:
            out.append(SPOKEN_DIGITS[t])
        else:
            out.append(t)
    return out


def _display_words(text: str) -> list[str]:
    """ink-2's words as shown on screen, without edge punctuation ('33.' -> '33', '1-2-3' kept)."""
    words = (w.strip(".,!?;:\"'()") for w in text.split())
    return [w for w in words if w and _keys(w)]


def align_words(text: str, timed: list[Word], duration_s: float | None = None) -> tuple[list[Word], dict]:
    """ink-2 words with ink-whisper times, plus a report of which words had to be interpolated."""
    words = _display_words(text)
    timed = [w for w in timed if w.word.strip()]
    # One entry per key: (owner word index, start, end). A timed word with several keys
    # ("33" -> 3, 3) splits its span evenly between them.
    t_keys, t_spans = [], []
    for w in timed:
        ks = _keys(w.word)
        for i, k in enumerate(ks):
            step = (w.end - w.start) / len(ks)
            t_keys.append(k)
            t_spans.append((w.start + i * step, w.start + (i + 1) * step))
    x_keys, x_owner = [], []
    for i, w in enumerate(words):
        for k in _keys(w):
            x_keys.append(k)
            x_owner.append(i)
    spans: list[tuple[float, float] | None] = [None] * len(words)
    matcher = difflib.SequenceMatcher(a=x_keys, b=t_keys, autojunk=False)
    for block in matcher.get_matching_blocks():
        for j in range(block.size):
            i = x_owner[block.a + j]
            start, end = t_spans[block.b + j]
            spans[i] = (start, end) if spans[i] is None else (min(spans[i][0], start), max(spans[i][1], end))
    end_s = max([w.end for w in timed] + [duration_s or 0.0])
    interpolated = []
    i = 0
    while i < len(words):
        if spans[i] is not None:
            i += 1
            continue
        j = i
        while j < len(words) and spans[j] is None:
            j += 1
        lo = spans[i - 1][1] if i > 0 else 0.0
        hi = spans[j][0] if j < len(words) else end_s
        hi = max(hi, lo)
        step = (hi - lo) / (j - i)
        for k in range(i, j):
            spans[k] = (lo + (k - i) * step, lo + (k - i + 1) * step)
            interpolated.append({"index": k, "word": words[k]})
        i = j
    aligned = [Word(word=w, start=round(a, 3), end=round(b, 3)) for w, (a, b) in zip(words, spans)]
    report = {
        "text_words": len(words), "timed_words": len(timed),
        "matched": len(words) - len(interpolated), "interpolated": interpolated,
        "timing_text": " ".join(w.word.strip() for w in timed),
    }
    return aligned, report


def alignment_audit(transcript: TowerTranscript, report: dict) -> AuditRecord:
    """The alignment report as an audit record, keyed by the transcript id."""
    return AuditRecord(event_id=transcript.transcript_id, stage="tower_word_alignment", actor="tower",
                       payload={"transcript_id": transcript.transcript_id, **report})


class TowerTranscriber:
    def __init__(self, stt_factory=CartesiaManualSTT, runways=(), taxiways=(), realtime: bool = True):
        self.stt_factory = stt_factory
        self.realtime = realtime  # False: send the clip as fast as possible (manual endpoint accepts it)
        self.runways = runways
        self.taxiways = taxiways
        self.last_alignment: dict | None = None  # report from the latest transcribe(), see align_words

    async def transcribe(self, audio: bytes, ptt_start: int, ptt_end: int,
                         frequency: str, callsign: str | None = None) -> TowerTranscript:
        """Transcribe 16 kHz mono pcm_s16le, with offsets from the first sample."""
        if ptt_end < ptt_start or len(audio) % 2:
            raise ValueError("invalid PTT window or PCM audio")
        terms = build_keyterms(callsigns=[callsign] if callsign else (),
                               runways=self.runways, taxiways=self.taxiways)
        async with self.stt_factory(model=cartesia_stt_model(), keyterms=terms) as text_stt:
            async with self.stt_factory(model=cartesia_stt_timestamp_model(), timestamp_granularities=["word"]) as word_stt:
                started = time.monotonic()
                for offset in range(0, len(audio), 3200):
                    chunk = audio[offset:offset + 3200]
                    await asyncio.gather(text_stt.send_audio(chunk), word_stt.send_audio(chunk))
                    if self.realtime:
                        await asyncio.sleep(max(0, started + (offset + len(chunk)) / 32000 - time.monotonic()))
                if self.realtime:
                    await asyncio.sleep(max(0, started + (ptt_end - ptt_start) / 1000 - time.monotonic()))
                text, timing = await asyncio.gather(text_stt.finalize(), word_stt.finalize())
        words, self.last_alignment = align_words(text.text, timing.words, (ptt_end - ptt_start) / 1000)
        return TowerTranscript(
            transcript_id=f"tx-{uuid.uuid4().hex}", frequency=frequency, callsign=callsign,
            ptt_start=ptt_start, ptt_end=ptt_end, text=text.text, words=words,
        )


class TowerStream:
    """Tower transcription fed while the controller is still talking (P3).

    Same two Cartesia streams as TowerTranscriber (keyed text, word timings), but
    audio goes in as it is spoken, so it arrives at real-time pace by itself and
    both streams can finalize at key release instead of after a replay.
    """

    def __init__(self, stt_factory=CartesiaManualSTT, callsigns=(), runways=(), taxiways=()):
        terms = build_keyterms(callsigns=callsigns, runways=runways, taxiways=taxiways)
        self.text_stt = stt_factory(model=cartesia_stt_model(), keyterms=terms)
        self.word_stt = stt_factory(model=cartesia_stt_timestamp_model(), timestamp_granularities=["word"])
        self.frames = 0
        self.last_alignment: dict | None = None

    async def __aenter__(self):
        await asyncio.gather(self.text_stt.__aenter__(), self.word_stt.__aenter__())
        return self

    async def __aexit__(self, *exc):
        await asyncio.gather(self.text_stt.__aexit__(*exc), self.word_stt.__aexit__(*exc), return_exceptions=True)

    async def send_audio(self, pcm: bytes) -> None:
        self.frames += 1
        await asyncio.gather(self.text_stt.send_audio(pcm), self.word_stt.send_audio(pcm))

    async def finish(self, ptt_start: int, ptt_end: int, frequency: str,
                     callsign: str | None = None) -> TowerTranscript:
        text, timing = await asyncio.gather(self.text_stt.finalize(), self.word_stt.finalize())
        words, self.last_alignment = align_words(text.text, timing.words, (ptt_end - ptt_start) / 1000)
        return TowerTranscript(
            transcript_id=f"tx-{uuid.uuid4().hex}", frequency=frequency, callsign=callsign,
            ptt_start=ptt_start, ptt_end=ptt_end, text=text.text, words=words,
        )


class FakeTowerTranscriber:
    async def transcribe(self, audio: bytes, ptt_start: int, ptt_end: int,
                         frequency: str, callsign: str | None = None) -> TowerTranscript:
        return scenario.tower_transcript(ptt_start).model_copy(update={
            "transcript_id": f"tx-{uuid.uuid4().hex}", "ptt_end": ptt_end,
            "frequency": frequency, "callsign": callsign,
        })


async def run(args) -> None:
    samples = read_wav(args.clip)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    transcriber = TowerTranscriber() if args.live else FakeTowerTranscriber()
    async with websockets.connect(ws_url("tower", args.url)) as ws:
        start = args.ptt_start if args.ptt_start is not None else now_ms()
        transcript = await transcriber.transcribe(pcm, start, start + round(len(samples) / 16),
                                                  args.frequency, args.callsign)
        await ws.send(wrap(transcript))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clip", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--url")
    parser.add_argument("--ptt-start", type=int)
    parser.add_argument("--frequency", default=scenario.FREQUENCY)
    parser.add_argument("--callsign", default=scenario.CALLSIGN)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
