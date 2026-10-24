"""Simulated traffic through the real live room, for the benchmark (docs/18-benchmark.md).

Simulated: every call here is scripted synthetic traffic processed by the real room code; nothing in its output is real usage, and every record carries `simulated: true` and the run's `run_id`.

Each session starts a real `LiveRoom` (offline speech, local memory) with several planes. Per call the
tower gives one plane an instruction from FAA-style templates (restrictive or permissive). With a set
probability another plane keys at a random offset, so the tower's call is stepped on (ground truth from
the script). A simulated controller decides proposals that need a human (approves 90%, otherwise rejects),
and the plane reads back, wrong on purpose at a set rate. Calls are back-dated so the room processes them
at once: counts and rates are meaningful, timings are not (those come from live runs).

    python scripts/simulate_traffic.py --sessions 20 --calls 25 --seed 7
    python scripts/simulate_traffic.py --sessions 2 --calls 10          # quick

Output: data/sim/<run_id>/calls.jsonl (one row per call), envelopes.jsonl (every message through the
gateway, tagged) and summary.json. With Elastic configured and --elastic, the gateway's records also go to
the `unstep-sim-events` index (never the real events index), each with `simulated: true` and `run_id`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import uuid
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep import scenario  # noqa: E402
from unstep.clock import now_ms  # noqa: E402
from unstep.cockpit.phraseology import parse_instruction  # noqa: E402
from unstep.evaluation import proportion  # noqa: E402
from unstep.live.recording import say_callsign, say_digits  # noqa: E402

OUT = ROOT / "data" / "sim"
SIM_INDEX = "unstep-sim-events"
RUNWAYS = ["33", "28L", "15", "4R"]
RESTRICTIVE = ["{cs}, hold short runway {rwy}.", "{cs}, hold position.", "{cs}, go around."]
PERMISSIVE = ["{cs}, runway {rwy}, cleared for takeoff.", "{cs}, runway {rwy}, line up and wait.",
              "{cs}, runway {rwy}, cleared to land."]
OTHER = ["Tower, {cs}, request transition over the field, northbound.", "Tower, {cs}, ready for departure.",
         "Ground, {cs}, at the ramp, request taxi."]


class TaggingSink:
    """Wraps the gateway's sink: every envelope gets `simulated: true` and the run id, and is kept."""

    def __init__(self, run_id: str, inner=None, path: Path | None = None):
        self.run_id, self.inner, self.path = run_id, inner, path

    def write(self, envelope: dict) -> None:
        envelope = {**envelope, "simulated": True, "run_id": self.run_id}
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(envelope) + "\n")
        if self.inner is not None:
            self.inner.write(envelope)

    async def aclose(self) -> None:
        if self.inner is not None and hasattr(self.inner, "aclose"):
            await self.inner.aclose()


def speech(text: str, word_s: float = 0.25):
    """Fake speech: a tone per word and word times (the room's offline voice)."""
    from unstep.cockpit.tts import FakeTTS

    words = text.split()
    n = int(16000 * word_s)
    t = np.arange(n) / 16000
    tone = (0.05 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    pcm = np.concatenate([tone for _ in words]) if words else np.zeros(1, np.float32)
    stamps = [(w, i * word_s, (i + 1) * word_s) for i, w in enumerate(words)]
    del FakeTTS
    return pcm, stamps


async def wait(pred, timeout: float) -> bool:
    end = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > end:
            return False
        await asyncio.sleep(0.02)
    return True


async def run_session(k: int, run_id: str, rng: random.Random, calls: int, p_step: float, p_wrong: float,
                      p_permissive: float, inner_sink, envelopes: Path) -> list[dict]:
    from unstep.cockpit.memory import LocalMemory
    from unstep.cockpit.tts import FakeTTS
    from unstep.gateway.server import create_app
    from unstep.live import room as room_mod
    from unstep.live.radio import Transmission

    room_mod.create_memory = LocalMemory  # local memory: fast and offline
    app = create_app(TaggingSink(run_id, inner_sink, envelopes))
    room = room_mod.LiveRoom(app.state.gateway, live=False, tts_factory=lambda v: FakeTTS(), advisory_tts=FakeTTS())
    await room.start()
    room.policy.enabled = rng.random() < 0.5  # half the sessions auto-relay routine stop calls
    for _ in range(4):  # the two team planes plus two walk-up planes
        await room.claim_aircraft()
    planes = [sid for sid, st in room.stations.items() if st.kind == "aircraft"]
    rows = []
    base = now_ms() - 3_600_000  # back-dated: processed at once
    for i in range(calls):
        plane = rng.choice(planes)
        spoken = scenario.SPOKEN[plane]
        restrictive = rng.random() >= p_permissive
        rwy = rng.choice(RUNWAYS)
        line = rng.choice(RESTRICTIVE if restrictive else PERMISSIVE).format(cs=say_callsign(spoken), rwy=say_digits(rwy))
        stepped = rng.random() < p_step
        start = base + i * 30_000
        pcm, words = speech(line)
        before = set(room.traces)
        await room.transmit(Transmission("atc", start, pcm, text=line, words=words))
        other = None
        if stepped:
            other = rng.choice([p for p in planes if p != plane])
            o_line = rng.choice(OTHER).format(cs=say_callsign(scenario.SPOKEN[other]))
            o_pcm, o_words = speech(o_line)
            offset = rng.randint(300, max(400, int(len(pcm) / 16) - 300))
            await room.transmit(Transmission(other, start + offset, o_pcm, text=o_line, words=o_words))
        new = lambda: [t for eid, t in room.traces.items() if eid not in before and t.get("callsign") == plane]  # noqa: E731
        detected = await wait(lambda: bool(new()), 2.0 if stepped else 0.6)
        row = {"simulated": True, "run_id": run_id, "session": k, "call": i, "plane": plane, "instruction": line,
               "restrictive": restrictive, "stepped_on": stepped, "talked_over_by": other, "detected": detected,
               "auto_relay_on": room.policy.enabled}
        if detected:
            trace = new()[0]
            await wait(lambda: trace["status"] not in ("detected", "proposed"), 3.0)
            if trace["status"] == "needs_you":
                approve = rng.random() < 0.9
                await room.decide(trace["event_id"], approve=approve)
                row["controller"] = "approved" if approve else "rejected"
            await wait(lambda: trace["status"] in ("delivered", "rejected", "expired", "confirmed", "readback_wrong"), 3.0)
            truth = parse_instruction(line)
            prop = (trace.get("proposal") or {}).get("slots") or {}
            row.update({"status_after_decision": trace["status"], "proposal": (trace.get("proposal") or {}).get("instruction_text"),
                        "proposal_correct": bool(truth) and prop.get("action") == truth.action
                        and (prop.get("runway") or None) == (truth.runway or None),
                        "auto_relayed": any(s["kind"] == "auto_relay" for s in trace["steps"])})
            if trace["status"] == "delivered":
                wrong = rng.random() < p_wrong
                said_rwy = rng.choice([r for r in RUNWAYS if r != rwy]) if wrong else rwy
                rb = (f"Hold short runway {say_digits(said_rwy)}, {say_callsign(spoken)}." if "hold short" in line
                      else f"{line.split(', ', 1)[1].rstrip('.')}, {say_callsign(spoken)}." if not wrong
                      else f"Hold short runway {say_digits(said_rwy)}, {say_callsign(spoken)}.")
                rb_pcm, rb_words = speech(rb)
                n_before = len(trace["readbacks"])
                await room.transmit(Transmission(plane, now_ms() - 10_000, rb_pcm, text=rb, words=rb_words))
                await wait(lambda: len(trace["readbacks"]) > n_before, 3.0)
                last = trace["readbacks"][-1] if len(trace["readbacks"]) > n_before else None
                row.update({"readback": rb, "readback_wrong": wrong,
                            "readback_flagged": None if last is None else not last["match"]})
        rows.append(row)
    await room.stop()
    return rows


def summarize(rows: list[dict], run_id: str, args: dict) -> dict:
    stepped = [r for r in rows if r["stepped_on"]]
    clean = [r for r in rows if not r["stepped_on"]]
    detected = [r for r in stepped if r["detected"]]
    restrictive_detected = [r for r in detected if r["restrictive"]]
    rb = [r for r in rows if r.get("readback_flagged") is not None]
    tp = sum(r["readback_flagged"] and r["readback_wrong"] for r in rb)
    fp = sum(r["readback_flagged"] and not r["readback_wrong"] for r in rb)
    fn = sum(not r["readback_flagged"] and r["readback_wrong"] for r in rb)
    return {"simulated": True, "run_id": run_id, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "params": args,
            "calls": len(rows), "stepped_on_calls": len(stepped),
            "status_quo_automatic_detection": proportion(0, len(stepped)),
            "detected_stepped_on": proportion(len(detected), len(stepped)),
            "false_events_on_clean_calls": proportion(sum(r["detected"] for r in clean), len(clean)),
            "proposal_correct_when_detected": proportion(sum(bool(r.get("proposal_correct")) for r in detected), len(detected)),
            "delivered_restrictive": proportion(sum(r.get("status_after_decision") in ("delivered", "confirmed", "readback_wrong")
                                                    for r in restrictive_detected), len(restrictive_detected)),
            "readback_error_precision": proportion(tp, tp + fp), "readback_error_recall": proportion(tp, tp + fn),
            "auto_relayed": sum(bool(r.get("auto_relayed")) for r in detected),
            "controller_decisions": sum(1 for r in detected if r.get("controller"))}


async def main_async(args) -> dict:
    run_id = f"sim-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    out = args.out / run_id
    out.mkdir(parents=True, exist_ok=True)
    inner = None
    if args.elastic:
        from unstep.config import elastic_settings
        from unstep.gateway.sink import ElasticSink

        settings = elastic_settings()
        inner = ElasticSink(*settings, index=SIM_INDEX) if settings else None
    rng = random.Random(args.seed)
    rows = []
    for k in range(args.sessions):
        rows += await run_session(k, run_id, rng, args.calls, args.p_step, args.p_wrong, args.p_permissive,
                                  inner, out / "envelopes.jsonl")
        print(f"session {k + 1}/{args.sessions}: {len(rows)} calls so far")
    if inner is not None:
        await inner.aclose()
    (out / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    summary = summarize(rows, run_id, {k: v for k, v in vars(args).items() if k != "out"} | {"out": str(args.out)})
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sessions", type=int, default=20)
    p.add_argument("--calls", type=int, default=25)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--p-step", type=float, default=0.3, help="share of tower calls stepped on")
    p.add_argument("--p-wrong", type=float, default=0.25, help="share of readbacks wrong on purpose")
    p.add_argument("--p-permissive", type=float, default=0.3)
    p.add_argument("--elastic", action="store_true", help=f"also send records to {SIM_INDEX}")
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args(argv)
    s = asyncio.run(main_async(args))
    print(json.dumps({k: v for k, v in s.items() if k != "params"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
