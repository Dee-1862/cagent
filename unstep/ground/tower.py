"""Tower transcription with keyed text and a separate word timing stream (B2)."""

from __future__ import annotations

import argparse
import asyncio
import time
import uuid
from pathlib import Path

import numpy as np
import websockets

from unstep import scenario
from unstep.clock import now_ms
from unstep.config import cartesia_stt_model, cartesia_stt_timestamp_model, ws_url
from unstep.cockpit.audio import read_wav
from unstep.cockpit.stt import CartesiaManualSTT, build_keyterms
from unstep.contracts import TowerTranscript, wrap


class TowerTranscriber:
    def __init__(self, stt_factory=CartesiaManualSTT, runways=(), taxiways=()):
        self.stt_factory = stt_factory
        self.runways = runways
        self.taxiways = taxiways

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
                    await asyncio.sleep(max(0, started + (offset + len(chunk)) / 32000 - time.monotonic()))
                await asyncio.sleep(max(0, started + (ptt_end - ptt_start) / 1000 - time.monotonic()))
                text, timing = await asyncio.gather(text_stt.finalize(), word_stt.finalize())
        return TowerTranscript(
            transcript_id=f"tx-{uuid.uuid4().hex}", frequency=frequency, callsign=callsign,
            ptt_start=ptt_start, ptt_end=ptt_end, text=text.text,
            words=[w.model_copy(update={"word": w.word.lstrip()}) for w in timing.words],
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
