"""Reproduce and measure the Cartesia STT behaviours we hit (P7c, docs/09-cartesia-feedback.md).

Each experiment answers one question with numbers, so feedback to Cartesia is a
question with data, not a claim:

  manual_pacing   Does /stt/websocket (manual finalize) need real-time pacing, like the turns endpoint?
  turns_pacing    How often is turn.end empty when audio is sent fast vs paced?
  words_by_model  Which model returns word timestamps (ink-2 vs ink-whisper)?
  handshake       How long does opening an STT socket take, and how often does it fail?
  finalize        How much does finalize latency vary for the same clip?
  hedged          Does racing a second, already open socket cut the slow finalizes?

    python scripts/cartesia_repro.py                 # all experiments, 10 runs each
    python scripts/cartesia_repro.py --runs 25 --only finalize hedged

Needs CARTESIA_API_KEY. Writes data/cartesia-repro/<time>.json and prints a table.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run without PYTHONPATH=.

from unstep.cockpit.audio import read_wav
from unstep.cockpit.stt import CartesiaManualSTT, CartesiaTurnSTT, build_keyterms, send_paced
from unstep.config import ROOT, cartesia_stt_timestamp_model, env
from unstep.ground.percolate import normalize

CLIP = ROOT / "assets" / "clips" / "real" / "correct_readback.wav"
EXPECT = "hold short runway 33"  # what a correct transcript of the clip must contain, normalized
TERMS = build_keyterms(callsigns=["Cessna 1-2-3", "N123AB"], runways=["33"])
OUT = ROOT / "data" / "cartesia-repro"


def pcm16(path: Path) -> bytes:
    return (np.clip(read_wav(path), -1, 1) * 32767).astype("<i2").tobytes()


async def send_fast(stt, pcm: bytes, chunk: int = 3200) -> None:
    for i in range(0, len(pcm), chunk):
        await stt.send_audio(pcm[i:i + chunk])


def correct(text: str) -> bool:
    return EXPECT in normalize(text)


def ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


def summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    v = sorted(values)
    return {"n": len(v), "min": v[0], "p50": statistics.median(v), "p95": v[min(len(v) - 1, int(0.95 * len(v)))],
            "max": v[-1]}


# ---------------------------------------------------------------- experiments


async def manual_once(pcm: bytes, paced: bool) -> dict:
    t0 = time.perf_counter()
    async with CartesiaManualSTT(keyterms=TERMS) as stt:
        (await send_paced(stt, pcm)) if paced else (await send_fast(stt, pcm))
        sent = time.perf_counter()
        result = await stt.finalize()
    return {"text": result.text, "empty": not result.text.strip(), "correct": correct(result.text),
            "finalize_ms": round((time.perf_counter() - sent) * 1000, 1), "total_ms": ms(t0)}


async def manual_pacing(pcm: bytes, runs: int) -> dict:
    out = {}
    for mode in ("fast", "paced"):
        rows = [await manual_once(pcm, mode == "paced") for _ in range(runs)]
        out[mode] = {"empty": sum(r["empty"] for r in rows), "correct": sum(r["correct"] for r in rows),
                     "finalize_ms": summary([r["finalize_ms"] for r in rows]),
                     "total_ms": summary([r["total_ms"] for r in rows]), "examples": [r["text"] for r in rows[:3]]}
    return out


async def turns_once(pcm: bytes, paced: bool) -> dict:
    async with CartesiaTurnSTT(keyterms=TERMS) as stt:
        async def feed():
            if paced:
                await send_paced(stt, pcm, trailing_silence_s=1.5)
            else:
                await send_fast(stt, pcm + b"\x00\x00" * 24000)

        feeder = asyncio.create_task(feed())
        text = None
        try:
            async def first_end():
                async for ev in stt.events():
                    if ev.type == "turn.end":
                        return ev.transcript
            text = await asyncio.wait_for(first_end(), 15)
        except asyncio.TimeoutError:
            text = None
        feeder.cancel()
    return {"text": text, "empty": not (text or "").strip(), "correct": correct(text or "")}


async def turns_pacing(pcm: bytes, runs: int) -> dict:
    out = {}
    for mode in ("fast", "paced"):
        rows = [await turns_once(pcm, mode == "paced") for _ in range(runs)]
        out[mode] = {"runs": runs, "empty": sum(r["empty"] for r in rows), "correct": sum(r["correct"] for r in rows),
                     "examples": [r["text"] for r in rows[:3]]}
    return out


async def words_by_model(pcm: bytes, runs: int) -> dict:
    out = {}
    for model in ("ink-2", cartesia_stt_timestamp_model()):
        async with CartesiaManualSTT(model=model, timestamp_granularities=["word"]) as stt:
            await send_paced(stt, pcm)
            r = await stt.finalize()
        out[model] = {"text": r.text, "words": len(r.words)}
    return out


async def handshake(pcm: bytes, runs: int) -> dict:
    times, failures = [], 0
    for _ in range(runs):
        t0 = time.perf_counter()
        try:
            async with CartesiaManualSTT(keyterms=TERMS):
                times.append(ms(t0))
        except Exception:
            failures += 1
    return {"open_ms": summary(times), "failures": failures, "runs": runs}


async def finalize(pcm: bytes, runs: int) -> dict:
    rows = [await manual_once(pcm, paced=True) for _ in range(runs)]
    return {"finalize_ms": summary([r["finalize_ms"] for r in rows]), "empty": sum(r["empty"] for r in rows),
            "slow_over_800ms": sum(r["finalize_ms"] > 800 for r in rows), "runs": runs}


async def hedged_once(pcm: bytes, hedge_after_ms: float) -> dict:
    """Paced stream on socket A (as in the room). If finalize is slow, send the clip fast on
    an already open socket B and take whichever finishes first."""
    async with CartesiaManualSTT(keyterms=TERMS) as a, CartesiaManualSTT(keyterms=TERMS) as b:
        await send_paced(a, pcm)
        t0 = time.perf_counter()
        primary = asyncio.create_task(a.finalize())
        done, _ = await asyncio.wait({primary}, timeout=hedge_after_ms / 1000)
        if done:
            r, used = primary.result(), "primary"
        else:
            async def backup():
                await send_fast(b, pcm)
                return await b.finalize()

            second = asyncio.create_task(backup())
            done, pending = await asyncio.wait({primary, second}, return_when=asyncio.FIRST_COMPLETED)
            winner = done.pop()
            r, used = winner.result(), "primary" if winner is primary else "hedge"
            for p in pending:
                p.cancel()
        return {"finalize_ms": ms(t0), "used": used, "correct": correct(r.text), "empty": not r.text.strip()}


async def hedged(pcm: bytes, runs: int, hedge_after_ms: float = 800) -> dict:
    rows = [await hedged_once(pcm, hedge_after_ms) for _ in range(runs)]
    return {"hedge_after_ms": hedge_after_ms, "finalize_ms": summary([r["finalize_ms"] for r in rows]),
            "hedge_won": sum(r["used"] == "hedge" for r in rows), "correct": sum(r["correct"] for r in rows),
            "runs": runs}


EXPERIMENTS = {"manual_pacing": manual_pacing, "turns_pacing": turns_pacing, "words_by_model": words_by_model,
               "handshake": handshake, "finalize": finalize, "hedged": hedged}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--only", nargs="*", choices=list(EXPERIMENTS))
    parser.add_argument("--clip", type=Path, default=CLIP)
    args = parser.parse_args()
    if not env("CARTESIA_API_KEY"):
        print("CARTESIA_API_KEY not set: skipping")
        return
    pcm = pcm16(args.clip)
    report = {"clip": str(args.clip.relative_to(ROOT)), "clip_s": round(len(pcm) / 32000, 2), "runs": args.runs,
              "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "results": {}}
    for name in args.only or EXPERIMENTS:
        print(f"running {name} ...", flush=True)
        try:
            report["results"][name] = await EXPERIMENTS[name](pcm, args.runs)
        except Exception as e:  # keep going: one failing experiment is itself a finding
            report["results"][name] = {"error": f"{type(e).__name__}: {e}"}
        print(json.dumps(report["results"][name], indent=1))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=1))
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
