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
