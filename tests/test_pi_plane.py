"""The Raspberry Pi plane client: joins the hub as a pilot, talks from a WAV, hears the room."""

import asyncio
import os
import socket
import subprocess
import sys
import time
import wave

import pytest

from unstep.config import ROOT
from scripts import pi_plane

CLIP = ROOT / "assets" / "clips" / "real" / "clean_call.wav"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_socket_url_follows_the_hubs_scheme_and_carries_the_room_code():
    assert pi_plane.socket_url("http://192.168.2.53:8765/", "N123AB", None) == "ws://192.168.2.53:8765/live/ws/N123AB"
    assert pi_plane.socket_url("https://unstep.onrender.com", "H456", "a b") == \
        "wss://unstep.onrender.com/live/ws/H456?token=a+b"


def test_a_wav_is_cut_into_100_ms_frames_and_wrong_formats_are_refused(tmp_path):
    frames = list(pi_plane.wav_frames(str(CLIP)))
    assert all(len(f) == pi_plane.FRAME_BYTES for f in frames[:-1]) and 30 < len(frames) < 50
    bad = tmp_path / "stereo.wav"
    with wave.open(str(bad), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(44100), w.writeframes(b"\0" * 400)
    with pytest.raises(SystemExit, match="16 kHz, mono, 16-bit"):
        list(pi_plane.wav_frames(str(bad)))


def test_the_pi_joins_a_real_hub_and_its_call_reaches_the_radio():
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("CARTESIA_API_KEY", None)
    env.pop("UNSTEP_GATEWAY_TOKEN", None)
    proc = subprocess.Popen([sys.executable, "-m", "unstep.live", "--offline", "--no-browser", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        import httpx

        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        args = pi_plane.parse(["--hub", f"http://127.0.0.1:{port}", "--wav", str(CLIP), "--fast",
                               "--listen", "6", "--no-sound"])
        result = asyncio.run(pi_plane.run(args))
    finally:
        proc.terminate()
        proc.wait(10)
    assert result["station"] in ("N123AB", "H456") and result["frames_sent"] == 40
    assert "hello" in result["heard"]
    assert result["heard"].count("keyed") >= 2  # key down and key up
    assert result["heard"].count("level") == 40  # the hub metered every 100 ms frame
    assert "radio" in result["heard"]  # the call went out on the shared frequency
    assert abs(result["offset_ms"]) < 1000  # same machine: the clocks agree


def _tone(amplitude, n=1600):
    import array
    import math

    return array.array("h", [int(amplitude * math.sin(i / 5)) for i in range(n)]).tobytes()


def test_the_meter_shows_silence_speech_and_clipping():
    quiet_db, quiet_peak = pi_plane.level(b"\0" * pi_plane.FRAME_BYTES)
    assert quiet_db == -90.0 and quiet_peak == 0
    assert "no sound at all" in pi_plane.meter("Listening", quiet_db, quiet_peak)
    db, peak = pi_plane.level(_tone(8000))
    assert -25 < db < -8 and peak > 7000
    line = pi_plane.meter("ON AIR", db, peak)
    assert line.startswith("ON AIR") and "#" in line and "CLIPPING" not in line and "no sound" not in line
    loud_db, loud_peak = pi_plane.level(_tone(32767))
    assert "CLIPPING" in pi_plane.meter("Listening", loud_db, loud_peak)
    assert pi_plane.level(b"")[0] == -90.0  # an empty read is silence, not a crash


class _FakeArecord:
    """Stands in for the arecord process: yields frames, then stops (as if the camera was unplugged)."""

    def __init__(self, frames):
        self._frames, self.returncode = list(frames), None
        self.stdout = self

    async def readexactly(self, n):
        await asyncio.sleep(0.01)  # real audio arrives over time, so a call can start in the middle
        if not self._frames:
            raise asyncio.IncompleteReadError(b"", n)
        return self._frames.pop(0)

    def terminate(self):
        self.returncode = 0

    async def wait(self):
        return 0


def _fake_mic(monkeypatch, frames):
    async def spawn(*args, **kwargs):
        return _FakeArecord(frames)

    monkeypatch.setattr(pi_plane.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(pi_plane.asyncio, "create_subprocess_exec", spawn)


def test_mic_test_says_the_microphone_works_when_it_hears_sound(monkeypatch, capsys):
    _fake_mic(monkeypatch, [_tone(6000)] * 5)
    assert asyncio.run(pi_plane.test_mic("plughw:3,0", 5)) == 0
    out = capsys.readouterr().out
    assert "Listening on plughw:3,0" in out and "picking up sound" in out
    assert "stopped sending audio" in out  # the fake runs dry, like an unplugged camera


def test_mic_test_explains_a_missing_microphone_instead_of_staying_quiet(monkeypatch, capsys):
    _fake_mic(monkeypatch, [])  # arecord started but never produced audio
    assert asyncio.run(pi_plane.test_mic("plughw:3,0", 5)) == 1
    assert "No audio from plughw:3,0" in capsys.readouterr().out
    monkeypatch.setattr(pi_plane.shutil, "which", lambda name: None)  # no arecord at all
    assert asyncio.run(pi_plane.test_mic("default", 1)) == 1
    assert "install alsa-utils" in capsys.readouterr().out


def test_a_call_gets_only_the_frames_spoken_while_talking(monkeypatch):
    _fake_mic(monkeypatch, [_tone(5000)] * 6)

    async def go():
        mic = pi_plane.Mic("x", show=False)
        runner = asyncio.ensure_future(mic.run())
        await asyncio.sleep(0.025)  # the first frames are heard but are not part of any call
        mic.talking = True
        stop = asyncio.Event()
        taken = []

        async def collect():
            async for frame in mic.call_frames(stop):
                taken.append(frame)

        collector = asyncio.ensure_future(collect())
        await runner  # the fake runs out of audio
        stop.set()
        await collector
        return mic, taken

    mic, taken = asyncio.run(go())
    assert mic.frames == 6 and 0 < len(taken) < 6  # only what was spoken after the key went down


def test_the_gain_is_set_on_every_start_because_a_replug_resets_it(monkeypatch):
    calls = []

    class Done:
        returncode = 0

    monkeypatch.setattr(pi_plane.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(pi_plane.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Done())
    assert "25%" in pi_plane.set_gain("plughw:3,0", 25)
    assert calls == [["amixer", "-c", "3", "sset", "Mic", "25%"]]
    assert pi_plane.set_gain("default", 25) is None  # no card number to set
    assert pi_plane.set_gain("plughw:3,0", 0) is None  # 0 leaves the level alone
    assert len(calls) == 1
    monkeypatch.setattr(pi_plane.shutil, "which", lambda name: None)  # no amixer: no failure, just no change
    assert pi_plane.set_gain("plughw:3,0", 25) is None
