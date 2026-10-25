"""Summarise the Cartesia evidence for the README table into docs/evidence/cartesia-<date>.json.

The three measurements are made by the existing scripts, which write their raw results under data/ (not in git):

    python scripts/eval_bench.py --live --n 200 --conditions clean,radio-10 --stepped 0   # key terms, 200 lines (uses credits)
    python scripts/cartesia_repro.py --runs 30 --only manual_pacing                        # streaming against burst finalize
    python scripts/cartesia_live_check.py --only tts caption --tts-runs 30 --runs 5        # Sonic first audio, caption timing
    python scripts/evidence_cartesia.py                                                    # this: copy the raw files, write the summary

The raw files are copied next to the summary so every number can be traced. Nothing here calls Cartesia.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "evidence"


def newest(folder: str, pattern: str = "*.json") -> Path:
    files = sorted((ROOT / "data" / folder).glob(pattern))
    if not files:
        raise SystemExit(f"no results in data/{folder}: run the measurement first (see this file's docstring)")
    return files[-1]


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)


def main(day: str) -> dict:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    bench_path = EVIDENCE / f"cartesia-bench-{day}.json"
    if not bench_path.exists():
        shutil.copy(newest("eval"), bench_path)
    bench = json.loads(bench_path.read_text(encoding="utf-8"))
    if bench.get("mode") != "live":
        raise SystemExit("the benchmark file is not a live run")
    repro_path, live_path = newest("cartesia-repro"), newest("cartesia-live")
    shutil.copy(repro_path, EVIDENCE / f"cartesia-repro-{day}.json")
    shutil.copy(live_path, EVIDENCE / f"cartesia-live-check-{day}.json")
    repro = json.loads(repro_path.read_text(encoding="utf-8"))["results"]["manual_pacing"]
    live = {c["name"]: c for c in json.loads(live_path.read_text(encoding="utf-8"))["checks"]}

    ab = bench["keyterms_ab"]
    keyterms = {"n": ab["with"]["n"], "condition": "radio-10 (10 dB signal to noise), three voices, synthetic speech", "seed": bench["seed"],
                "callsign": {"without": ab["without"]["callsign"]["value"], "with": ab["with"]["callsign"]["value"],
                             "ci95_without": ab["without"]["callsign"]["ci95"], "ci95_with": ab["with"]["callsign"]["ci95"],
                             "n": ab["with"]["callsign"]["n"]},
                "runway": {"without": ab["without"]["runway"]["value"], "with": ab["with"]["runway"]["value"],
                           "ci95_without": ab["without"]["runway"]["ci95"], "ci95_with": ab["with"]["runway"]["ci95"],
                           "n": ab["with"]["runway"]["n"]},
                "wer": {"without": ab["without"]["wer"]["value"], "with": ab["with"]["wer"]["value"]},
                "callsign_by_voice_with_terms": {v: d["value"] for v, d in ab["with"]["by_voice"].items()}}

    first_audio = live["tts"]["data"]["first_audio_ms"]
    caption = live["caption"]["data"]["manual"]["runs"]
    last_after = [r["last_update_after_end_ms"] for r in caption]
    result = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "keyterms": keyterms,
        "stt_streaming_finalize_ms": {"n": repro["paced"]["finalize_ms"]["n"], "p50": repro["paced"]["finalize_ms"]["p50"],
                                      "p95": repro["paced"]["finalize_ms"]["p95"], "correct": repro["paced"]["correct"]},
        "stt_burst_finalize_ms": {"n": repro["fast"]["finalize_ms"]["n"], "p50": repro["fast"]["finalize_ms"]["p50"],
                                  "p95": repro["fast"]["finalize_ms"]["p95"]},
        "tts_first_audio_ms": {"n": len(first_audio), "p50": pct(first_audio, 0.5), "p95": pct(first_audio, 0.95),
                               "min": round(min(first_audio), 1), "first_request_on_the_socket": round(first_audio[0], 1)},
        "captions": {"runs": len(caption), "last_update_after_release_ms": {"p50": round(statistics.median(last_after)), "max": max(last_after)},
                     "median_gap_between_updates_ms": round(statistics.median(r["gap_median_ms"] for r in caption)),
                     "first_text_ms": round(statistics.median(r["first_text_ms"] for r in caption))},
        "files": [bench_path.name, f"cartesia-repro-{day}.json", f"cartesia-live-check-{day}.json"],
    }
    c = result["captions"]
    result["captions_text"] = (f"final caption {c['last_update_after_release_ms']['p50']} ms after release (median of {c['runs']} runs, worst "
                               f"{c['last_update_after_release_ms']['max']} ms); while speaking, a caption update about every "
                               f"{c['median_gap_between_updates_ms'] / 1000:.1f} s")
    result["note"] = ("Streaming the audio while the key is held finalizes in "
                      f"{result['stt_streaming_finalize_ms']['p50']:g} ms (median), against {result['stt_burst_finalize_ms']['p50']:g} ms when the "
                      "whole clip is sent at once; that is why the room streams. Of the three voices the pilot's is the hardest "
                      f"(callsign {keyterms['callsign_by_voice_with_terms']['pilot'] * 100:.1f}% with key terms).")
    out = EVIDENCE / f"cartesia-{day}.json"
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--day", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()
    summary = main(args.day)
    print(json.dumps(summary, indent=1))
    sys.exit(0)
