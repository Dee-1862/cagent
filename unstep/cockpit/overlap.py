"""Streaming overlap detector (task A2): finds the heterodyne squeal of a
stepped-on call and the window it covers, in epoch ms.

Two carriers on one frequency beat against each other and leave a strong,
steady narrowband tone in the audio band. Per frame we look at the last 512
samples, take the share of in-band power held by the strongest peak, and call
the frame "tonal" when that share is high and the peak frequency holds still
from frame to frame. A window opens after `open_frames` tonal frames (start
backdated to the first) and closes after `close_frames` non-tonal frames or
when the squelch closes. Only counts while the squelch is open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np

from unstep.cockpit.audio import SAMPLE_RATE, Frame


@dataclass
class OverlapWindow:
    start: int  # epoch ms
    end: int  # epoch ms

    @property
    def duration_ms(self) -> int:
        return self.end - self.start


class OverlapDetector:
    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        n_fft: int = 512,
        band_hz: tuple[float, float] = (300.0, 3400.0),
        peak_ratio: float = 0.5,
        max_drift_hz: float = 100.0,
        open_frames: int = 3,
        close_frames: int = 3,
    ):
        self.sample_rate = sample_rate
        self.n_fft = n_fft
        self.peak_ratio = peak_ratio
        self.open_frames = open_frames
        self.close_frames = close_frames
        self._window = np.hanning(n_fft).astype(np.float32)
        freqs = np.fft.rfftfreq(n_fft, 1 / sample_rate)
        self._band = np.nonzero((freqs >= band_hz[0]) & (freqs <= band_hz[1]))[0]
        self._bin_hz = sample_rate / n_fft
        self._max_drift_bins = max(1, round(max_drift_hz / self._bin_hz))
        self.reset()

    def reset(self) -> None:
        self._buf = np.zeros(self.n_fft, dtype=np.float32)
        self._prev_peak: Optional[int] = None
        self._hits = 0
        self._misses = 0
        self._run_start: Optional[int] = None
        self._last_hit_end: Optional[int] = None
        self._active = False
        self.last_score = 0.0

    def _score(self) -> tuple[float, int]:
        spec = np.abs(np.fft.rfft(self._buf * self._window)) ** 2
        band = spec[self._band]
        total = float(band.sum())
        if total <= 1e-12:
            return 0.0, -1
        k = int(np.argmax(band))
        peak = float(band[max(0, k - 2) : k + 3].sum())
        return peak / total, k

    def process(self, frame: Frame) -> list[OverlapWindow]:
        """Feed one frame. Returns windows that closed on this frame (usually none)."""
        x = frame.samples
        n = len(x)
        if n >= self.n_fft:
            self._buf[:] = x[-self.n_fft :]
        else:
            self._buf[:-n] = self._buf[n:]
            self._buf[-n:] = x

        if not frame.squelch_open:
            self._prev_peak = None
            self.last_score = 0.0
            return self._close()

        score, peak = self._score()
        self.last_score = score
        steady = self._prev_peak is not None and peak >= 0 and abs(peak - self._prev_peak) <= self._max_drift_bins
        tonal = score >= self.peak_ratio
        self._prev_peak = peak if tonal else None

        if tonal:
            if self._hits == 0:
                self._run_start = frame.ts
            if steady or self._hits == 0:
                self._hits += 1
            else:
                self._hits = 1
                self._run_start = frame.ts
            self._misses = 0
            self._last_hit_end = frame.end_ts
            if not self._active and self._hits >= self.open_frames:
                self._active = True
            return []

        self._misses += 1
        if not self._active:
            self._hits = 0
            return []
        if self._misses >= self.close_frames:
            return self._close()
        return []

    def _close(self) -> list[OverlapWindow]:
        out = []
        if self._active and self._run_start is not None and self._last_hit_end is not None:
            out.append(OverlapWindow(start=self._run_start, end=self._last_hit_end))
        self._active = False
        self._hits = 0
        self._misses = 0
        self._run_start = None
        self._last_hit_end = None
        return out

    def flush(self) -> list[OverlapWindow]:
        """Close any open window at end of stream."""
        return self._close()

    @property
    def active(self) -> bool:
        return self._active


def detect(frames: Iterable[Frame], detector: Optional[OverlapDetector] = None) -> list[OverlapWindow]:
    det = detector or OverlapDetector()
    windows: list[OverlapWindow] = []
    for f in frames:
        windows.extend(det.process(f))
    windows.extend(det.flush())
    return windows
