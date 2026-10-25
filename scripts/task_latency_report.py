"""Per-task time, Unstep against human air traffic control, with the evidence grade on every number.

Different jobs take different amounts of time, so this compares job by job and does not average them into one
figure. The machine side is measured where it can be (this script) or taken from live runs recorded in the docs;
the human side is only a published figure (SOURCED), our own arithmetic (MODELLED) or absent (NOT_MEASURED, so no
comparison is made). It does not claim agents are faster at everything: speaking a clearance takes as long as the
words take, and the model-written explanation is slower than a person's glance.

    python scripts/task_latency_report.py            # offline measurements, plus the recorded live numbers
    python scripts/task_latency_report.py --live     # also measures Cartesia speech (needs CARTESIA_API_KEY)
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

from unstep import scenario  # noqa: E402
from unstep.config import env  # noqa: E402
from unstep.contracts import ApprovedDirective, Slots  # noqa: E402
from unstep.ground.percolate import LocalPercolator  # noqa: E402
from unstep.ground.rules import LocalRules  # noqa: E402

BASELINES = ROOT / "assets" / "human_baselines.json"
CLEARANCES = ["Cessna one two three, hold short runway three three",
              "Cessna one two three, cleared for takeoff runway three three",
              "Helicopter four five six, taxi to runway three three via Alpha"]


def human_baselines() -> dict:
    return {i["id"]: i for i in json.loads(BASELINES.read_text())["items"]}


def p50(samples: list[float]) -> float:
    return round(statistics.median(samples), 4)


def timed(fn, runs: int = 500) -> list[float]:
    out = []
    for _ in range(runs):
        started = time.perf_counter()
        fn()
        out.append((time.perf_counter() - started) * 1000)
    return out


def measure_offline() -> dict:
    rules = LocalRules()
    lookup = p50(timed(lambda: rules.match("Cessna one two three, hold short runway three three")))

    async def readback() -> list[float]:
        perc = LocalPercolator()
        directive = ApprovedDirective(event_id="e", instruction_text="Cessna 1-2-3, hold short runway 33",
                                      slots=Slots(callsign="N123AB", action="hold short", runway="33"),
                                      approved_by="atc", approved_via="click")
        await perc.register(directive)
        out = []
        for _ in range(300):
            v = await perc.check("e", "hold short runway three three, Cessna one two three")
            out.append(v.took_ms)
        return out

    return {"rule_lookup_ms": lookup, "readback_check_ms": p50(asyncio.run(readback()))}


async def measure_speech() -> dict:
    from unstep.cockpit.tts import CartesiaTTS

    tts = CartesiaTTS()
    first, durations, words = [], [], []
    try:
        for text in CLEARANCES * 2:
            res = await tts.speak(text)
            first.append(res.first_audio_ms)
            durations.append(len(res.pcm) / 2 / res.sample_rate)
            words.append(len(text.split()))
    finally:
        await tts.close()
    return {"first_audio_ms": round(statistics.median(first[1:] or first)), "spoken_s": round(statistics.median(durations), 2),
            "words": round(statistics.median(words)), "n": len(first)}


def table(offline: dict, speech: dict | None, human: dict) -> list[tuple]:
    say_again = human["say_again_cycle"]["seconds"]
    syllables = 13  # "Cessna one two three, cleared for takeoff runway three three"
    spoken_s = round(syllables / human["atc_speech_rate"]["syllables_per_second"], 1)
    rows = [
        ("Notice a stepped-on call",
         "no automatic detection (FAA CAMI 2005); noticed through consequences, time not measured",
         "key overlap known within one network hop; call end to cockpit flagged about 1.0 s (Rishit, live)",
         "Unstep: the only one that detects it. Detection rate 91.7% is on simulated calls"),
        ("Recover the lost instruction",
         f"say again and retransmit: about {say_again} s, DERIVED from the cited controller speech rate plus a 1.5 s reaction taken from a driving study, only if someone noticed",
         "2.9 s call end to the pilot hearing the fix, including the controller's approval (Rishit, live)",
         "Unstep faster; most of its 2.9 s is the human approving"),
        ("Check a readback",
         "pilot readback starts about 0.6 s after the instruction (NASA 2022); the controller's catch is unmeasured and often missed",
         f"3.0 ms in Elastic (live); {offline['readback_check_ms']} ms in process (measured here)",
         "No human figure, so no comparison (the 0.6 s is the pilot's wait before reading back, not a controller's checking time); people stay the decision"),
        ("Find the governing FAA paragraph",
         "from memory, not measured",
         f"{offline['rule_lookup_ms']} ms from the hub's stored rules (measured here); 0.7 to 1.1 s by hybrid search plus rerank when no rule is stored",
         "no human figure, so no comparison"),
        ("Speak a clearance",
         f"about {spoken_s} s for a {syllables}-syllable clearance at the median controller rate of 6.1 syllables per second (Nitta, Okazaki and Klinger 2011)",
         (f"first audio {speech['first_audio_ms']} ms, whole phrase {speech['spoken_s']} s (Cartesia, measured here, {speech['n']} calls)"
          if speech else "first audio about 140 ms, whole phrase about 3.9 s (run with --live to measure)"),
         "Unstep starts within about 140 ms but its phrase takes about 3.7 s of speech (3.5 syllables per second) against about 2.1 s at the median controller rate. Sonic's top speed setting (1.5) reaches about 4.1 syllables per second and mishears a word; slower speech is also easier for non-native listeners (21.2% of words missed at 6 syllables per second)"),
        ("Explain why, or write a handoff briefing",
         "not measured for controllers; a bracket from other fields: a 60-word note takes about 70 s to type (51.56 wpm) or about 18 s to say (196 wpm)",
         "about 10 to 11.5 s through Elastic agents (live); skipping Intercept did not help; under 0.1 s only on a cache hit (cache off by default)",
         "Likely faster than typing, slower than saying it; this runs after the card is on screen, off the path a pilot waits on"),
    ]
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="also measure Cartesia speech")
    args = parser.parse_args()
    human = human_baselines()
    offline = measure_offline()
    speech = None
    if args.live:
        if not env("CARTESIA_API_KEY"):
            print("CARTESIA_API_KEY not set: skipping the speech measurement")
        else:
            speech = asyncio.run(measure_speech())
    rows = table(offline, speech, human)
    for task, h, u, verdict in rows:
        print(f"\n{task}\n   human:  {h}\n   Unstep: {u}\n   verdict: {verdict}")
    out = ROOT / "data" / "task-latency"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"offline": offline, "speech": speech, "rows": rows}, indent=1))
    print(f"\nwrote {path.relative_to(ROOT)}. Human figures are SOURCED, MODELLED or absent (assets/human_baselines.json).")


if __name__ == "__main__":
    main()
