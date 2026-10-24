"""Streaming overlap detector (task A2): finds the heterodyne squeal of a
stepped-on call and the window it covers, in epoch ms.

Two carriers on one frequency beat against each other and leave a narrowband
tone in the audio band that is present in every frame and drifts only slowly.
Speech also has narrowband lines (pitch harmonics), but they glide with
intonation and vanish at every consonant and pause.

Per 20 ms frame we take the last 512 samples, compute the log power spectrum
and subtract a running local median across frequency (about +-330 Hz), which
gives each bin's prominence in dB over its neighbourhood. Each frame's
prominence is max-pooled over a few neighbouring bins (so a slow drift stays
in the same pooled bin) and kept in a ring of the last `persist_frames`
frames (300 ms). The persistence score is the best bin's *minimum* over that
ring: it is high only when one line stood out in every frame for 300 ms.

A frame is a hit when that score is at least `prominence_db`. A window opens
after `open_frames` consecutive hits, its start backdated by the persistence
span (the tone had to be there all along), and closes after `close_frames`
misses or when the squelch closes. Windows shorter than `min_window_ms` are
dropped. Only counts while the squelch is open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
from scipy.ndimage import maximum_filter1d, median_filter

from unstep.cockpit.audio import FRAME_MS, SAMPLE_RATE, Frame

_FLOOR_DB = -200.0


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
        band_hz: tuple[float, float] = (500.0, 3400.0),
        prominence_db: float = 12.0,
        persist_frames: int = 15,
        median_bins: int = 21,
        pool_bins: int = 5,
        open_frames: int = 5,
        close_frames: int = 5,
        min_window_ms: int = 300,
        frame_ms: int = FRAME_MS,
    ):
        self.sample_rate = sample_rate
        self.n_fft = n_fft
        self.prominence_db = prominence_db
        self.persist_frames = persist_frames
        self.median_bins = median_bins
        self.pool_bins = pool_bins
        self.open_frames = open_frames
        self.close_frames = close_frames
        self.min_window_ms = min_window_ms
        self.frame_ms = frame_ms
        self._window = np.hanning(n_fft).astype(np.float32)
        freqs = np.fft.rfftfreq(n_fft, 1 / sample_rate)
        self._band = np.nonzero((freqs >= band_hz[0]) & (freqs <= band_hz[1]))[0]
        self._freqs = freqs[self._band]
        self.reset()

    def reset(self) -> None:
        self._buf = np.zeros(self.n_fft, dtype=np.float32)
        self._ring = np.full((self.persist_frames, len(self._band)), _FLOOR_DB, dtype=np.float32)
        self._ring_i = 0
        self._hits = 0
        self._misses = 0
        self._run_start: Optional[int] = None
        self._last_hit_end: Optional[int] = None
        self._active = False
        self.last_score = 0.0
        self.last_peak_hz = 0.0

    def _prominence(self) -> np.ndarray:
        spec = np.abs(np.fft.rfft(self._buf * self._window)) ** 2
        logp = 10 * np.log10(spec + 1e-12)
        # Median over the full spectrum so band edges see real neighbours.
        prom = logp - median_filter(logp, self.median_bins, mode="nearest")
        return maximum_filter1d(prom[self._band], self.pool_bins).astype(np.float32)

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
            self._ring.fill(_FLOOR_DB)
            self.last_score = 0.0
            return self._close()

        self._ring[self._ring_i] = self._prominence()
        self._ring_i = (self._ring_i + 1) % self.persist_frames
        persist = self._ring.min(axis=0)
        k = int(np.argmax(persist))
        self.last_score = float(persist[k])
        self.last_peak_hz = float(self._freqs[k])

        if self.last_score >= self.prominence_db:
            if self._hits == 0 and not self._active:
                # The line had to be present for the whole persistence span.
                span = (self.persist_frames - 1) * (frame.end_ts - frame.ts or self.frame_ms)
                self._run_start = frame.ts - span
            self._hits += 1
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
            w = OverlapWindow(start=self._run_start, end=self._last_hit_end)
            if w.duration_ms >= self.min_window_ms:
                out.append(w)
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
