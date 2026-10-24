"""Measure how often Cartesia sends partial text while someone is still talking.

The live captions can only be as fast as Cartesia's updates. This streams one clip at real-time
pace to each speech endpoint and records when text comes back, so we know which endpoint gives
the smoothest captions and what the floor is.

    python scripts/caption_probe.py                       # both endpoints, 3 runs each
    python scripts/caption_probe.py --runs 5 --clip assets/clips/real/helicopter_call.wav
    python scripts/caption_probe.py --only turns

  manual  /stt/websocket, ink-2: the endpoint the room uses for the final text; partial text comes as
          final-text deltas (Rishit's R26 check: about every 0.5 to 0.7 s, can split a word)
  turns   /stt/turns/websocket, ink-2: turn.update carries the turn's text so far; how often is unmeasured

For each endpoint it prints: updates while the clip was still playing, time to the first text,
the gap between updates (median and worst), words added per update, and how long after the clip
ended the last update came. Results are also written to data/caption-probe/<time>.json.
Needs CARTESIA_API_KEY and network access to Cartesia. Run it where Cartesia is reachable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from unstep.cockpit.audio import read_wav  # noqa: E402
from unstep.cockpit.stt import CartesiaManualSTT, CartesiaTurnSTT, build_keyterms, send_paced  # noqa: E402
from unstep.config import env  # noqa: E402

CLIP = ROOT / "assets" / "clips" / "real" / "helicopter_call.wav"
OUT = ROOT / "data" / "caption-probe"
CHUNK_MS = 50
TERMS = build_keyterms(callsigns=["Cessna 1-2-3", "Helicopter 4-5-6"], runways=["33"])


def summarize(updates: list[tuple[float, int]], audio_end_s: float) -> dict:
    """updates: (seconds since the first audio was sent, words in the text so far), in arrival order."""
    if not updates:
        return {"updates": 0}
    times = [t for t, _ in updates]
    gaps = [b - a for a, b in zip(times, times[1:])]
    added = [b - a for (_, a), (_, b) in zip([(0.0, 0)] + updates[:-1], updates) if b > a]
    during = [t for t in times if t <= audio_end_s]
    return {
        "updates": len(updates),
        "updates_while_speaking": len(during),
        "first_text_ms": round(times[0] * 1000),
        "gap_median_ms": round(statistics.median(gaps) * 1000) if gaps else None,
        "gap_worst_ms": round(max(gaps) * 1000) if gaps else None,
        "words_per_update_median": statistics.median(added) if added else None,
        "last_update_after_end_ms": round((times[-1] - audio_end_s) * 1000),
    }


def pcm16(path: Path) -> bytes:
    return (np.clip(read_wav(path), -1, 1) * 32767).astype("<i2").tobytes()


async def probe_manual(pcm: bytes) -> list[tuple[float, int]]:
    updates: list[tuple[float, int]] = []
    started = time.perf_counter()

    def on_text(delta: str, so_far: str) -> None:
        updates.append((time.perf_counter() - started, len(so_far.split())))

    async with CartesiaManualSTT(keyterms=TERMS, on_text=on_text) as stt:
        started = time.perf_counter()
        await send_paced(stt, pcm, chunk_ms=CHUNK_MS)
        await stt.finalize()
    return updates


async def probe_turns(pcm: bytes) -> list[tuple[float, int]]:
    updates: list[tuple[float, int]] = []
    async with CartesiaTurnSTT(keyterms=TERMS) as stt:
        started = time.perf_counter()

        async def read() -> None:
            committed = ""
            async for ev in stt.events():
                text = (ev.transcript or "").strip()
                if ev.type in ("turn.update", "turn.eager_end") and text:
                    updates.append((time.perf_counter() - started, len((committed + " " + text).split())))
                elif ev.type == "turn.end":
                    if text:
                        committed = (committed + " " + text).strip()
                        updates.append((time.perf_counter() - started, len(committed.split())))
                    return

        reader = asyncio.create_task(read())
        await send_paced(stt, pcm, chunk_ms=CHUNK_MS, trailing_silence_s=1.5)
        try:
            await asyncio.wait_for(reader, 6)
        except asyncio.TimeoutError:
            reader.cancel()
    return updates


PROBES = {"manual": probe_manual, "turns": probe_turns}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--clip", type=Path, default=CLIP)
    parser.add_argument("--only", choices=list(PROBES))
    args = parser.parse_args()
    if not env("CARTESIA_API_KEY"):
        print("CARTESIA_API_KEY not set: skipping")
        return
    pcm = pcm16(args.clip)
    audio_s = len(pcm) / 32000
    report = {"clip": str(args.clip), "clip_s": round(audio_s, 2), "chunk_ms": CHUNK_MS,
              "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "endpoints": {}}
    for name in [args.only] if args.only else list(PROBES):
        runs = []
        for _ in range(args.runs):
            try:
                runs.append(summarize(await PROBES[name](pcm), audio_s))
            except Exception as e:  # a failing endpoint is itself a finding
                runs.append({"error": f"{type(e).__name__}: {e}"})
        report["endpoints"][name] = runs
        print(f"\n{name} ({audio_s:.1f} s clip, {CHUNK_MS} ms chunks, real-time pace)")
        for r in runs:
            print("  ", json.dumps(r))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=1))
    print(f"\nwrote {path.relative_to(ROOT)}")
    print("Reading it: more updates while speaking and a smaller median gap mean smoother live captions.")


if __name__ == "__main__":
    asyncio.run(main())
