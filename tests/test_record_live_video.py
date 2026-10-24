"""R24 video recorder: the parts that run without a browser (layout, audio placement)."""

import base64
import importlib.util
import io
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("record_live_video", ROOT / "scripts" / "record_live_video.py")
rec = importlib.util.module_from_spec(spec)
sys.modules["record_live_video"] = rec
spec.loader.exec_module(rec)


def wav_b64(n=1600, rate=16000):
    buf = io.BytesIO()
    sf.write(buf, np.zeros(n, dtype=np.int16), rate, format="WAV", subtype="PCM_16")
    return base64.b64encode(buf.getvalue()).decode()


def test_layout_has_the_console_and_two_phones_with_the_token():
    html = rec.layout_html(9999, "room code")
    assert 'id="atc" src="http://127.0.0.1:9999/live/atc/?token=room%20code"' in html
    assert "#/fly/N123AB" in html and "#/fly/H456" in html


def test_audio_plan_keeps_each_radio_clip_once_and_joins_advisory_chunks():
    pcm = np.arange(10, dtype="<i2").tobytes()
    events = [
        {"kind": "radio", "id": "tx-1", "t": 1500, "wav": wav_b64()},
        {"kind": "radio", "id": "tx-1", "t": 1502, "wav": wav_b64()},  # heard in a second frame
        {"kind": "chunk", "id": "ctx", "seq": 1, "t": 2100, "rate": 24000, "pcm": base64.b64encode(pcm[10:]).decode()},
        {"kind": "chunk", "id": "ctx", "seq": 0, "t": 2000, "rate": 24000, "pcm": base64.b64encode(pcm[:10]).decode()},
        {"kind": "recovery", "id": "recovery-1", "t": 900, "wav": wav_b64()},
    ]
    plan = rec.audio_plan(events, t0_ms=1000)
    assert [d for d, _ in plan] == [0, 500, 1000]
    joined, rate = sf.read(io.BytesIO(plan[2][1]), dtype="int16")
    assert rate == 24000 and list(joined) == list(range(10))
