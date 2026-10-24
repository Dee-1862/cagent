"""Cockpit audio input (task A1): fixed-size mono float32 frames at 16 kHz with
epoch ms timestamps and a squelch state.

`WavFileSource` plays a recorded or generated clip. Squelch is simulated from
signal energy with hangover, since the laptop has no real receiver. Only numpy,
scipy and soundfile, so it runs on the Pi too.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import gcd
from pathlib import Path
from typing import Iterator, Optional

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from unstep.clock import now_ms

SAMPLE_RATE = 16_000
FRAME_MS = 20


@dataclass
class Frame:
    samples: np.ndarray  # float32 mono, length = frame size
    ts: int  # epoch ms of the first sample
    squelch_open: bool
    index: int = 0

    @property
    def end_ts(self) -> int:
        return self.ts + round(len(self.samples) * 1000 / SAMPLE_RATE)


class SimulatedSquelch:
    """Opens when frame RMS (dBFS) is above `threshold_db`, closes after `hangover_ms` below it."""

    def __init__(self, threshold_db: float = -45.0, hangover_ms: int = 200, frame_ms: int = FRAME_MS):
        self.threshold_db = threshold_db
        self.hangover_frames = max(0, round(hangover_ms / frame_ms))
        self.is_open = False
        self._quiet = 0

    def update(self, samples: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))) if len(samples) else 0.0
        db = 20 * np.log10(rms + 1e-12)
        if db >= self.threshold_db:
            self.is_open = True
            self._quiet = 0
        elif self.is_open:
            self._quiet += 1
            if self._quiet > self.hangover_frames:
                self.is_open = False
        return self.is_open

    def reset(self) -> None:
        self.is_open = False
        self._quiet = 0


class AudioSource(ABC):
    sample_rate: int = SAMPLE_RATE
    frame_ms: int = FRAME_MS

    @property
    def frame_size(self) -> int:
        return self.sample_rate * self.frame_ms // 1000

    @abstractmethod
    def __iter__(self) -> Iterator[Frame]: ...


class ArraySource(AudioSource):
    """Frames from a PCM array already in memory (16 kHz mono)."""

    def __init__(
        self,
        pcm: np.ndarray,
        t0: Optional[int] = None,
        frame_ms: int = FRAME_MS,
        squelch: Optional[SimulatedSquelch] = None,
    ):
        self.pcm = np.asarray(pcm, dtype=np.float32)
        self.t0 = t0
        self.frame_ms = frame_ms
        self.squelch = squelch or SimulatedSquelch(frame_ms=frame_ms)

    def __iter__(self) -> Iterator[Frame]:
        t0 = now_ms() if self.t0 is None else self.t0
        n = self.frame_size
        self.squelch.reset()
        for i, start in enumerate(range(0, len(self.pcm), n)):
            chunk = self.pcm[start : start + n]
            if len(chunk) < n:
                chunk = np.pad(chunk, (0, n - len(chunk)))
            yield Frame(
                samples=chunk,
                ts=t0 + i * self.frame_ms,
                squelch_open=self.squelch.update(chunk),
                index=i,
            )


class WavFileSource(ArraySource):
    """Frames from a WAV file, downmixed and resampled to 16 kHz."""

    def __init__(self, path: str | Path, t0: Optional[int] = None, frame_ms: int = FRAME_MS,
                 squelch: Optional[SimulatedSquelch] = None):
        self.path = Path(path)
        super().__init__(read_wav(self.path), t0=t0, frame_ms=frame_ms, squelch=squelch)


def read_wav(path: str | Path) -> np.ndarray:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    pcm = data.mean(axis=1)
    if sr != SAMPLE_RATE:
        g = gcd(sr, SAMPLE_RATE)
        pcm = resample_poly(pcm, SAMPLE_RATE // g, sr // g).astype(np.float32)
    return pcm


def write_wav(path: str | Path, pcm: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(np.asarray(pcm, dtype=np.float32), -1.0, 1.0), sample_rate, subtype="PCM_16")
    return path
