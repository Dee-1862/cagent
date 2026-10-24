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
from scipy.signal import butter, resample_poly, sosfilt

from unstep.cockpit.audio import FRAME_MS, SAMPLE_RATE

TAIL_MS = 400  # silence after a cluster so the squelch closes
# AM receiver model for two carriers keyed at once (same shape as scripts/make_real_clips.py):
# similar-strength voices garble each other and the carriers beat into a drifting tone.
OVERLAP_VOICE_GAIN = 0.5
BEAT_LEVEL = 0.35
BEAT_F0, BEAT_F1 = 1600.0, 1900.0
RAMP_MS = 20


# What people in the room hear: an aircraft VHF voice channel, about 300 to 3400 Hz, with a
# little hiss while the carrier is up and a short squelch tail at the end. Only for the
# audio sent to listeners; STT and the overlap detector get the clean mix. Unstep's own
# private voice is never shaped, so it can't be mistaken for a radio call.
RADIO_BAND_HZ = (300.0, 3400.0)
RADIO_HISS = 0.012
SQUELCH_TAIL_MS = 90
_RADIO_SOS = butter(4, RADIO_BAND_HZ, btype="bandpass", fs=SAMPLE_RATE, output="sos")


def radio_voice(pcm: np.ndarray, seed: int | None = 0) -> np.ndarray:
    """Clean 16 kHz float mono -> how it sounds on the frequency (band-limited, hiss, squelch tail)."""
    x = np.asarray(pcm, dtype=np.float32)
    if not len(x):
        return x
    rng = np.random.default_rng(seed)
    y = sosfilt(_RADIO_SOS, x).astype(np.float32)
    y = np.tanh(1.6 * y) / np.tanh(1.6)  # mild clipping, like a speech-processed transmitter
    y += (RADIO_HISS * rng.standard_normal(len(y))).astype(np.float32)
    tail = int(SAMPLE_RATE * SQUELCH_TAIL_MS / 1000)
    burst = (2.5 * RADIO_HISS * rng.standard_normal(tail) * np.linspace(1, 0, tail)).astype(np.float32)
    peak = float(np.max(np.abs(x))) or 1.0
    y *= min(1.0, peak / (float(np.max(np.abs(y))) or 1.0))  # never louder than the clean clip
    return np.clip(np.concatenate([y, burst]), -1.0, 1.0)


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


class LiveMix:
    """The frequency as it sounds while transmissions are still on air (R27 3a).

    `mix()` needs the whole cluster, so the cockpits used to start transcribing only after the
    last key came up. LiveMix sums the transmissions as their audio arrives (typed lines all
    at once, push-to-talk frame by frame) so each cockpit's speech-to-text can be fed while the
    call is still on the air and finalized when the cluster ends. Where two or more stations
    are keyed it applies the same receiver model as `mix()` (voices at half gain plus a beat
    tone), with the tone generated continuously because the overlap's length isn't known yet.
    """

    def __init__(self, t0: int):
        self.t0 = t0
        self.cursor = 0  # samples already pulled
        self.parts: dict[str, dict] = {}  # key -> {station, start, chunks, n, end_ms}
        self._phase = 0.0
        self._rng = np.random.default_rng(t0 % (2**32))

    def add(self, key: str, station: str, start_ms: int, samples: np.ndarray) -> None:
        start = round((start_ms - self.t0) * SAMPLE_RATE / 1000)
        part = self.parts.setdefault(key, {"station": station, "start": max(0, start), "skip": max(0, -start),
                                           "chunks": [], "n": 0, "end": None})
        samples = np.asarray(samples, dtype=np.float32)
        if part["skip"]:  # started before the mix did (clock jitter): drop what lies before t0
            cut = min(part["skip"], len(samples))
            samples, part["skip"] = samples[cut:], part["skip"] - cut
        part["chunks"].append(samples)
        part["n"] += len(samples)

    def close(self, key: str) -> None:
        part = self.parts.get(key)
        if part is not None:
            part["end"] = part["start"] + part["n"]

    def drop(self, key: str) -> None:
        """A tap, not a call: it never went on air."""
        self.parts.pop(key, None)

    @property
    def stations(self) -> set[str]:
        return {p["station"] for p in self.parts.values()}

    def available(self) -> int:
        """Samples that can be mixed for sure: open parts limit how far we can go."""
        ends = [p["start"] + p["n"] for p in self.parts.values() if p["end"] is None]
        closed = [p["end"] for p in self.parts.values() if p["end"] is not None]
        return min(ends) if ends else max(closed, default=0)

    def pull(self, until_ms: int | None = None) -> np.ndarray:
        """Mixed audio from the last pull up to `until_ms` (or as far as is known)."""
        stop = self.available()
        if until_ms is not None:
            stop = min(stop, round((until_ms - self.t0) * SAMPLE_RATE / 1000))
        if stop <= self.cursor:
            return np.zeros(0, dtype=np.float32)
        a, b = self.cursor, stop
        out = np.zeros(b - a, dtype=np.float32)
        active = np.zeros(b - a, dtype=np.int8)
        for p in self.parts.values():
            data = np.concatenate(p["chunks"]) if len(p["chunks"]) > 1 else (p["chunks"][0] if p["chunks"] else np.zeros(0))
            p["chunks"] = [data] if len(data) else []
            lo, hi = max(a, p["start"]), min(b, p["start"] + len(data))
            if hi > lo:
                out[lo - a:hi - a] += data[lo - p["start"]:hi - p["start"]]
                active[lo - a:hi - a] += 1
        both = active >= 2
        if both.any():
            n = int(both.sum())
            f = BEAT_F0 + (BEAT_F1 - BEAT_F0) * (0.5 + 0.5 * np.sin(np.arange(n) / SAMPLE_RATE * 0.5))
            phase = self._phase + 2 * np.pi * np.cumsum(f) / SAMPLE_RATE
            self._phase = float(phase[-1] % (2 * np.pi))
            tone = np.sin(phase) * BEAT_LEVEL + self._rng.standard_normal(n) * BEAT_LEVEL * 0.15
            out[both] = out[both] * OVERLAP_VOICE_GAIN + tone.astype(np.float32)
        self.cursor = b
        return np.clip(out, -1.0, 1.0)
