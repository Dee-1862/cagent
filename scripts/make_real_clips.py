"""Generate real-speech demo clips with Cartesia TTS into assets/clips/real/.

The synthetic placeholders in assets/clips/ are left alone. Clips are 16 kHz mono WAV:

- clean_call.wav        tower: "Cessna one two three, hold short runway three three"
- helicopter_call.wav   second voice: "Helicopter four five six, request ..."
- stepped_on_call.wav   tower call with the helicopter call and a heterodyne beat
                        tone mixed in from 1.3 s to the end of the tower call
- wrong_readback.wav    pilot: "... runway two three ..."
- correct_readback.wav  pilot: "... runway three three ..."
- pilot_question.wav    pilot: "Unstep, what was my last clearance?"
- voices.json           which voice ID spoke which clip

Voices: CARTESIA_TOWER_VOICE_ID, CARTESIA_HELI_VOICE_ID, CARTESIA_PILOT_VOICE_ID
if set, otherwise distinct English voices picked from GET /voices.
Without CARTESIA_API_KEY it prints "skipped: ..." and exits 0.

Run from the repo root: python scripts/make_real_clips.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from unstep.config import cartesia_version  # noqa: E402

SR = 16_000
OUT = ROOT / "assets" / "clips" / "real"
OVERLAP_START_S = 1.3
REST_VERSION = cartesia_version()

TOWER = "Cessna one two three, hold short runway three three."
HELI = "Helicopter four five six, request transition over the field, northbound, at one thousand five hundred."
WRONG = "Hold short runway two three, Cessna one two three."
RIGHT = "Hold short runway three three, Cessna one two three."
QUESTION = "Unstep, what was my last clearance?"


def list_voices(api_key: str, gender: str) -> list[dict]:
    req = urllib.request.Request(
        f"https://api.cartesia.ai/voices?limit=100&language=en&gender={gender}",
        headers={"Authorization": f"Bearer {api_key}", "Cartesia-Version": REST_VERSION},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["data"]


def pick_voices(api_key: str) -> dict[str, dict]:
    env = {"tower": "CARTESIA_TOWER_VOICE_ID", "heli": "CARTESIA_HELI_VOICE_ID", "pilot": "CARTESIA_PILOT_VOICE_ID"}
    chosen: dict[str, dict] = {r: {"id": os.environ[v], "name": f"from {v}"} for r, v in env.items() if os.getenv(v)}
    missing = [r for r in env if r not in chosen]
    if missing:
        masc = list_voices(api_key, "masculine")
        fem = list_voices(api_key, "feminine")
        pools = {"tower": masc, "heli": masc, "pilot": fem or masc}
        used = {v["id"] for v in chosen.values()}
        for role in missing:
            for v in pools[role]:
                if v["id"] not in used:
                    chosen[role] = {"id": v["id"], "name": v.get("name", "")}
                    used.add(v["id"])
                    break
            else:
                raise RuntimeError(f"no unused English voice for {role}")
    return chosen


async def speak(voice_id: str, text: str) -> np.ndarray:
    from unstep.cockpit.tts import CartesiaTTS, pcm_bytes_to_array

    tts = CartesiaTTS(voice_id=voice_id, sample_rate=SR, speed=1.0, emotion="neutral")
    try:
        res = await tts.speak(text)
    finally:
        await tts.close()
    pcm = pcm_bytes_to_array(res.pcm).astype(np.float32) / 32768.0
    if not len(pcm):
        raise RuntimeError(f"no audio for {text!r}")
    # Small lead-in so the squelch opens on silence, like a real transmission.
    return np.concatenate([np.zeros(int(0.1 * SR), np.float32), pcm, np.zeros(int(0.1 * SR), np.float32)])


def beat_tone(n: int, f0: float = 1600.0, f1: float = 1900.0, level: float = 0.15, seed: int = 2) -> np.ndarray:
    """Two carriers beating: drifting tone with slow AM plus light static."""
    t = np.arange(n) / SR
    phase = 2 * np.pi * np.cumsum(np.linspace(f0, f1, n)) / SR
    am = 0.8 + 0.2 * np.sin(2 * np.pi * 7 * t)
    static = np.random.default_rng(seed).standard_normal(n) * level * 0.15
    return (np.sin(phase) * am * level + static).astype(np.float32)


def stepped_on(tower: np.ndarray, heli: np.ndarray, tower_gain: float = 0.12) -> np.ndarray:
    """Two carriers of similar strength garble each other on AM: the tower's words
    after the overlap start are buried under the helicopter and the beat tone."""
    out = tower.copy()
    a = int(OVERLAP_START_S * SR)
    n = len(out) - a
    if n <= 0:
        raise RuntimeError("tower call shorter than the overlap start")
    out[a:] *= tower_gain
    over = np.zeros(n, np.float32)
    h = heli[:n]
    over[: len(h)] += 0.9 * h
    over += beat_tone(n, level=0.35)
    # Short fade-in so the second carrier keys up instead of clicking.
    ramp = min(n, int(0.02 * SR))
    over[:ramp] *= np.linspace(0, 1, ramp)
    out[a:] += over
    peak = np.max(np.abs(out))
    return out / peak * 0.9 if peak > 0.99 else out


async def main() -> int:
    api_key = os.getenv("CARTESIA_API_KEY")
    if not api_key:
        print("skipped: CARTESIA_API_KEY not set")
        return 0

    from unstep.cockpit.audio import write_wav

    voices = pick_voices(api_key)
    for role, v in voices.items():
        print(f"voice {role}: {v['id']} ({v['name']})")

    tower = await speak(voices["tower"]["id"], TOWER)
    heli = await speak(voices["heli"]["id"], HELI)
    clips = {
        "clean_call.wav": (tower, "tower", TOWER),
        "helicopter_call.wav": (heli, "heli", HELI),
        "stepped_on_call.wav": (stepped_on(tower, heli), "tower+heli", f"{TOWER} | {HELI}"),
        "wrong_readback.wav": (await speak(voices["pilot"]["id"], WRONG), "pilot", WRONG),
        "correct_readback.wav": (await speak(voices["pilot"]["id"], RIGHT), "pilot", RIGHT),
        "pilot_question.wav": (await speak(voices["pilot"]["id"], QUESTION), "pilot", QUESTION),
    }
    manifest = {"sample_rate": SR, "overlap_start_s": OVERLAP_START_S,
                "overlap_end_s": round(len(tower) / SR, 3), "voices": voices, "clips": {}}
    for name, (pcm, role, text) in clips.items():
        path = write_wav(OUT / name, pcm, SR)
        manifest["clips"][name] = {"role": role, "text": text, "seconds": round(len(pcm) / SR, 3)}
        print(f"wrote {path.relative_to(ROOT)} ({len(pcm) / SR:.2f} s)")
    (OUT / "voices.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {(OUT / 'voices.json').relative_to(ROOT)}")
    return 0


def remix() -> int:
    """Rebuild stepped_on_call.wav from the existing clean and helicopter clips, no API calls."""
    import soundfile as sf

    d = OUT_DIR if "OUT_DIR" in globals() else Path(__file__).resolve().parents[1] / "assets" / "clips" / "real"
    tower, _ = sf.read(d / "clean_call.wav", dtype="float32")
    heli, _ = sf.read(d / "helicopter_call.wav", dtype="float32")
    sf.write(d / "stepped_on_call.wav", stepped_on(tower, heli), SR)
    print(f"wrote {d / 'stepped_on_call.wav'}")
    return 0


if __name__ == "__main__":
    sys.exit(remix() if "--remix" in sys.argv else asyncio.run(main()))
