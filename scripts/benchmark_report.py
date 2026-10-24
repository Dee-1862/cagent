"""Write docs/18-benchmark.md from the latest benchmark results, each kind of data under its own heading.

    python scripts/benchmark_report.py                       # latest of each kind found under data/
    python scripts/benchmark_report.py --sim data/sim/<run>/summary.json --bench data/eval/<run>.json

Inputs (all optional; a missing one is reported as "not run yet" with the command to run):
  --sim        scripts/simulate_traffic.py summary          -> "Simulated traffic (n=...)"
  --bench      scripts/eval_bench.py --live result           -> "Speech under radio conditions" (and ATCO2)
  --recorded   scripts/eval_unstep.py --recordings result    -> "Recorded sessions"
Fake-speech benchmark runs are never used. Every proportion shows n and a Wilson 95% interval.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DOC = ROOT / "docs" / "18-benchmark.md"
WORD_MS = 250  # the simulator's offline voice: one word per 250 ms
GAP_MS = 300  # the room's quiet gap between calls
REACTION_MS = 1500  # assumption: a pilot who noticed the garble starts "say again" after 1.5 s


def latest(pattern: str, want=lambda d: True) -> Path | None:
    files = sorted((ROOT / "data").glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        try:
            if want(json.loads(f.read_text())):
                return f
        except (OSError, ValueError):
            continue
    return None


def p(x: dict | None) -> str:
    if not x or x.get("value") is None:
        return "n/a"
    lo, hi = x["ci95"]
    return f"{x['value'] * 100:.1f}% [{lo * 100:.1f}, {hi * 100:.1f}] (n={x['n']})"


def say_again_ms(instruction: str, callsign_words: int = 3) -> int:
    """Modelled "say again" exchange after a stepped-on call that someone noticed (assumptions labelled)."""
    request_words = 3 + callsign_words  # "Tower, <callsign>, say again"
    return REACTION_MS + request_words * WORD_MS + GAP_MS + len(instruction.split()) * WORD_MS + GAP_MS


def section_status_quo() -> str:
    return """## Status quo: no automatic detection

Today nothing tells the pilot or the controller that a call was stepped on. FAA CAMI found blocked, stepped-on or clipped calls in 1.16% of sampled transmissions at the five busiest US TRACONs, and "no alerting system was detected for stepped-on or clipped transmissions through waveform analysis" ([DOT/FAA/AM-05/19, 2005](https://rosap.ntl.bts.gov/view/dot/58248/dot_58248_DS1.pdf)). SKYbrary describes blocked transmissions as going unnoticed by the people talking ([SKYbrary](https://skybrary.aero/articles/blocked-transmissions-undetected-simultaneous-transmissions-usit)). At the NTSB hearing on the 2025 DCA midair, asked whether a controller can tell a call was stepped on, the tower operations manager said: "There's nothing." ([AIN, 2025-08-04](https://backend.ainonline.com/aviation-news/air-transport/2025-08-04/ntsb-dc-midair-hearing-panel-3-covers-frequency-issues)).

So the baseline for automatic detection is 0%: a lost instruction is recovered only if someone notices the garble and asks.
"""


def section_sim(s: dict | None, calls: list[dict]) -> str:
    if not s:
        return "## Simulated traffic\n\nNot run yet: `python scripts/simulate_traffic.py --sessions 20 --calls 25`\n"
    lines = [f"## Simulated traffic (n={s['calls']} calls, {s['stepped_on_calls']} stepped on)", "",
             f"Run `{s['run_id']}`: scripted synthetic traffic processed by the real room code (offline voice, local memory), "
             "every record marked `simulated: true`. Counts and rates are meaningful; timings are not, because calls are back-dated.", "",
             "| Measure | Status quo | Unstep |", "| --- | --- | --- |",
             f"| Stepped-on calls detected automatically | {p(s['status_quo_automatic_detection'])} | {p(s['detected_stepped_on'])} |",
             f"| False events on clean calls | n/a | {p(s['false_events_on_clean_calls'])} |",
             f"| Recovered instruction matches what the tower said (action and runway) | n/a | {p(s['proposal_correct_when_detected'])} |",
             f"| Restrictive instructions delivered privately after detection | n/a | {p(s['delivered_restrictive'])} |",
             f"| Wrong readbacks caught (recall) | n/a | {p(s['readback_error_recall'])} |",
             f"| Readbacks flagged that were really wrong (precision) | n/a | {p(s['readback_error_precision'])} |", "",
             f"Auto-relayed: {s['auto_relayed']}; decided by the simulated controller: {s['controller_decisions']}.",
             "The detection here is the cockpit's audio overlap detector on the room's radio model (a beat tone where two stations transmit); push-to-talk key timing, which the live room also uses, isn't simulated.",
             "The offline room knows each typed line's words, so the recovered instruction and the readback check run on exact text here: those rows measure the pipeline's logic (matching, policy, delivery, the slot checker), not speech recognition. Speech accuracy is in the next sections.", ""]
    stepped = [c for c in calls if c.get("stepped_on")]
    if stepped:
        modelled = sorted(say_again_ms(c["instruction"]) for c in stepped)
        lines += ["### Time to the right instruction: a modelled \"say again\"", "",
                  f"Modelled for the {len(stepped)} stepped-on calls: pilot reaction {REACTION_MS} ms (assumption), "
                  f"\"Tower, <callsign>, say again\" and the tower's full re-transmission at {WORD_MS} ms per word, plus the room's "
                  f"{GAP_MS} ms gaps. Median {modelled[len(modelled) // 2]} ms, and only if someone noticed the garble.", ""]
    return "\n".join(lines) + "\n"


def section_bench(b: dict | None) -> str:
    if not b:
        return "## Speech under radio conditions\n\nNot run yet: `python scripts/eval_bench.py --live --n 200 --store`\n"
    rows = ["## Speech under radio conditions (Cartesia, synthetic lines)", "",
            f"Run `{b.get('run_id')}`, n={b['n']} lines, three voices, through our VHF channel. Synthetic voices, real Cartesia speech-to-text.", "",
            "| Condition | Callsign | Runway | WER | Finalize p50 / p95 |", "| --- | --- | --- | --- | --- |"]
    for name, c in b.get("conditions", {}).items():
        w = c["wer"]
        rows.append(f"| {name} | {p(c['callsign'])} | {p(c['runway'])} | {w['value']} [{w['ci95'][0]}, {w['ci95'][1]}] | "
                    f"{c['finalize_ms']['p50']} / {c['finalize_ms']['p95']} ms |")
    if "keyterms_ab" in b:
        for side in ("with", "without"):
            c = b["keyterms_ab"][side]
            rows.append(f"| radio-10, {side} key terms | {p(c['callsign'])} | {p(c['runway'])} | {c['wer']['value']} | |")
    rb, d = b.get("readbacks"), b.get("detection_audio_only")
    rows += ["", "### Readback check compared with HAAWAII", "",
             "| | Wrong readbacks caught | False alarms |", "| --- | --- | --- |",
             f"| Unstep (radio-10, synthetic) | {p(rb['recall']) if rb else 'n/a'} | {p(rb['false_alarm_rate']) if rb else 'n/a'} |",
             "| HAAWAII (controller lab trials) | about 80% | about 11% |", "",
             "HAAWAII figures from [Idiap](https://publications.idiap.ch/publications/show/4728) and [CORDIS](https://cordis.europa.eu/article/id/442201-better-automatic-speech-recognition-for-safer-air-traffic-control). Conditions differ: their trials used real controller speech and real readbacks; ours are synthetic voices on a simulated radio channel, so this is a sanity check, not a head-to-head result.", ""]
    if d:
        rows += ["### Detection: audio-only overlap detector", "",
                 f"Recall at IoU 0.5: {p(d['recall_iou_0_5'])}; false alarms on clean lines: {p(d['false_alarms_on_clean'])}; "
                 f"latency from the overlap start to the first active frame p50/p95: {d['latency_ms']['p50']} / {d['latency_ms']['p95']} ms. "
                 "In the live room, push-to-talk key timing detects a step-on at the moment the second key goes down, so the audio detector is the backup for radios without key data.", ""]
    if "atco2" in b:
        a = b["atco2"]
        rows += [f"## ATCO2 (real ATC speech, n={a['n']})", "",
                 f"WER {a['wer']['value']} [{a['wer']['ci95'][0]}, {a['wer']['ci95'][1]}]; callsign {p(a['callsign'])}; runway {p(a['runway'])}.", ""]
    return "\n".join(rows) + "\n"


def section_recorded(r: dict | None) -> str:
    if not r:
        return "## Recorded sessions\n\nNot recorded yet: see docs/15 section 6a, then `python scripts/eval_unstep.py --recordings data/dataset/unstep-radio --live`.\n"
    return "\n".join([f"## Recorded sessions (real voices, n={r['n_clips']} clips)", "",
                      f"WER against the prompted line {r['wer']['value']} [{r['wer']['ci95'][0]}, {r['wer']['ci95'][1]}]; "
                      f"callsign {p(r['callsign'])}; runway {p(r['runway'])}; wrong readbacks caught {p(r['readback']['recall'])}, "
                      f"precision {p(r['readback']['precision'])}; overlap detector recall against key timing "
                      f"{p(r['detection']['recall_iou_0_5'])}, false alarms on clean clips {p(r['detection']['false_alarms_on_clean_clips'])}.", ""]) + "\n"


def section_latency() -> str:
    return """## Time from a stepped-on call to the recovered instruction

| | Value | Source |
| --- | --- | --- |
| Before transcribing during the call: call end to the pilot hearing the fix | 6.1 s | Live run on Rishit's laptop (R27), measured on the console waterfall |
| After (8d526bf), live: call end to the pilot hearing the fix | 2.9 s, including the human approval | Live run on Rishit's laptop (R28), console waterfall |
| Tower transcript final after release | 155 ms (was 2702 ms) | Same live run |
| Cockpit transcript final after release | 172 ms (was 2875 ms) | Same live run |
| First audio of the private advisory | 201 ms | Same live run |
| After, in an offline timing model | 0.43 s call end to the recovered proposal (Cartesia at 1.5 times real time, finalize 100 ms after catching up) | `tests/test_on_air_stt.py`; a model, not a measurement |

Still slow after the fix: call end to "cockpit flagged a lost call" is about 1.0 s, and approved to spoken.
"""


def rel(path: Path | None) -> str:
    if path is None:
        return "none"
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return path.name


def build(sim: Path | None, bench: Path | None, recorded: Path | None) -> str:
    s = json.loads(sim.read_text()) if sim else None
    calls = []
    if sim and (sim.parent / "calls.jsonl").is_file():
        calls = [json.loads(x) for x in (sim.parent / "calls.jsonl").read_text().splitlines() if x.strip()]
    b = json.loads(bench.read_text()) if bench else None
    r = json.loads(recorded.read_text()).get("recorded_sessions") if recorded else None
    return "\n".join([
        "# Benchmark", "",
        "How Unstep compares with today's radio and with published work. Simulated traffic, synthetic speech, recorded sessions and ATCO2 are kept under separate headings; nothing simulated is reported as real use.", "",
        "| Field | Value |", "| --- | --- |", "| Status | Generated by `scripts/benchmark_report.py` |",
        f"| Inputs | simulated: {rel(sim)}; speech: {rel(bench)}; recorded: {rel(recorded)} |", "",
        section_status_quo(), section_sim(s, calls), section_latency(), section_bench(b), section_recorded(r)])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sim", type=Path)
    ap.add_argument("--bench", type=Path)
    ap.add_argument("--recorded", type=Path)
    ap.add_argument("--out", type=Path, default=DOC)
    args = ap.parse_args(argv)
    sim = args.sim or latest("sim/*/summary.json", lambda d: d.get("simulated") is True)
    bench = args.bench or latest("eval/eval-*.json", lambda d: d.get("mode") == "live")
    recorded = args.recorded or latest("eval/*.json", lambda d: "recorded_sessions" in d)
    args.out.write_text(build(sim, bench, recorded), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
