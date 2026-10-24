"""R17 e: people in the room hear transmissions as VHF radio; STT and the detector get the clean mix."""

import asyncio
import base64
import io

import numpy as np
import soundfile as sf

from unstep import config
from unstep.cockpit.audio import SAMPLE_RATE
from unstep.live.radio import SQUELCH_TAIL_MS, radio_voice

from tests.test_live_room import make_room  # noqa: F401 (fixture)


def tone(hz, s=0.5, amp=0.5):
    t = np.arange(int(SAMPLE_RATE * s)) / SAMPLE_RATE
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def level(x, hz):
    spectrum = np.abs(np.fft.rfft(x[: int(SAMPLE_RATE * 0.5)]))
    freqs = np.fft.rfftfreq(int(SAMPLE_RATE * 0.5), 1 / SAMPLE_RATE)
    return spectrum[np.argmin(np.abs(freqs - hz))]


def test_band_limits_like_vhf_and_adds_a_squelch_tail():
    clean = tone(100) + tone(1000) + tone(6000)
    radio = radio_voice(clean)
    assert len(radio) == len(clean) + SAMPLE_RATE * SQUELCH_TAIL_MS // 1000
    keep = level(radio, 1000) / level(clean, 1000)
    assert keep > 0.3
    assert level(radio, 100) / level(clean, 100) < keep / 5
    assert level(radio, 6000) / level(clean, 6000) < keep / 5
    assert np.max(np.abs(radio[: len(clean)])) <= np.max(np.abs(clean)) + 1e-6
    assert radio_voice(np.zeros(0, dtype=np.float32)).size == 0


def test_listeners_get_radio_audio_and_the_switch_turns_it_off(make_room, monkeypatch):
    async def go():
        room, atc, pilot = await make_room()
        tx = await room.say("atc", "Cessna one two three, hold short runway three three")
        await asyncio.sleep(0.05)
        onair = next(m for m in pilot.messages if m["type"] == "onair")
        heard, _ = sf.read(io.BytesIO(base64.b64decode(onair["audio"])), dtype="float32")
        assert onair["radio"] is True and len(heard) > len(tx.pcm)  # shaped, with a tail
        assert len(tx.pcm) == round((tx.end_ms - tx.start_ms) * SAMPLE_RATE / 1000)  # the mix stays clean
        await room.stop()

    asyncio.run(go())
    monkeypatch.setenv("UNSTEP_RADIO_SOUND", "0")
    assert config.radio_sound() is False
