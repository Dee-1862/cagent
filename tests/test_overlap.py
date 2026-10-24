"""Tasks A1 and A2: synthetic clips, simulated squelch and the streaming overlap
detector. Clips are generated into a tmp dir so the tests never depend on
committed assets.
"""

import time
from pathlib import Path

import numpy as np
import pytest

from scripts import make_demo_clips as clips
from unstep.cockpit.audio import SAMPLE_RATE, ArraySource, SimulatedSquelch, WavFileSource, read_wav
from unstep.cockpit.overlap import OverlapDetector, detect

T0 = 1_792_800_000_000
TOL_MS = 150


@pytest.fixture(scope="module")
def clip_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("clips")
    clips.make_clips(out)
    return out


def windows_for(path, **kw):
    return detect(WavFileSource(path, t0=T0, **kw))


def test_clips_are_written_and_deterministic(clip_dir):
    for name in clips.CLIPS:
        pcm = read_wav(clip_dir / name)
        assert pcm.dtype == np.float32 and len(pcm) > SAMPLE_RATE
    np.testing.assert_array_equal(clips.stepped_on_call(), clips.stepped_on_call())
    assert not np.array_equal(clips.wrong_readback(), clips.correct_readback())


def test_frames_have_timestamps_and_fixed_size(clip_dir):
    frames = list(WavFileSource(clip_dir / "clean_call.wav", t0=T0))
    assert all(len(f.samples) == 320 and f.samples.dtype == np.float32 for f in frames)
    assert [f.ts for f in frames[:3]] == [T0, T0 + 20, T0 + 40]
    assert frames[0].end_ts == T0 + 20


def test_squelch_opens_on_signal_and_closes_after_hangover():
    pcm = np.concatenate([np.zeros(3200), clips.speech_like(1.0, seed=9), np.zeros(16000)]).astype(np.float32)
    frames = list(ArraySource(pcm, t0=T0, squelch=SimulatedSquelch(hangover_ms=200)))
    opened = [f.ts - T0 for f in frames if f.squelch_open]
    assert 200 <= opened[0] <= 350
    assert 1200 <= opened[-1] <= 1350 + 200
    assert not frames[-1].squelch_open


def test_stepped_on_call_flags_overlap_window(clip_dir):
    windows = windows_for(clip_dir / "stepped_on_call.wav")
    assert len(windows) == 1
    w = windows[0]
    assert abs(w.start - (T0 + 1300)) <= TOL_MS
    assert abs(w.end - (T0 + 2600)) <= TOL_MS


@pytest.mark.parametrize("name", ["clean_call.wav", "wrong_readback.wav", "correct_readback.wav"])
def test_no_overlap_on_clean_clips(clip_dir, name):
    assert windows_for(clip_dir / name) == []


def test_silence_only():
    frames = list(ArraySource(np.zeros(SAMPLE_RATE * 2, dtype=np.float32), t0=T0))
    assert not any(f.squelch_open for f in frames)
    assert detect(frames) == []


def test_squelch_never_opens_ignores_tone():
    pcm = clips.stepped_on_call()
    frames = list(ArraySource(pcm, t0=T0, squelch=SimulatedSquelch(threshold_db=10.0)))
    assert not any(f.squelch_open for f in frames)
    assert detect(frames) == []


def test_overlap_at_very_start():
    pcm = clips.speech_like(2.6, seed=11) + clips.place(2.6, clips.heterodyne(1.0, seed=12), 0.0)
    windows = detect(ArraySource(pcm, t0=T0))
    assert len(windows) == 1
    assert abs(windows[0].start - T0) <= TOL_MS
    assert abs(windows[0].end - (T0 + 1000)) <= TOL_MS


def test_overlap_continuing_to_end_of_clip():
    pcm = clips.speech_like(2.0, seed=13) + clips.place(2.0, clips.heterodyne(1.0, seed=14), 1.0)
    det = OverlapDetector()
    closed = []
    for f in ArraySource(pcm, t0=T0):
        closed.extend(det.process(f))
    assert closed == [] and det.active
    windows = det.flush()
    assert len(windows) == 1
    assert abs(windows[0].start - (T0 + 1000)) <= TOL_MS
    assert abs(windows[0].end - (T0 + 2000)) <= TOL_MS


def test_per_frame_time_under_10ms(clip_dir):
    frames = list(WavFileSource(clip_dir / "stepped_on_call.wav", t0=T0))
    det = OverlapDetector()
    for f in frames[:5]:
        det.process(f)
    det.reset()
    started = time.perf_counter()
    for f in frames:
        det.process(f)
    mean_ms = (time.perf_counter() - started) * 1000 / len(frames)
    print(f"overlap detector: {mean_ms:.3f} ms per 20 ms frame")
    assert mean_ms < 10


# Real speech (Cartesia TTS, made by scripts/make_real_clips.py). The tower call
# in stepped_on_call.wav has a second voice and a beat tone from 1.3 s to the end.
REAL = Path(__file__).resolve().parent.parent / "assets" / "clips" / "real"
REAL_TOL_MS = 250


def _real(name):
    path = REAL / name
    if not path.exists():
        pytest.skip(f"missing {path}")
    return path


def test_real_stepped_on_call_flags_one_window():
    path = _real("stepped_on_call.wav")
    frames = list(WavFileSource(path, t0=T0))
    windows = detect(frames)
    assert len(windows) == 1
    w = windows[0]
    assert abs(w.start - (T0 + 1300)) <= REAL_TOL_MS
    assert abs(w.end - frames[-1].end_ts) <= REAL_TOL_MS


@pytest.mark.parametrize(
    "name",
    ["clean_call.wav", "wrong_readback.wav", "correct_readback.wav", "pilot_question.wav",
     "helicopter_call.wav", "smoke_advisory.wav"],
)
def test_no_overlap_on_real_clean_speech(name):
    assert windows_for(_real(name)) == []
