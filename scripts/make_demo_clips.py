"""Generate deterministic synthetic demo clips into assets/clips/ (task A1).

Speech is faked with band-limited noise under syllable envelopes. The stepped-on
call adds a second carrier from 1.3 s: a drifting heterodyne beat tone plus static.
Placeholders until real recorded or Cartesia-generated audio replaces them.

Run from the repo root: python scripts/make_demo_clips.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep.cockpit.audio import SAMPLE_RATE, write_wav  # noqa: E402

SR = SAMPLE_RATE
CALL_S = 2.6
OVERLAP_START_S = 1.3
OVERLAP_END_S = 2.6


def speech_like(duration_s: float, seed: int, level: float = 0.25, start_s: float = 0.05,
                end_s: float | None = None, total_s: float | None = None) -> np.ndarray:
    """Band-limited noise (300-3400 Hz) shaped by random syllable envelopes."""
    rng = np.random.default_rng(seed)
    total = int(round((total_s or duration_s) * SR))
    end_s = duration_s - 0.05 if end_s is None else end_s
    sos = butter(4, [300, 3400], btype="bandpass", fs=SR, output="sos")
    noise = sosfilt(sos, rng.standard_normal(total))
    noise /= np.max(np.abs(noise)) + 1e-9
    env = np.zeros(total)
    t = start_s
    while t < end_s:
        syl = rng.uniform(0.12, 0.25)
        a, b = int(t * SR), min(int(min(t + syl, end_s) * SR), total)
        if b > a:
            env[a:b] = np.hanning(b - a) * rng.uniform(0.6, 1.0)
        t += syl + rng.uniform(0.02, 0.08)
    return (noise * env * level).astype(np.float32)


def heterodyne(duration_s: float, seed: int, f0: float = 1600.0, f1: float = 1900.0,
               level: float = 0.3) -> np.ndarray:
    """Beat tone drifting f0 -> f1 with slow AM, plus static and a faint second voice."""
    rng = np.random.default_rng(seed)
    n = int(round(duration_s * SR))
    t = np.arange(n) / SR
    freq = np.linspace(f0, f1, n)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    am = 0.8 + 0.2 * np.sin(2 * np.pi * 7 * t)
    tone = np.sin(phase) * am * level
    static = rng.standard_normal(n) * level * 0.15
    voice = speech_like(duration_s, seed + 1000, level=level * 0.4, start_s=0.0, end_s=duration_s)
    return (tone + static + voice).astype(np.float32)


def place(total_s: float, clip: np.ndarray, at_s: float) -> np.ndarray:
    out = np.zeros(int(round(total_s * SR)), dtype=np.float32)
    a = int(round(at_s * SR))
    b = min(len(out), a + len(clip))
    out[a:b] += clip[: b - a]
    return out


def clean_call() -> np.ndarray:
    return speech_like(CALL_S, seed=1)


def stepped_on_call() -> np.ndarray:
    pcm = clean_call()
    return pcm + place(CALL_S, heterodyne(OVERLAP_END_S - OVERLAP_START_S, seed=2), OVERLAP_START_S)


def wrong_readback() -> np.ndarray:
    return speech_like(2.4, seed=3)


def correct_readback() -> np.ndarray:
    return speech_like(2.4, seed=4)


CLIPS = {
    "clean_call.wav": clean_call,
    "stepped_on_call.wav": stepped_on_call,
    "wrong_readback.wav": wrong_readback,
    "correct_readback.wav": correct_readback,
}

README = """# Demo clips

Synthetic placeholders made by `python scripts/make_demo_clips.py`. They are not
real speech: "speech" is band-limited noise under syllable envelopes, and the
stepped-on call adds a heterodyne beat tone plus static from 1.3 s to 2.6 s.
They exist to exercise the squelch and overlap detector until real recorded or
Cartesia-generated audio replaces them. STT is tested separately.

| File | What |
| --- | --- |
| `clean_call.wav` | Tower call, ~2.6 s, no overlap |
| `stepped_on_call.wav` | Same call, second carrier overlaps 1.3 s to 2.6 s |
| `wrong_readback.wav` | Pilot readback placeholder (wrong) |
| `correct_readback.wav` | Pilot readback placeholder (correct) |
"""


def make_clips(out_dir: str | Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return {name: write_wav(out_dir / name, fn()) for name, fn in CLIPS.items()}


if __name__ == "__main__":
    out = ROOT / "assets" / "clips"
    for name, path in make_clips(out).items():
        print(f"wrote {path.relative_to(ROOT)}")
    (out / "README.md").write_text(README, encoding="utf-8")
