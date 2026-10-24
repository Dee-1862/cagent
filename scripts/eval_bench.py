"""Benchmark Unstep's speech path under radio conditions, with 95% intervals (R19, D20).

Extends scripts/eval_unstep.py, whose clean 40-line run was Cartesia TTS heard by Cartesia STT
with one voice and no noise (circular and small). Here:

  conditions   each line through our VHF voice channel (unstep.live.radio.radio_voice) at several
               noise levels: clean, radio (no added noise), radio-20, radio-10, radio-5 (SNR dB)
  voices       the room's three Cartesia voices (assets/clips/real/voices.json), round robin
  key terms    A/B on radio-10: ink-2 with and without our key terms
  readbacks    labelled wrong/right readbacks through radio-10, checked by our readback checker
  stepped on   instruction mixed with another line at a known offset, mixed like the live room;
               the cockpit's audio-only overlap detector is scored (recall at IoU >= 0.5, latency
               from the true overlap start to the first frame it is active, false alarms on clean
               radio-10 lines), and STT accuracy on the stepped-on audio
  ATCO2        optional real controller and pilot speech (Hugging Face Jzuluaga/atco2_corpus_1h),
               WER plus callsign and runway agreement with the reference transcript

Every accuracy has a Wilson 95% interval, WER a bootstrap 95% interval, latency p50 and p95.

    python scripts/eval_bench.py --live --n 200                  # Cartesia (needs keys), ~25 min
    python scripts/eval_bench.py --live --atco2 --atco2-licence-ok --atco2-limit 300
    python scripts/eval_bench.py --fake --n 30                   # plumbing check with fake speech
    ... --store                                                   # also index the summary in unstep-eval

--fake uses tone "speech" and an STT that echoes the reference with scripted errors: it tests the
harness only and its numbers mean nothing; its output is marked mode "fake" and is never stored.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
import time
import uuid
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from eval_unstep import RUNWAYS, build_items  # noqa: E402
from unstep import scenario  # noqa: E402
from unstep.cockpit.audio import SAMPLE_RATE  # noqa: E402
from unstep.cockpit.phraseology import callsign_digits, parse_instruction  # noqa: E402
from unstep.cockpit.readback import check_readback  # noqa: E402
from unstep.contracts import Slots  # noqa: E402
from unstep.evaluation import (bootstrap_wer, detect_overlap, iou, pct, proportion, stepped_on,  # noqa: E402
                               through_radio, wer)

OUT = ROOT / "data" / "eval"
EVAL_INDEX = "unstep-eval"
CONDITIONS = {"clean": None, "radio": "none", "radio-20": 20.0, "radio-10": 10.0, "radio-5": 5.0}
VOICE_ROLES = ("tower", "pilot", "heli")


# ------------------------------------------------------------ speech backends

class LiveSpeech:
    """Cartesia TTS with the room's voices, Cartesia ink-2 STT (manual finalize, audio sent fast)."""

    mode = "live"

    def __init__(self):
        from unstep.cockpit.stt import build_keyterms
        from unstep.live.room import station_voices

        self.voices = station_voices()
        self.terms = build_keyterms(callsigns=[s for _, s, *_ in scenario.FLEET], runways=RUNWAYS)

    async def say(self, text: str, role: str) -> np.ndarray:
        from unstep.cockpit.tts import CartesiaTTS
        from unstep.live.radio import to_mono16k

        tts = CartesiaTTS(voice_id=self.voices.get(role))
        try:
            speech = await tts.speak(text)
        finally:
            await tts.close()  # one socket per line; left open they pile up until Cartesia answers 429
        return to_mono16k(speech.pcm, speech.sample_rate)

    async def hear(self, pcm: np.ndarray, keyterms: bool, ref: str, condition: str) -> tuple[str, float]:
        from unstep.cockpit.stt import CartesiaManualSTT

        data = (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()
        async with CartesiaManualSTT(keyterms=self.terms if keyterms else ()) as stt:
            for i in range(0, len(data), SAMPLE_RATE // 5):
                await stt.send_audio(data[i:i + SAMPLE_RATE // 5])
            t = time.perf_counter()
            text = (await stt.finalize()).text
        return text, (time.perf_counter() - t) * 1000


class FakeSpeech:
    """Harness test only: tones for speech, and an STT that echoes the reference with scripted errors."""

    mode = "fake"
    DROP = {"clean": 0.0, "radio": 0.02, "radio-20": 0.05, "radio-10": 0.1, "radio-5": 0.25, "stepped": 0.4}

    async def say(self, text: str, role: str) -> np.ndarray:
        n = len(text.split())
        t = np.arange(int(SAMPLE_RATE * 0.25)) / SAMPLE_RATE
        word = (0.3 * np.sin(2 * np.pi * (180 if role == "tower" else 240) * t)).astype(np.float32)
        gap = np.zeros(int(SAMPLE_RATE * 0.05), dtype=np.float32)
        return np.concatenate([np.concatenate([word, gap]) for _ in range(max(1, n))])

    async def hear(self, pcm: np.ndarray, keyterms: bool, ref: str, condition: str) -> tuple[str, float]:
        rng = random.Random(int(hashlib.sha1(f"{ref}|{condition}|{keyterms}".encode()).hexdigest()[:8], 16))
        p = self.DROP.get(condition, 0.1) * (1.0 if keyterms else 1.5)
        return " ".join(w for w in ref.split() if rng.random() >= p), 100.0 + rng.random() * 400


# ------------------------------------------------------------ scoring

def score_lines(rows: list[dict]) -> dict:
    """Callsign, action and runway agreement with the said line, WER, finalize latency."""
    cs = act = rwy = rwy_n = 0
    pairs, final = [], []
    for r in rows:
        slots = parse_instruction(r["heard"])
        cs += bool(slots and slots.callsign) and callsign_digits(slots.callsign) == callsign_digits(r["callsign"])
        act += bool(slots) and slots.action == r["action"]
        if r["runway"]:
            rwy_n += 1
            rwy += bool(slots) and (slots.runway or "").upper() == r["runway"].upper()
        pairs.append(wer(r["said"], r["heard"]))
        if r.get("finalize_ms") is not None:
            final.append(r["finalize_ms"])
    n = len(rows)
    return {"n": n, "callsign": proportion(cs, n), "action": proportion(act, n), "runway": proportion(rwy, rwy_n),
            "wer": bootstrap_wer(pairs), "finalize_ms": {"p50": pct(final, 0.5), "p95": pct(final, 0.95)}}


def score_readbacks(rows: list[dict]) -> dict:
    tp = sum(r["flagged"] and r["labelled"] for r in rows)
    fp = sum(r["flagged"] and not r["labelled"] for r in rows)
    fn = sum(not r["flagged"] and r["labelled"] for r in rows)
    tn = len(rows) - tp - fp - fn
    return {"n": len(rows), "precision": proportion(tp, tp + fp), "recall": proportion(tp, tp + fn),
            "false_alarm_rate": proportion(fp, fp + tn), "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}}


def score_detection(hits: list[dict], clean_flags: list[bool]) -> dict:
    found = [h for h in hits if h["iou"] >= 0.5]
    lat = [h["latency_ms"] for h in hits if h["latency_ms"] is not None]
    return {"n": len(hits), "recall_iou_0_5": proportion(len(found), len(hits)),
            "any_detection": proportion(sum(h["detected"] for h in hits), len(hits)),
            "false_alarms_on_clean": proportion(sum(clean_flags), len(clean_flags)),
            "latency_ms": {"p50": pct(lat, 0.5), "p95": pct(lat, 0.95)}}


def first_active_ms(pcm: np.ndarray, t0: int) -> int | None:
    """End time of the first frame where the streaming detector is active (what the cockpit would act on)."""
    from unstep.cockpit.audio import ArraySource
    from unstep.cockpit.overlap import OverlapDetector

    det = OverlapDetector()
    for frame in ArraySource(pcm, t0=t0):
        det.process(frame)
        if det.active:
            return frame.end_ts
    return None


# ------------------------------------------------------------ the run

async def run_bench(speech, n: int, conditions: list[str], stepped: int, seed: int, ab: bool,
                    concurrency: int = 2) -> dict:
    items = build_items(n, seed)
    sem = asyncio.Semaphore(concurrency)
    rng = random.Random(seed)

    async def limited(make):
        """`make()` builds the call; a Cartesia 429 (rate limit) is retried with backoff, not fatal."""
        for attempt in range(6):
            async with sem:
                try:
                    return await make()
                except Exception as exc:
                    if "429" not in str(exc) or attempt == 5:
                        raise
            await asyncio.sleep(2 ** attempt)

    roles = [VOICE_ROLES[i % len(VOICE_ROLES)] for i in range(len(items))]
    said = await asyncio.gather(*(limited(lambda it=it, r=r: speech.say(it.instruction, r)) for it, r in zip(items, roles)))
    readback_audio = await asyncio.gather(*(limited(lambda it=it: speech.say(it.readback, "pilot")) for it in items))

    def channel(pcm, cond, k):
        level = CONDITIONS[cond]
        if level is None:
            return pcm
        return through_radio(pcm, None if level == "none" else level, seed=seed * 1000 + k)

    async def hear_all(cond, keyterms=True):
        async def one(k):
            text, ms = await limited(lambda: speech.hear(channel(said[k], cond, k), keyterms, items[k].instruction, cond))
            it = items[k]
            return {"id": it.id, "voice": roles[k], "said": it.instruction, "heard": text, "finalize_ms": round(ms, 1),
                    "callsign": it.spoken_callsign, "action": it.action, "runway": it.runway}
        return await asyncio.gather(*(one(k) for k in range(len(items))))

    result: dict = {"mode": speech.mode, "n": len(items), "seed": seed, "conditions": {}, "rows": {}}
    for cond in conditions:
        rows = await hear_all(cond)
        result["conditions"][cond] = score_lines(rows)
        result["conditions"][cond]["by_voice"] = {v: score_lines([r for r in rows if r["voice"] == v])["callsign"]
                                                  for v in VOICE_ROLES}
        result["rows"][cond] = rows
    if ab:
        rows = await hear_all("radio-10", keyterms=False)
        result["keyterms_ab"] = {"with": result["conditions"].get("radio-10") or score_lines(await hear_all("radio-10")),
                                 "without": score_lines(rows)}
        result["rows"]["radio-10-no-keyterms"] = rows

    # readbacks through radio-10
    async def readback(k):
        it = items[k]
        text, _ = await limited(lambda: speech.hear(channel(readback_audio[k], "radio-10", 50_000 + k), True, it.readback, "radio-10"))
        match, _, _ = check_readback(Slots(callsign=it.spoken_callsign, action=it.action, runway=it.runway), text)
        return {"id": it.id, "heard": text, "flagged": not match, "labelled": it.readback_wrong, "error": it.error}
    rb = await asyncio.gather(*(readback(k) for k in range(len(items))))
    result["readbacks"] = score_readbacks(rb)
    result["rows"]["readbacks"] = rb

    # stepped-on mixes: audio detector and STT on the damaged line
    hits, damaged = [], []
    for j in range(min(stepped, len(items))):
        k, other = j, rng.randrange(len(items))
        offset = rng.uniform(0.4, 1.6)
        t0 = 1_000_000 + j * 100_000
        pcm, window = stepped_on(said[k], readback_audio[other], offset, t0=t0)
        if window is None:
            continue
        found = detect_overlap(pcm, t0=t0)
        best = max((iou(window, w) for w in found), default=0.0)
        first = first_active_ms(pcm, t0)
        hits.append({"id": items[k].id, "window": window, "detected": bool(found), "iou": round(best, 3),
                     "latency_ms": (first - window[0]) if first is not None else None})
        text, ms = await limited(lambda: speech.hear(pcm, True, items[k].instruction, "stepped"))
        damaged.append({"id": items[k].id, "said": items[k].instruction, "heard": text, "finalize_ms": ms,
                        "callsign": items[k].spoken_callsign, "action": items[k].action, "runway": items[k].runway})
    clean_flags = [bool(detect_overlap(channel(said[k], "radio-10", k))) for k in range(min(len(items), max(stepped, 1) * 2))]
    result["detection_audio_only"] = score_detection(hits, clean_flags)
    result["stepped_on_stt"] = score_lines(damaged)
    result["rows"]["stepped"] = hits
    return result


# ------------------------------------------------------------ ATCO2 (real speech)

def load_atco2(split: str, limit: int, licence_ok: bool):
    """Yields (reference text, 16 kHz float pcm). Needs the `datasets` package and Hugging Face access."""
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SystemExit("ATCO2 needs: pip install datasets soundfile") from exc
    ds = load_dataset("Jzuluaga/atco2_corpus_1h", split=split)
    licence = getattr(ds.info, "license", None) or "not stated in the dataset info"
    print(f"ATCO2 licence (from the dataset card): {licence}")
    if not licence_ok:
        raise SystemExit("Read the dataset card's licence, then rerun with --atco2-licence-ok. Results stay local.")
    cols = ds.column_names
    audio_col = next(c for c in cols if c in ("audio", "speech"))
    text_col = next(c for c in cols if c in ("text", "transcription", "sentence", "transcript"))
    from unstep.live.radio import to_mono16k

    for k, row in enumerate(ds):
        if k >= limit:
            break
        audio = row[audio_col]
        yield str(row[text_col]), to_mono16k(np.asarray(audio["array"], dtype=np.float32), int(audio["sampling_rate"]))


async def run_atco2(speech, split: str, limit: int, licence_ok: bool) -> dict:
    rows = []
    for ref, pcm in load_atco2(split, limit, licence_ok):
        text, ms = await speech.hear(pcm, True, ref, "atco2")
        r_slots, h_slots = parse_instruction(ref), parse_instruction(text)
        rows.append({"ref": ref, "heard": text, "finalize_ms": ms,
                     "callsign_ok": None if not (r_slots and r_slots.callsign) else
                     bool(h_slots and callsign_digits(h_slots.callsign) == callsign_digits(r_slots.callsign)),
                     "runway_ok": None if not (r_slots and r_slots.runway) else
                     bool(h_slots and (h_slots.runway or "") == r_slots.runway)})
    cs = [r["callsign_ok"] for r in rows if r["callsign_ok"] is not None]
    rw = [r["runway_ok"] for r in rows if r["runway_ok"] is not None]
    return {"n": len(rows), "wer": bootstrap_wer([wer(r["ref"], r["heard"]) for r in rows]),
            "callsign": proportion(sum(cs), len(cs)), "runway": proportion(sum(rw), len(rw)),
            "finalize_ms": {"p50": pct([r["finalize_ms"] for r in rows], 0.5), "p95": pct([r["finalize_ms"] for r in rows], 0.95)},
            "rows": rows[:50]}


# ------------------------------------------------------------ output

def summary(result: dict) -> dict:
    """The run without per-line rows: what gets printed, stored and quoted."""
    return {k: v for k, v in result.items() if k != "rows"} | (
        {"atco2": {k: v for k, v in result["atco2"].items() if k != "rows"}} if "atco2" in result else {})


def store(doc: dict, transport=None) -> str | None:
    """Index the run in unstep-eval (headline numbers plus the summary). Fake runs are never stored."""
    from unstep.evaluation import store_eval

    return store_eval(doc, transport=transport)


def fmt(p: dict | None) -> str:
    if not p or p.get("value") is None:
        return "-"
    lo, hi = p["ci95"]
    return f"{p['value']:.3f} [{lo:.3f}, {hi:.3f}]"


def print_table(s: dict) -> None:
    if s.get("mode") == "fake":
        print("FAKE SPEECH: harness check only, these numbers mean nothing")
    print(f"{'condition':22} {'n':>4}  {'callsign':24} {'runway':24} {'WER':24} finalize p50/p95")
    for name, c in s.get("conditions", {}).items():
        print(f"{name:22} {c['n']:>4}  {fmt(c['callsign']):24} {fmt(c['runway']):24} {fmt(c['wer']):24} "
              f"{c['finalize_ms']['p50']}/{c['finalize_ms']['p95']} ms")
    if "keyterms_ab" in s:
        for side in ("with", "without"):
            c = s["keyterms_ab"][side]
            print(f"{'radio-10 ' + side + ' terms':22} {c['n']:>4}  {fmt(c['callsign']):24} {fmt(c['runway']):24} {fmt(c['wer']):24}")
    if "readbacks" in s:
        rb = s["readbacks"]
        print(f"readback check (radio-10): precision {fmt(rb['precision'])}, recall {fmt(rb['recall'])}, "
              f"false alarms {fmt(rb['false_alarm_rate'])}")
    if "detection_audio_only" in s:
        d = s["detection_audio_only"]
        print(f"audio-only overlap detector: recall {fmt(d['recall_iou_0_5'])}, false alarms on clean "
              f"{fmt(d['false_alarms_on_clean'])}, latency p50/p95 {d['latency_ms']['p50']}/{d['latency_ms']['p95']} ms")
    if "atco2" in s:
        a = s["atco2"]
        print(f"ATCO2 n={a['n']}: WER {fmt(a['wer'])}, callsign {fmt(a['callsign'])}, runway {fmt(a['runway'])}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--fake", action="store_true")
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--conditions", default=",".join(CONDITIONS))
    p.add_argument("--stepped", type=int, default=60, help="stepped-on mixes for the detector and STT")
    p.add_argument("--no-ab", action="store_true", help="skip the key terms A/B")
    p.add_argument("--atco2", action="store_true")
    p.add_argument("--atco2-split", default="test")
    p.add_argument("--atco2-limit", type=int, default=300)
    p.add_argument("--atco2-licence-ok", action="store_true")
    p.add_argument("--store", action="store_true", help="index the summary in unstep-eval (live runs only)")
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args(argv)
    speech = LiveSpeech() if args.live else FakeSpeech()
    conditions = [c for c in args.conditions.split(",") if c in CONDITIONS]
    result = asyncio.run(run_bench(speech, args.n, conditions, args.stepped, args.seed, not args.no_ab))
    if args.atco2:
        result["atco2"] = asyncio.run(run_atco2(speech, args.atco2_split, args.atco2_limit, args.atco2_licence_ok))
    result["run_id"] = f"eval-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    result["created"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    s = summary(result)
    print_table(s)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{result['run_id']}.json"
    path.write_text(json.dumps(result, indent=1, default=str))
    print(f"wrote {path}")
    if args.store:
        doc_id = store(s)
        print(f"stored in {EVAL_INDEX}: {doc_id}" if doc_id else "not stored (fake run, or Elastic not configured)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
