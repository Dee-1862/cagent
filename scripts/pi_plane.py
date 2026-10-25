#!/usr/bin/env python3
"""A Raspberry Pi as one plane's radio: joins the hub as a pilot and talks and listens like the pilot app.

    python scripts/pi_plane.py --hub http://192.168.2.53:8765 --wav assets/clips/real/clean_call.wav
    python scripts/pi_plane.py --hub http://192.168.2.53:8765 --mic plughw:3,0     # Enter = start/stop talking
    python scripts/pi_plane.py --hub https://unstep.onrender.com --token <room code> --mic plughw:3,0

It needs only `websockets` and the standard library. Live audio comes from `arecord` (alsa-utils), the
advisory is played with `aplay`; without them the script still joins, talks from a WAV and prints what the hub says.
It speaks the same messages as the pilot app (app/src/App.tsx): `key`, `mic_frame` (100 ms of 16 kHz mono
16-bit PCM, base64) and `mic_end`; the hub does the rest. The console's "Add Raspberry Pi" button shows this
command with the right hub address.

Push to talk here is the Enter key. Covering the camera or a GPIO pin is planned, not built.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1600  # 100 ms, what the pilot app sends
FRAME_BYTES = FRAME_SAMPLES * 2
TAIL_S = 0.3  # keep the key down briefly after the last word, like the pilot app


def join(hub: str, token: str | None) -> dict:
    """POST /live/join: the hub hands out a free plane."""
    query = urllib.parse.urlencode({"token": token} if token else {})
    request = urllib.request.Request(f"{hub.rstrip('/')}/live/join" + (f"?{query}" if query else ""), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read().decode() or "{}").get("error", e.reason)
        raise SystemExit(f"The hub refused the join ({e.code}): {detail}")
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit(f"Cannot reach the hub at {hub}: {e}. Is it running with --host 0.0.0.0, on the same network?")


def socket_url(hub: str, station: str, token: str | None) -> str:
    parts = urllib.parse.urlsplit(hub.rstrip("/"))
    scheme = "wss" if parts.scheme == "https" else "ws"
    query = urllib.parse.urlencode({"token": token} if token else {})
    return f"{scheme}://{parts.netloc}/live/ws/{station}" + (f"?{query}" if query else "")


def wav_frames(path: str):
    """100 ms frames of a 16 kHz mono 16-bit WAV."""
    with wave.open(path, "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            raise SystemExit(f"{path} must be 16 kHz, mono, 16-bit (this one is {w.getframerate()} Hz, "
                             f"{w.getnchannels()} channel(s), {8 * w.getsampwidth()}-bit)")
        data = w.readframes(w.getnframes())
    for i in range(0, len(data), FRAME_BYTES):
        yield data[i:i + FRAME_BYTES]


async def mic_frames(device: str, stop: asyncio.Event):
    """100 ms frames from the microphone through arecord, until `stop` is set."""
    if not shutil.which("arecord"):
        raise SystemExit("arecord not found: install alsa-utils (sudo apt install alsa-utils)")
    proc = await asyncio.create_subprocess_exec(
        "arecord", "-q", "-D", device, "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-t", "raw",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        while not stop.is_set():
            try:
                frame = await asyncio.wait_for(proc.stdout.readexactly(FRAME_BYTES), timeout=2)
            except (asyncio.IncompleteReadError, asyncio.TimeoutError):
                break
            yield frame
    finally:
        if proc.returncode is None:
            proc.terminate()
        await proc.wait()


class Plane:
    def __init__(self, ws, station: str, play: bool):
        self.ws, self.station, self.play = ws, station, play
        self.offset = 0.0  # hub time = local time + offset (ms)
        self.heard: list[str] = []  # message types, for the summary
        self.frames_sent = 0

    def now(self) -> int:
        return round(time.time() * 1000 + self.offset)

    async def sync_clock(self, tries: int = 4) -> None:
        """Ping the hub; the reply with the shortest round trip sets the offset (same as the pilot app)."""
        best = None
        for _ in range(tries):
            t0 = time.time() * 1000
            await self.ws.send(json.dumps({"type": "ping", "t0": t0}))
            while True:
                m = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=10))
                if m.get("type") == "pong":
                    break
                self.handle(m)
            t3 = time.time() * 1000
            if best is None or t3 - t0 < best[0]:
                best = (t3 - t0, m["t1"] - (t0 + t3) / 2)
        self.offset = best[1]

    async def talk(self, frames, realtime: bool = True) -> int:
        """Key down, stream the frames as they are spoken, key up. Returns the number of frames sent."""
        start = self.now()
        await self.ws.send(json.dumps({"type": "key", "down": True, "at": start}))
        sent = 0
        if hasattr(frames, "__aiter__"):
            async for frame in frames:
                await self._frame(start, frame)
                sent += 1
        else:
            for frame in frames:
                await self._frame(start, frame)
                sent += 1
                if realtime:
                    await asyncio.sleep(len(frame) / 2 / SAMPLE_RATE)
        await asyncio.sleep(TAIL_S)
        await self.ws.send(json.dumps({"type": "mic_end"}))
        self.frames_sent += sent
        return sent

    async def _frame(self, start: int, frame: bytes) -> None:
        await self.ws.send(json.dumps({"type": "mic_frame", "start_ms": start, "pcm": base64.b64encode(frame).decode()}))

    def handle(self, m: dict) -> None:
        kind = m.get("type", "?")
        self.heard.append(kind)
        if kind == "cockpit_line":
            print(f"  [{m.get('party', '')}] {m.get('text', '')}")
        elif kind == "status":
            print(f"  hub: {m.get('text', '')}")
        elif kind == "stepon_live" and self.station in (m.get("stations") or []):
            print("  Talked over: your call was blocked")
        elif kind in ("advisory_audio", "onair") and self.play and not m.get("streamed"):
            self.speak(m.get("audio", ""))

    def speak(self, wav_b64: str) -> None:
        if not wav_b64 or not shutil.which("aplay"):
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(base64.b64decode(wav_b64))
        subprocess.Popen(["aplay", "-q", f.name], stderr=subprocess.DEVNULL)

    async def listen(self, seconds: float | None = None) -> None:
        """Print what the hub sends, for `seconds` or until the socket closes."""
        end = None if seconds is None else time.monotonic() + seconds
        while end is None or time.monotonic() < end:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=0.5 if end else 30)
            except asyncio.TimeoutError:
                continue
            except Exception:
                return
            self.handle(json.loads(raw))


async def hold_to_talk(plane: Plane, device: str) -> None:
    """Enter starts talking, Enter again stops: one press per call."""
    loop = asyncio.get_running_loop()
    print("Press Enter to start talking, Enter again to stop. Ctrl+C to quit.")
    while True:
        if await loop.run_in_executor(None, sys.stdin.readline) == "":  # input closed: quit
            return
        stop = asyncio.Event()
        talking = asyncio.ensure_future(plane.talk(mic_frames(device, stop)))
        print("  on air...")
        await loop.run_in_executor(None, sys.stdin.readline)
        stop.set()
        n = await talking
        print(f"  sent {n / 10:.1f} s")


async def run(args: argparse.Namespace) -> dict:
    import websockets

    seat = join(args.hub, args.token)
    print(f"Joined as {seat.get('name') or seat['station']} ({seat.get('callsign')}) on {seat.get('frequency')}"
          + (" [live voice]" if seat.get("live") else " [offline voice]"))
    context = ssl.create_default_context() if args.hub.startswith("https") else None
    async with websockets.connect(socket_url(args.hub, seat["station"], args.token), ssl=context, max_size=None) as ws:
        plane = Plane(ws, seat["station"], play=not args.no_sound)
        hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
        plane.handle(hello)
        await plane.sync_clock()
        print(f"Clock offset to the hub: {plane.offset:+.0f} ms")
        if args.wav:
            print(f"Talking: {args.wav}")
            await plane.talk(wav_frames(args.wav), realtime=not args.fast)
            await plane.listen(args.listen)
        else:
            reader = asyncio.ensure_future(plane.listen())
            try:
                await hold_to_talk(plane, args.mic)
            finally:
                reader.cancel()
    return {"station": seat["station"], "callsign": seat.get("callsign"), "frames_sent": plane.frames_sent,
            "heard": plane.heard, "offset_ms": plane.offset}


def parse(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="A Raspberry Pi as one plane's radio")
    p.add_argument("--hub", required=True, help="the hub's address, e.g. http://192.168.2.53:8765")
    p.add_argument("--token", help="the room code, when the hub has one (UNSTEP_GATEWAY_TOKEN)")
    p.add_argument("--wav", help="talk once from this 16 kHz mono 16-bit WAV, listen, and exit")
    p.add_argument("--mic", default="default", help="arecord device for live talking, e.g. plughw:3,0 (see arecord -l)")
    p.add_argument("--listen", type=float, default=8.0, help="seconds to listen after a --wav call")
    p.add_argument("--fast", action="store_true", help="send a --wav as fast as possible instead of at speaking pace")
    p.add_argument("--no-sound", action="store_true", help="print what the hub sends but do not play audio")
    return p.parse_args(argv)


if __name__ == "__main__":
    try:
        result = asyncio.run(run(parse()))
        print(f"Done: sent {result['frames_sent']} frames, heard {len(result['heard'])} messages")
    except KeyboardInterrupt:
        print("\nStopped.")
