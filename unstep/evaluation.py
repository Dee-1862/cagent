"""Evaluation helpers: statistics with honest error bars, and the radio channel used in the benchmark.

- `wilson(k, n)`: 95% Wilson score interval for a proportion (works at 0 and n, unlike the normal one).
- `wer(ref, hyp)` and `bootstrap_wer(pairs)`: word error rate over normalized words, and a seeded
  bootstrap 95% interval over utterances.
- `pct(values, q)`: nearest-rank percentile.
- `through_radio(pcm, snr_db, seed)`: a clean 16 kHz line through our VHF voice channel
  (unstep.live.radio.radio_voice: 300 to 3400 Hz, mild clipping, hiss, squelch tail) plus white
  noise at the given SNR. The same channel the live room plays to listeners.
- `stepped_on(a, b, offset_s)`: two lines mixed the way the live room mixes a cluster (AM beat
  tone in the overlap), with the overlap window as ground truth.
"""

from __future__ import annotations

import math
import random
import re

import numpy as np

from unstep.cockpit.audio import SAMPLE_RATE
from unstep.cockpit.phraseology import _digit_tokens, _tokens

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def proportion(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "value": round(k / n, 4) if n else None, "ci95": [lo, hi]}


def words(text: str) -> list[str]:
    """Lowercase words with spoken digits as digits, so "three three" and "33" compare equal."""
    out: list[str] = []
    for t in _digit_tokens(_tokens(text)):
        if t.isdigit() and len(t) > 1:
            out.extend(t)  # "33" -> "3", "3"
        else:
            out.append(t)
    return out


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str) -> tuple[int, int]:
    """(word errors, reference words)."""
    r, h = words(ref), words(hyp)
    return edit_distance(r, h), len(r)


def bootstrap_wer(pairs: list[tuple[int, int]], iters: int = 1000, seed: int = 7) -> dict:
    """Corpus WER (sum errors / sum words) with a 95% bootstrap interval over utterances."""
    if not pairs:
        return {"value": None, "ci95": [None, None], "n": 0}
    total = sum(e for e, _ in pairs) / max(1, sum(w for _, w in pairs))
    rng = random.Random(seed)
    stats = []
    for _ in range(iters):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        stats.append(sum(e for e, _ in sample) / max(1, sum(w for _, w in sample)))
    stats.sort()
    return {"value": round(total, 4), "ci95": [round(stats[int(0.025 * iters)], 4), round(stats[int(0.975 * iters) - 1], 4)],
            "n": len(pairs)}


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def add_noise(x: np.ndarray, snr_db: float, seed: int = 0) -> np.ndarray:
    """White noise at `snr_db` relative to the signal's RMS over its non-silent part."""
    x = np.asarray(x, dtype=np.float32)
    voiced = x[np.abs(x) > 1e-3]
    power = float(np.mean(voiced ** 2)) if voiced.size else 0.0
    if power == 0.0:
        return x
    noise = np.random.default_rng(seed).standard_normal(len(x)).astype(np.float32)
    noise *= math.sqrt(power / (10 ** (snr_db / 10)))
    return np.clip(x + noise, -1.0, 1.0)


def through_radio(pcm: np.ndarray, snr_db: float | None, seed: int = 0) -> np.ndarray:
    from unstep.live.radio import radio_voice

    y = radio_voice(pcm, seed=seed)
    return y if snr_db is None else add_noise(y, snr_db, seed=seed + 1)


def stepped_on(a: np.ndarray, b: np.ndarray, offset_s: float, t0: int = 1_000_000) -> tuple[np.ndarray, tuple[int, int] | None]:
    """Line `a` with line `b` keyed `offset_s` later, mixed like the live room. Returns (pcm, overlap ms window)."""
    from unstep.live.radio import Transmission, mix

    ta = Transmission("a", t0, np.asarray(a, dtype=np.float32))
    tb = Transmission("b", t0 + int(offset_s * 1000), np.asarray(b, dtype=np.float32))
    m = mix([ta, tb])
    window = (m.overlaps[0].start_ms, m.overlaps[0].end_ms) if m.overlaps else None
    return m.pcm, window


def detect_overlap(pcm: np.ndarray, t0: int = 1_000_000) -> list[tuple[int, int]]:
    """The cockpit's audio-only overlap detector on a whole line (squelch from loudness)."""
    from unstep.cockpit.audio import ArraySource
    from unstep.cockpit.overlap import detect

    return [(w.start, w.end) for w in detect(ArraySource(pcm, t0=t0))]


def iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union > 0 else 0.0


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
