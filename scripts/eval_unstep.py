"""Evaluate Unstep's speech and readback checks on our own data (agreed in R19).

Data: a synthetic set built from FAA-style phraseology with the fleet's callsigns, and
optionally our live sessions (data/events.jsonl or an export of the Elastic events index).
No public ATC corpus is bundled (licences).

    python scripts/eval_unstep.py --dry-run            # text only: the checkers on the exact words, no API calls
    python scripts/eval_unstep.py --live --n 40        # Cartesia TTS -> Cartesia STT (ink-2, key terms) -> checks
    python scripts/eval_unstep.py --sessions data/events.jsonl   # latency and readback outcomes from live sessions

Metrics: callsign accuracy, runway accuracy and action accuracy of the parsed transcript,
readback-error precision and recall (positive = "this readback is wrong"), STT finalize
latency p50 and p95 (live). Writes data/eval/<time>.json and prints a table. --live needs
CARTESIA_API_KEY and CARTESIA_VOICE_ID; run it where Cartesia is reachable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep import scenario  # noqa: E402
from unstep.cockpit.phraseology import callsign_digits, callsigns_match, parse_instruction  # noqa: E402
from unstep.cockpit.readback import check_readback  # noqa: E402
from unstep.contracts import Slots  # noqa: E402

OUT = ROOT / "data" / "eval"
RUNWAYS = ["33", "28L", "15", "4R", "9"]
DIGIT_WORDS = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
               "7": "seven", "8": "eight", "9": "niner"}
SIDES = {"L": "left", "R": "right", "C": "center"}
TEMPLATES = [  # (action, instruction template, needs runway)
    ("hold short", "{cs}, hold short Runway {rwy}", True),
    ("hold position", "{cs}, hold position", False),
    ("go around", "{cs}, go around", False),
    ("cleared for takeoff", "{cs}, Runway {rwy}, cleared for takeoff", True),
    ("line up and wait", "{cs}, Runway {rwy}, line up and wait", True),
    ("cleared to land", "{cs}, Runway {rwy}, cleared to land", True),
]
ERRORS = ("runway_digit", "callsign_digit", "action", "missing_callsign")


def say_runway(rwy: str) -> str:
    digits = " ".join(DIGIT_WORDS[d] for d in rwy if d.isdigit())
    side = next((SIDES[c] for c in rwy if c in SIDES), "")
    return f"{digits} {side}".strip()


@dataclass
class Item:
    id: str
    callsign: str
    spoken_callsign: str
    action: str
    runway: str | None
    instruction: str
    readback: str
    readback_wrong: bool
    error: str | None


def _other_runway(rng: random.Random, rwy: str) -> str:
    return rng.choice([r for r in RUNWAYS if r != rwy])


def build_items(n: int, seed: int = 7, error_rate: float = 0.3) -> list[Item]:
    """n instruction / readback pairs; about error_rate of readbacks carry one labelled error."""
    rng = random.Random(seed)
    items = []
    for i in range(n):
        callsign, spoken, *_ = rng.choice(scenario.FLEET)
        action, template, needs_rwy = rng.choice(TEMPLATES)
        rwy = rng.choice(RUNWAYS) if needs_rwy else None
        instruction = template.format(cs=spoken, rwy=say_runway(rwy) if rwy else "")
        wrong = rng.random() < error_rate
        error = rng.choice([e for e in ERRORS if needs_rwy or e != "runway_digit"]) if wrong else None
        rb_cs, rb_rwy, rb_action = spoken, rwy, action
        if error == "runway_digit":
            rb_rwy = _other_runway(rng, rwy)
        elif error == "callsign_digit":
            others = [s for c, s, *_ in scenario.FLEET if c != callsign]
            rb_cs = rng.choice(others)
        elif error == "action":
            rb_action = rng.choice([a for a, _, nr in TEMPLATES if a != action and (nr == needs_rwy)])
        readback_template = next(t for a, t, _ in TEMPLATES if a == rb_action)
        readback = readback_template.format(cs=rb_cs, rwy=say_runway(rb_rwy) if rb_rwy else "")
        if error == "missing_callsign":
            readback = readback.split(", ", 1)[1]
        items.append(Item(f"syn-{i:04d}", callsign, spoken, action, rwy, instruction, readback, wrong, error))
    return items


def score(items: list[Item], heard_instructions: list[str], heard_readbacks: list[str],
          audio_ms: list[tuple[float, float]] | None = None) -> dict:
    """Accuracy and readback precision/recall, plus one row per line so misses can be read."""
    cs_ok = rwy_ok = act_ok = rwy_n = 0
    tp = fp = fn = tn = 0
    rows = []
    for k, (item, heard, rb) in enumerate(zip(items, heard_instructions, heard_readbacks)):
        slots = parse_instruction(heard)
        c_ok = a_ok = False
        r_ok = None
        if slots is not None:
            c_ok = bool(slots.callsign) and callsign_digits(slots.callsign) == callsign_digits(item.spoken_callsign)
            a_ok = slots.action == item.action
            if item.runway:
                r_ok = (slots.runway or "").upper() == item.runway.upper()
        elif item.runway:
            r_ok = False
        cs_ok += c_ok
        act_ok += a_ok
        if r_ok is not None:
            rwy_n += 1
            rwy_ok += r_ok
        directive = Slots(callsign=item.spoken_callsign, action=item.action, runway=item.runway)
        match, _, reason = check_readback(directive, rb)
        flagged = not match
        row = {"id": item.id, "text": item.instruction, "heard": heard, "callsign_ok": c_ok, "action_ok": a_ok,
               "runway_ok": r_ok, "readback": item.readback, "heard_readback": rb, "flagged": flagged,
               "labelled": item.readback_wrong, "error": item.error, "reason": reason or None}
        if audio_ms is not None and k < len(audio_ms):
            row["audio_ms"], row["readback_audio_ms"] = audio_ms[k]
        rows.append(row)
        if flagged and item.readback_wrong:
            tp += 1
        elif flagged:
            fp += 1
        elif item.readback_wrong:
            fn += 1
        else:
            tn += 1
    n = len(items) or 1
    return {
        "n": len(items),
        "callsign_accuracy": round(cs_ok / n, 3),
        "action_accuracy": round(act_ok / n, 3),
        "runway_accuracy": round(rwy_ok / rwy_n, 3) if rwy_n else None,
        "readback_error_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "readback_error_recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "rows": rows,
    }


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


async def transcribe_live(items: list[Item], tts_factory=None, stt_factory=None):
    """Returns (heard instructions, heard readbacks, finalize ms per line, (instruction, readback) audio ms per item)."""
    """Speak each line with Cartesia TTS and transcribe it with Cartesia STT, sent fast (W3)."""
    from unstep.cockpit.audio import SAMPLE_RATE
    from unstep.cockpit.stt import CartesiaManualSTT, build_keyterms
    from unstep.live.radio import to_mono16k

    if tts_factory is None:
        from unstep.cockpit.tts import CartesiaTTS

        tts_factory = CartesiaTTS
    terms = build_keyterms(callsigns=[s for _, s, *_ in scenario.FLEET], runways=RUNWAYS)
    stt_factory = stt_factory or (lambda: CartesiaManualSTT(keyterms=terms))
    tts = tts_factory()
    heard_i, heard_r, final_ms, audio_ms = [], [], [], []
    for item in items:
        lengths = []
        for text, out in ((item.instruction, heard_i), (item.readback, heard_r)):
            speech = await tts.speak(text)
            pcm = (to_mono16k(speech.pcm, speech.sample_rate) * 32767).astype("<i2").tobytes()
            lengths.append(round(len(pcm) / 2 / SAMPLE_RATE * 1000, 1))
            async with stt_factory() as stt:
                for i in range(0, len(pcm), SAMPLE_RATE // 5):
                    await stt.send_audio(pcm[i:i + SAMPLE_RATE // 5])
                t = time.perf_counter()
                out.append((await stt.finalize()).text)
                final_ms.append((time.perf_counter() - t) * 1000)
        audio_ms.append(tuple(lengths))
    return heard_i, heard_r, final_ms, audio_ms


def sessions_summary(path: Path) -> dict:
    """Latency per stage and readback outcomes from a live-session event log (JSONL envelopes)."""
    stages: dict[str, list[float]] = {}
    readbacks = {"match": 0, "wrong": 0}
    events = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            env = json.loads(line)
        except ValueError:
            continue
        kind, data = env.get("type"), env.get("data") or {}
        if kind == "AnomalyEvent":
            events += 1
        elif kind == "ReadbackResult":
            readbacks["match" if data.get("match") else "wrong"] += 1
        elif kind == "AuditRecord" and isinstance(data.get("latency_ms"), (int, float)):
            stages.setdefault(data.get("stage", "?"), []).append(float(data["latency_ms"]))
    return {"blocked_calls": events, "readbacks": readbacks,
            "latency_ms": {k: {"n": len(v), "p50": pct(v, 0.5), "p95": pct(v, 0.95)} for k, v in sorted(stages.items())}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=40)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true", help="text only, no API calls")
    parser.add_argument("--live", action="store_true", help="Cartesia TTS and STT (needs keys)")
    parser.add_argument("--sessions", type=Path, help="JSONL event log from live sessions")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    items = build_items(args.n, args.seed)
    result: dict = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "seed": args.seed,
                    "errors": {e: sum(i.error == e for i in items) for e in ERRORS}}
    result["text_only"] = score(items, [i.instruction for i in items], [i.readback for i in items])
    if args.live and not args.dry_run:
        heard_i, heard_r, final_ms, audio_ms = asyncio.run(transcribe_live(items))
        lengths = [ms for pair in audio_ms for ms in pair]
        result["live"] = {**score(items, heard_i, heard_r, audio_ms),
                          "stt_finalize_ms": {"p50": pct(final_ms, 0.5), "p95": pct(final_ms, 0.95)},
                          "audio_ms": {"p50": pct(lengths, 0.5), "p95": pct(lengths, 0.95)}}
    if args.sessions:
        result["sessions"] = sessions_summary(args.sessions)
    if args.dry_run:
        result["items_preview"] = [asdict(i) for i in items[:5]]
    for name in ("text_only", "live"):
        if name in result:
            r = result[name]
            print(f"{name:10} n={r['n']} callsign={r['callsign_accuracy']} action={r['action_accuracy']} "
                  f"runway={r['runway_accuracy']} readback P={r['readback_error_precision']} "
                  f"R={r['readback_error_recall']}" + (f" finalize p50={r['stt_finalize_ms']['p50']} "
                                                       f"p95={r['stt_finalize_ms']['p95']} ms"
                                                       f" (lines p50 {r['audio_ms']['p50']} ms long)"
                                                       if name == "live" else ""))
            for row in r["rows"]:
                if not (row["callsign_ok"] and row["action_ok"] and row["runway_ok"] is not False) \
                        or row["flagged"] != row["labelled"]:
                    print(f"  miss {row['id']}: said {row['text']!r} heard {row['heard']!r}"
                          + (f" | readback {row['heard_readback']!r} flagged={row['flagged']} "
                             f"labelled={row['labelled']}" if row["flagged"] != row["labelled"] else ""))
    if "sessions" in result:
        print("sessions  ", json.dumps(result["sessions"])[:400])
    if not args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)
        path = args.out / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps(result, indent=2))
        print(f"wrote {path}")
    else:
        print(json.dumps(result["errors"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
