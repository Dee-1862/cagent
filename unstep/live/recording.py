"""Recording-session mode: record a real dataset of people talking on the live room's radio.

The presenter (controller seat) starts a session; every push-to-talk transmission from a person
who ticked the consent box is saved as a 16 kHz WAV under data/recordings/<session>/ with one
manifest row per clip, and every stepped-on cluster is also saved as the mix the cockpits heard,
with the overlap windows from key timing as ground truth. People get their next line from a
prompter; the tower is cued to talk over a plane at planned moments, so overlaps happen on purpose.

Manifest rows (manifest.jsonl):
  kind "clip": clip, station, speaker_name, script_line, script_kind, transcript, start_ms, end_ms, duration_s,
               overlaps [{with, start_ms, end_ms}], stepped_on, readback_of, readback_directive,
               qc {clipping, silence, rms}, session, recorded_at
  kind "mix":  clip, stations, start_ms, end_ms, overlaps [{stations, start_ms, end_ms}], session
"""

from __future__ import annotations

import json
import random
import re
import time
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf

from unstep import scenario
from unstep.cockpit.audio import SAMPLE_RATE
from unstep.config import ROOT

RECORDINGS = ROOT / "data" / "recordings"
MIN_CLIP_S = 0.3
CLIP_LEVEL = 0.99  # a sample at or above this counts as clipped
CLIPPED_SHARE = 0.01  # more than 1% clipped samples flags the clip
SILENT_RMS = 0.005
TALK_OVER_EVERY = 3  # every 3rd tower line cues a plane to talk over it

DIGITS = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven",
          "8": "eight", "9": "niner"}
RUNWAYS = ["33", "28L", "15", "4R"]


def say_digits(text: str) -> str:
    return " ".join(DIGITS[c] for c in text if c.isdigit()) + (
        {"L": " left", "R": " right", "C": " center"}.get(text[-1], "") if text[-1:].isalpha() else "")


def say_callsign(spoken: str) -> str:
    """'Cessna 1-2-3' -> 'Cessna one two three' (digits as words, niner for 9)."""
    return re.sub(r"\d(?:-\d)*", lambda m: say_digits(m.group(0).replace("-", "")), spoken)


def tower_lines(seed: int = 1, n: int = 40) -> list[dict]:
    """Instructions for the tower, to every plane in the fleet, restrictive and permissive."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        callsign, spoken, name, _ = rng.choice(scenario.FLEET)
        rwy = rng.choice(RUNWAYS)
        template = rng.choice([
            "{cs}, hold short runway {rwy}.", "{cs}, runway {rwy}, line up and wait.",
            "{cs}, runway {rwy}, cleared for takeoff.", "{cs}, hold position.", "{cs}, go around.",
            "{cs}, taxi to runway {rwy} via Bravo, hold short runway {rwy}.", "{cs}, runway {rwy}, cleared to land.",
        ])
        out.append({"line": template.format(cs=say_callsign(spoken), rwy=say_digits(rwy)), "to": callsign, "plane": name})
    return out


def pilot_lines(callsign: str, spoken: str, seed: int = 1, n: int = 30) -> list[dict]:
    """Requests and readbacks for one plane; a few readbacks are wrong on purpose (labelled)."""
    rng = random.Random(f"{seed}-{callsign}")
    me = say_callsign(spoken)
    out = []
    for i in range(n):
        rwy = rng.choice(RUNWAYS)
        kind = rng.choice(["readback", "readback", "request", "wrong_readback"])
        if kind == "readback":
            line = f"Hold short runway {say_digits(rwy)}, {me}."
        elif kind == "wrong_readback":
            other = rng.choice([r for r in RUNWAYS if r != rwy])
            line = f"Hold short runway {say_digits(other)}, {me}."
        else:
            line = rng.choice([f"Tower, {me}, ready for departure runway {say_digits(rwy)}.",
                               f"Ground, {me}, at the ramp, request taxi to runway {say_digits(rwy)}.",
                               f"Tower, {me}, request transition over the field, northbound."])
        out.append({"line": line, "kind": kind})
    return out


def qc(pcm: np.ndarray) -> dict:
    x = np.asarray(pcm, dtype=np.float32)
    rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    clipped = float(np.mean(np.abs(x) >= CLIP_LEVEL)) if len(x) else 0.0
    return {"rms": round(rms, 5), "clipping": clipped > CLIPPED_SHARE, "silence": rms < SILENT_RMS}


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")[:40] or "session"


class Recorder:
    def __init__(self, session: str | None = None, root: Path | None = None, seed: int = 1):
        self.session = safe_name(session or time.strftime("rec-%Y%m%d-%H%M%S"))
        self.dir = (root or RECORDINGS) / self.session
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self.dir / "manifest.jsonl"
        self.started = int(time.time() * 1000)
        self.seed = seed
        self.counts = {"clips": 0, "overlaps": 0, "mixes": 0, "dropped": 0, "flagged": 0}
        self.by_speaker: dict[str, int] = {}
        self.tower = tower_lines(seed)
        self.pilot: dict[str, list[dict]] = {}
        self.next_index: dict[str, int] = {}
        self.tower_said = 0

    # ---- prompter

    def prompt(self, station: str, spoken: str | None) -> dict:
        lines = self.tower if station == "atc" else self.pilot.setdefault(station, pilot_lines(station, spoken or station, self.seed))
        i = self.next_index.get(station, 0) % len(lines)
        return {"type": "prompt", "station": station, "index": i, **lines[i], "cue": None}

    def advance(self, station: str) -> None:
        self.next_index[station] = self.next_index.get(station, 0) + 1

    def talk_over_target(self, planes: list[str]) -> str | None:
        """On every TALK_OVER_EVERY-th tower call, one plane is asked to talk at the same time."""
        self.tower_said += 1
        if not planes or self.tower_said % TALK_OVER_EVERY:
            return None
        return planes[(self.tower_said // TALK_OVER_EVERY) % len(planes)]

    # ---- saving

    def _row(self, row: dict) -> None:
        with self.manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def save_clip(self, *, station: str, speaker: str, pcm: np.ndarray, start_ms: int, end_ms: int,
                  script_line: str | None, transcript: str | None, overlaps: list[dict], script_kind: str | None = None,
                  readback_of: str | None = None, readback_directive: str | None = None) -> dict | None:
        pcm = np.asarray(pcm, dtype=np.float32)
        if len(pcm) < MIN_CLIP_S * SAMPLE_RATE:
            self.counts["dropped"] += 1
            return None
        checks = qc(pcm)
        clip = f"{station}-{start_ms}-{uuid.uuid4().hex[:6]}.wav"
        sf.write(self.dir / clip, pcm, SAMPLE_RATE, subtype="PCM_16")
        row = {"kind": "clip", "clip": clip, "station": station, "speaker_name": speaker, "script_line": script_line,
               "script_kind": script_kind,
               "transcript": transcript, "start_ms": start_ms, "end_ms": end_ms,
               "duration_s": round(len(pcm) / SAMPLE_RATE, 3), "overlaps": overlaps, "stepped_on": bool(overlaps),
               "readback_of": readback_of, "readback_directive": readback_directive, "qc": checks,
               "session": self.session, "recorded_at": int(time.time() * 1000)}
        self._row(row)
        self.counts["clips"] += 1
        self.counts["overlaps"] += bool(overlaps)
        self.counts["flagged"] += checks["clipping"] or checks["silence"]
        self.by_speaker[speaker] = self.by_speaker.get(speaker, 0) + 1
        return row

    def save_mix(self, *, pcm: np.ndarray, stations: list[str], start_ms: int, end_ms: int, overlaps: list[dict]) -> dict:
        clip = f"mix-{start_ms}-{uuid.uuid4().hex[:6]}.wav"
        sf.write(self.dir / clip, np.asarray(pcm, dtype=np.float32), SAMPLE_RATE, subtype="PCM_16")
        row = {"kind": "mix", "clip": clip, "stations": stations, "start_ms": start_ms, "end_ms": end_ms,
               "overlaps": overlaps, "session": self.session, "recorded_at": int(time.time() * 1000)}
        self._row(row)
        self.counts["mixes"] += 1
        return row

    def status(self) -> dict:
        return {"type": "recording", "on": True, "session": self.session, **self.counts,
                "by_speaker": dict(self.by_speaker), "started": self.started}
