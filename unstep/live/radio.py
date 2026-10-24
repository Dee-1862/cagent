"""The shared virtual frequency for the live room (docs/11-live-demo.md).

Every transmission is a clip with a start time on the gateway clock. Clips whose
times overlap form one cluster: the room mixes the cluster the way a real VHF
receiver would hear it and records exactly which stations were keyed in every
frame, so the "radio truth" of an overlap is known and can be compared with
what the cockpit's overlap detector found.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from math import gcd

import numpy as np
from scipy.signal import resample_poly

from unstep.cockpit.audio import FRAME_MS, SAMPLE_RATE

TAIL_MS = 400  # silence after a cluster so the squelch closes
# AM receiver model for two carriers keyed at once (same shape as scripts/make_real_clips.py):
# similar-strength voices garble each other and the carriers beat into a drifting tone.
OVERLAP_VOICE_GAIN = 0.5
BEAT_LEVEL = 0.35
BEAT_F0, BEAT_F1 = 1600.0, 1900.0
RAMP_MS = 20


@dataclass
class Transmission:
    station: str
    start_ms: int
    pcm: np.ndarray  # float32 mono at SAMPLE_RATE
    text: str | None = None  # known words (say box); None for microphone audio
    words: list[tuple[str, float, float]] = field(default_factory=list)  # (word, start s, end s)
    tx_id: str = field(default_factory=lambda: f"tx-{uuid.uuid4().hex[:10]}")

    @property
    def end_ms(self) -> int:
        return self.start_ms + round(len(self.pcm) * 1000 / SAMPLE_RATE)


@dataclass
class Overlap:
    start_ms: int
    end_ms: int
    stations: list[str]


@dataclass
class Mix:
    t0: int
    pcm: np.ndarray
    keyed: list[set[str]]  # stations keyed in each FRAME_MS frame
    overlaps: list[Overlap]
    transmissions: list[Transmission]

    @property
    def any_keyed(self) -> list[bool]:
        return [bool(k) for k in self.keyed]

    def heard_by(self, station: str) -> bool:
        """Half duplex: a station that was transmitting hears nothing."""
        return all(t.station != station for t in self.transmissions)


def to_mono16k(pcm16: bytes | np.ndarray, sample_rate: int) -> np.ndarray:
    """int16 bytes or float array at any rate to float32 mono at SAMPLE_RATE."""
    samples = (np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
               if isinstance(pcm16, (bytes, bytearray)) else np.asarray(pcm16, dtype=np.float32))
    if sample_rate != SAMPLE_RATE:
        g = gcd(sample_rate, SAMPLE_RATE)
        samples = resample_poly(samples, SAMPLE_RATE // g, sample_rate // g).astype(np.float32)
    return samples


def clusters(transmissions: list[Transmission]) -> list[list[Transmission]]:
    """Group transmissions whose time ranges overlap."""
    out: list[list[Transmission]] = []
    end = None
    for tx in sorted(transmissions, key=lambda t: t.start_ms):
        if out and end is not None and tx.start_ms < end:
            out[-1].append(tx)
            end = max(end, tx.end_ms)
        else:
            out.append([tx])
            end = tx.end_ms
    return out


def mix(cluster: list[Transmission], frame_ms: int = FRAME_MS, tail_ms: int = TAIL_MS) -> Mix:
    t0 = min(t.start_ms for t in cluster)
    end = max(t.end_ms for t in cluster) + tail_ms
    n = round((end - t0) * SAMPLE_RATE / 1000)
    pcm = np.zeros(n, dtype=np.float32)
    frames = -(-n // (SAMPLE_RATE * frame_ms // 1000))
    keyed: list[set[str]] = [set() for _ in range(frames)]
    for tx in cluster:
        offset = round((tx.start_ms - t0) * SAMPLE_RATE / 1000)
        pcm[offset:offset + len(tx.pcm)] += tx.pcm[: max(0, n - offset)]
        first = (tx.start_ms - t0) // frame_ms
        last = -(-(tx.end_ms - t0) // frame_ms)
        for i in range(first, min(last, frames)):
            keyed[i].add(tx.station)
    overlaps = _overlaps(keyed, t0, frame_ms)
    for o in overlaps:
        a = round((o.start_ms - t0) * SAMPLE_RATE / 1000)
        b = min(n, round((o.end_ms - t0) * SAMPLE_RATE / 1000))
        if b > a:
            pcm[a:b] = pcm[a:b] * OVERLAP_VOICE_GAIN + beat_tone(b - a, seed=o.start_ms)
    np.clip(pcm, -1.0, 1.0, out=pcm)
    return Mix(t0, pcm, keyed, overlaps, list(cluster))


def beat_tone(n: int, seed: int = 0) -> np.ndarray:
    """Two carriers beating: a drifting tone with slow AM, light static and soft edges."""
    t = np.arange(n) / SAMPLE_RATE
    phase = 2 * np.pi * np.cumsum(np.linspace(BEAT_F0, BEAT_F1, n)) / SAMPLE_RATE
    am = 0.8 + 0.2 * np.sin(2 * np.pi * 7 * t)
    static = np.random.default_rng(seed % (2**32)).standard_normal(n) * BEAT_LEVEL * 0.15
    out = (np.sin(phase) * am * BEAT_LEVEL + static).astype(np.float32)
    ramp = min(n // 2, SAMPLE_RATE * RAMP_MS // 1000)
    if ramp:
        out[:ramp] *= np.linspace(0, 1, ramp, dtype=np.float32)
        out[-ramp:] *= np.linspace(1, 0, ramp, dtype=np.float32)
    return out


def _overlaps(keyed: list[set[str]], t0: int, frame_ms: int) -> list[Overlap]:
    out: list[Overlap] = []
    for i, stations in enumerate(keyed):
        if len(stations) < 2:
            continue
        start = t0 + i * frame_ms
        if out and out[-1].end_ms == start:
            out[-1].end_ms = start + frame_ms
            out[-1].stations = sorted(set(out[-1].stations) | stations)
        else:
            out.append(Overlap(start, start + frame_ms, sorted(stations)))
    return out


class KeyedSquelch:
    """Opens while any station is keyed, as a receiver opens on a carrier.

    Matches the SimulatedSquelch interface (update per frame, reset), so the
    cockpit agent splits transmissions on the real push-to-talk timing.
    """

    def __init__(self, keyed: list[bool]):
        self.keyed = keyed
        self._i = 0
        self.is_open = False

    def update(self, samples: np.ndarray) -> bool:
        self.is_open = self._i < len(self.keyed) and self.keyed[self._i]
        self._i += 1
        return self.is_open

    def reset(self) -> None:
        self._i = 0
        self.is_open = False


def heard_text(tower: Transmission, overlaps: list[Overlap]) -> str:
    """What a cockpit hears of a tower call: the words before the first overlap, then static."""
    if not tower.text:
        return ""
    if not overlaps:
        return tower.text
    cut = (overlaps[0].start_ms - tower.start_ms) / 1000
    if tower.words:
        kept = [w for w, start, _ in tower.words if start < cut]
    else:
        words = tower.text.split()
        per_word = (tower.end_ms - tower.start_ms) / 1000 / max(1, len(words))
        kept = words[: max(0, int(cut / per_word))]
    return " ".join(kept + ["[static]"])
