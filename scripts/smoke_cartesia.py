"""Live smoke test for our Cartesia clients (CartesiaTTS, CartesiaManualSTT, CartesiaTurnSTT).

(a) TTS one advisory sentence: time to first audio, total time, saves a 16 kHz WAV.
(b) Round trip: that WAV through the manual STT endpoint with our keyterms;
    prints transcript and word timestamps.
(c) The same audio through the turns endpoint; prints turn events.

Needs CARTESIA_API_KEY in .env. CARTESIA_VOICE_ID is optional here: if it is
missing, the first English voice from GET /voices is used and printed.
Without a key it prints "skipped: ..." and exits 0.

Run from the repo root: python scripts/smoke_cartesia.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from unstep.config import cartesia_version  # noqa: E402

SR = 16_000
CHUNK_BYTES = SR * 2 // 10  # 100 ms of pcm_s16le, as the STT docs recommend
OUT = ROOT / "assets" / "clips" / "real" / "smoke_advisory.wav"
ADVISORY = "Transmission blocked. Likely hold short Runway 33. Awaiting controller."
REST_VERSION = cartesia_version()


def first_voice(api_key: str, gender: str | None = None, skip: int = 0) -> str:
    """Pick an English voice from GET /voices (REST uses a Bearer token, not X-API-Key)."""
    q = "?limit=100&language=en" + (f"&gender={gender}" if gender else "")
    req = urllib.request.Request(
        f"https://api.cartesia.ai/voices{q}",
        headers={"Authorization": f"Bearer {api_key}", "Cartesia-Version": REST_VERSION},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        voices = json.load(r)["data"]
    return voices[skip]["id"]


def keyterms() -> list[str]:
    from unstep.cockpit.stt import build_keyterms

    return build_keyterms(callsigns=["Cessna 1-2-3", "N123AB"], runways=["33", "28L"],
                          taxiways=["Alpha", "Bravo", "Charlie"])


async def tts_step(voice_id: str) -> np.ndarray:
    from unstep.cockpit.audio import write_wav
    from unstep.cockpit.tts import CartesiaTTS, advisory, pcm_bytes_to_array

    tts = CartesiaTTS(voice_id=voice_id, sample_rate=SR)
    text = advisory(ADVISORY)
    print(f"[tts] model={tts.model_id} dict={'set' if tts.pronunciation_dict_id else 'none'}")
    print(f"[tts] text: {text!r}")
    started = time.perf_counter()
    try:
        res = await tts.speak(text)
    finally:
        await tts.close()
    total_ms = (time.perf_counter() - started) * 1000
    pcm = pcm_bytes_to_array(res.pcm).astype(np.float32) / 32768.0
    first = f"{res.first_audio_ms:.0f} ms" if res.first_audio_ms is not None else "n/a"
    print(f"[tts] first audio {first}, total {total_ms:.0f} ms, audio {len(pcm) / SR:.2f} s")
    print(f"[tts] word timestamps: {len(res.words)} " + " ".join(f"{w}@{s:.2f}" for w, s, _ in res.words[:12]))
    write_wav(OUT, pcm, SR)
    print(f"[tts] wrote {OUT.relative_to(ROOT)}")
    if not len(pcm):
        raise RuntimeError("TTS returned no audio")
    return pcm


def to_bytes(pcm: np.ndarray) -> bytes:
    return (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()


async def manual_step(pcm: np.ndarray) -> None:
    from unstep.cockpit.stt import CartesiaManualSTT

    data = to_bytes(pcm)
    started = time.perf_counter()
    async with CartesiaManualSTT(sample_rate=SR, keyterms=keyterms()) as stt:
        for i in range(0, len(data), CHUNK_BYTES):
            await stt.send_audio(data[i:i + CHUNK_BYTES])
        sent = time.perf_counter()
        tr = await stt.finalize()
    done = time.perf_counter()
    print(f"[stt manual] finalize -> flush_done {1000 * (done - sent):.0f} ms (total {1000 * (done - started):.0f} ms)")
    print(f"[stt manual] transcript: {tr.text!r}")
    for w in tr.words:
        print(f"    {w.word:<14} {w.start:6.2f} {w.end:6.2f}")
    if not tr.words:
        print("[stt manual] WARNING: no word timestamps returned")


async def turns_step(pcm: np.ndarray, timeout_s: float = 20.0) -> None:
    from unstep.cockpit.stt import CartesiaTurnSTT

    # Trailing silence so turn_end_timeout_ms (1500) can fire.
    data = to_bytes(np.concatenate([pcm, np.zeros(int(2.5 * SR), dtype=np.float32)]))
    started = time.perf_counter()
    async with CartesiaTurnSTT(sample_rate=SR, keyterms=keyterms()) as stt:
        async def sender():
            for i in range(0, len(data), CHUNK_BYTES):
                await stt.send_audio(data[i:i + CHUNK_BYTES])
                await asyncio.sleep(0.1)  # real-time pacing: turn detection is time based

        send_task = asyncio.create_task(sender())
        try:
            async def reader():
                async for ev in stt.events():
                    t = time.perf_counter() - started
                    print(f"[stt turns] {t:5.2f}s {ev.type:<15} {ev.transcript!r}")
                    if ev.type == "error":
                        raise RuntimeError(f"turns error: {ev.raw.get('title')}: {ev.raw.get('message')}")
                    if ev.type == "turn.end":
                        return
            await asyncio.wait_for(reader(), timeout=timeout_s)
        except asyncio.TimeoutError:
            print(f"[stt turns] WARNING: no turn.end within {timeout_s:.0f} s")
        finally:
            send_task.cancel()


async def main() -> int:
    api_key = os.getenv("CARTESIA_API_KEY")
    if not api_key:
        print("skipped: CARTESIA_API_KEY not set")
        return 0
    voice_id = os.getenv("CARTESIA_VOICE_ID")
    if not voice_id:
        voice_id = first_voice(api_key)
        print(f"[tts] CARTESIA_VOICE_ID not set, using voice {voice_id}")
    pcm = await tts_step(voice_id)
    await manual_step(pcm)
    await turns_step(pcm)
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
