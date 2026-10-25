"""Record the live room demo (R24): ATC console plus two pilot phones, one 1920x1080 video with sound.

Starts `python -m unstep.live` (warm start) on a free port, or connects to a hub with --port.
One browser page holds three frames side by side (ATC, Plane A = N123AB, Plane B = H456).
Pilot calls and readbacks use the same websocket clients as e2e_taxi.py:

  1. Both planes queue on Taxiway B; Plane A requests taxi and receives clearance.
  2. Plane A reads back and taxis to the Runway 33 hold short line.
  3. Plane B reads back line up and wait, then a clearance card and takeoff readback.
  4. A stepped-on stop call, private advisory, and a wrong then corrected readback.

Every step has a timeout and the run stops with an error naming the step.

Sound: the room sends its audio over the socket (radio clips, advisory chunks, recovery
lines), not as files, so `AUDIO_PROBE` from record_demo_video.py can't see it. A socket probe
logs every audio message with its wall-clock time in each frame; ffmpeg then places each
clip at that moment, using the same muxing as record_demo_video.py.

Run:  python scripts/record_live_video.py [--offline] [--out data/video/unstep-live.mp4]
Needs: playwright with chromium, imageio-ffmpeg, and the pilot app built (cd app && npm run build).
UNSTEP_ATC_PASSWORD and UNSTEP_GATEWAY_TOKEN are read from the environment if set.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STEP_TIMEOUT_MS = 60_000
WIDTH, HEIGHT = 1920, 1080

# Logs every audio-bearing socket message with Date.now(), in every frame.
SOCKET_PROBE = """
(() => {
  window.__audio = [];
  const WS = window.WebSocket;
  window.WebSocket = function (...args) {
    const ws = new WS(...args);
    ws.addEventListener('message', (e) => {
      let m; try { m = JSON.parse(e.data); } catch { return; }
      const t = Date.now();
      if (m.type === 'onair' && m.audio) window.__audio.push({kind: 'radio', id: m.tx_id, t, wav: m.audio});
      else if (m.type === 'advisory_chunk') window.__audio.push({kind: 'chunk', id: m.id, seq: m.seq, t, rate: m.sample_rate, pcm: m.pcm});
      else if (m.type === 'advisory_audio' && m.audio && !m.streamed) window.__audio.push({kind: 'advisory', id: 'adv-' + t, t, wav: m.audio});
      else if ((m.type === 'recovery' || m.type === 'controller_audio') && m.audio) window.__audio.push({kind: m.type, id: m.type + '-' + t, t, wav: m.audio});
    });
    return ws;
  };
  window.WebSocket.prototype = WS.prototype;
  Object.assign(window.WebSocket, {CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3});
})();
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def layout_html(port: int, token: str | None) -> str:
    """One page, three frames: console on the left half, the two phones on the right."""
    base = f"http://127.0.0.1:{port}"
    q = f"?token={quote(token)}" if token else ""
    return f"""<!doctype html><html><body style="margin:0;background:#0b1220;display:flex;height:{HEIGHT}px">
<iframe id="atc" src="{base}/live/atc/{q}{'&' if q else '?'}quality=low" style="border:0;width:1080px;height:{HEIGHT}px" allow="autoplay"></iframe>
<iframe id="a" src="{base}/pilot/{q}#/fly/N123AB" style="border:0;width:420px;height:{HEIGHT}px" allow="autoplay"></iframe>
<iframe id="b" src="{base}/pilot/{q}#/fly/H456" style="border:0;width:420px;height:{HEIGHT}px" allow="autoplay"></iframe>
</body></html>"""


def to_wav(samples, rate: int) -> bytes:
    import numpy as np
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, np.asarray(samples), rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def audio_plan(events: list[dict], t0_ms: float) -> list[tuple[int, bytes]]:
    """(delay ms from the video start, WAV bytes) per clip. Radio clips heard in several frames
    are kept once (by tx id); streamed advisory chunks are joined per stream."""
    import numpy as np

    seen, clips, streams = set(), [], {}
    for e in sorted(events, key=lambda e: e["t"]):
        if e["kind"] == "chunk":
            s = streams.setdefault(e["id"], {"t": e["t"], "rate": e["rate"], "parts": {}})
            s["parts"][e["seq"]] = base64.b64decode(e["pcm"])
            continue
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        clips.append((max(0, int(e["t"] - t0_ms)), base64.b64decode(e["wav"])))
    for s in streams.values():
        pcm = b"".join(s["parts"][k] for k in sorted(s["parts"]))
        clips.append((max(0, int(s["t"] - t0_ms)), to_wav(np.frombuffer(pcm, dtype="<i2"), s["rate"])))
    return sorted(clips, key=lambda c: c[0])


def mix(video: Path, clips: list[tuple[int, bytes]], out: Path, tmp: Path) -> None:
    """Same muxing as record_demo_video.py: each clip delayed to its moment, amixed, H.264 + AAC."""
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    inputs, filters, labels = ["-i", str(video)], [], []
    for i, (delay, wav) in enumerate(clips, start=1):
        path = tmp / f"clip-{i:03d}.wav"
        path.write_bytes(wav)
        inputs += ["-i", str(path)]
        filters.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={delay}|{delay}[a{i}]")
        labels.append(f"[a{i}]")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", *inputs]
    if labels:
        filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0[aout]")
        cmd += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)


class StepFailed(RuntimeError):
    pass


class Pilots:
    """Keep both pilot websocket stations connected while the console records."""

    def __init__(self, port: int):
        import websockets

        self.port = port
        self.websockets = websockets
        self.loop = asyncio.new_event_loop()
        self.sockets = {}
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        if not self.ready.wait(30):
            raise RuntimeError("pilot websocket clients did not connect")

    async def _pilot(self, station: str):
        async with self.websockets.connect(f"ws://127.0.0.1:{self.port}/live/ws/{station}") as ws:
            self.sockets[station] = ws
            if len(self.sockets) == 2:
                self.ready.set()
            async for _ in ws:
                pass

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.task = self.loop.create_task(self._connect_both())
        self.loop.run_forever()
        self.loop.run_until_complete(self.task)
        self.loop.close()

    async def _connect_both(self):
        await asyncio.gather(self._pilot("N123AB"), self._pilot("H456"))

    def say(self, station: str, text: str):
        asyncio.run_coroutine_threadsafe(
            self.sockets[station].send(json.dumps({"type": "say", "text": text})), self.loop
        ).result(10)

    def close(self):
        async def disconnect():
            await asyncio.gather(*(ws.close() for ws in self.sockets.values()))
        asyncio.run_coroutine_threadsafe(disconnect(), self.loop).result(30)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=10)


def step(name: str, fn) -> None:
    started = time.time()
    try:
        fn()
    except Exception as exc:  # playwright timeouts and missing elements
        raise StepFailed(f"step '{name}' did not happen within {STEP_TIMEOUT_MS // 1000} s: {exc}") from exc
    print(f"ok   {name} ({time.time() - started:.1f} s)")


def start_hub(port: int, offline: bool) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "unstep.live", "--no-browser", "--port", str(port)] + (["--offline"] if offline else [])
    server = subprocess.Popen(cmd, cwd=ROOT)
    for _ in range(1200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return server
        except OSError:
            if server.poll() is not None:
                raise RuntimeError("the hub exited during start")
            time.sleep(0.1)
    server.terminate()
    raise RuntimeError("the hub did not start")


def run_story(page, password: str | None, pilots: Pilots) -> None:
    from playwright.sync_api import expect

    atc, a, b = (page.frame_locator(f"#{i}") for i in ("atc", "a", "b"))
    t = STEP_TIMEOUT_MS

    def login():
        if password and atc.locator("#auth-form").is_visible():
            atc.locator("#password").fill(password)
            atc.locator("#auth-form button, #auth-form [type=submit]").first.click()
        expect(atc.locator("#autonomy")).to_be_enabled(timeout=45_000)  # warm start: Moss sessions for six planes

    def autonomy_off():
        if atc.locator("#autonomy").is_checked():
            atc.locator("#autonomy").click()
        expect(atc.locator("#autonomy")).not_to_be_checked(timeout=t)

    def feed_has(text):
        return atc.locator("#feed .feed-row", has_text=text).count() > 0

    def wait_feed(text, timeout=t):
        expect(atc.locator("#feed .feed-row", has_text=text).first).to_be_visible(timeout=timeout)

    def planes():
        return atc.locator("body").evaluate("() => window.unstepAirport?.inspect?.() || []")

    def wait_plane(station, predicate, timeout=t):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            plane = next((p for p in planes() if p["id"] == station), None)
            if plane and predicate(plane):
                return
            page.wait_for_timeout(500)
        raise AssertionError(f"{station} did not reach expected state: {planes()}")

    def await_readback_window(station, instruction):
        # Match the current instruction so an older feed row cannot open this window.
        who = "Plane A" if station == "N123AB" else "Plane B"
        wait_feed(f"{who} was told")
        wait_feed(instruction)

    def readback(station, instruction, text):
        await_readback_window(station, instruction)
        pilots.say(station, text)

    def tower(text):
        atc.locator("#say").fill(text)
        atc.locator("#transmit").click()

    def card(title):
        return atc.locator("#requests .clearance", has_text=title).first

    def queue():
        expect(a.get_by_role("button", name="More")).to_be_visible(timeout=t)
        expect(b.get_by_role("button", name="More")).to_be_visible(timeout=t)
        wait_plane("N123AB", lambda p: p["state"] == "queue" and p["z"] == 14)
        wait_plane("H456", lambda p: p["state"] == "queue" and p["z"] == 14)
        wait_feed("Plane A now in Taxiway B at 37.")

    def request_taxi():
        pilots.say("N123AB", "Tower, Cessna one two three, request taxi")
        expect(card("Plane A asks")).to_be_visible(timeout=t)
        expect(card("Plane A asks").locator(".proposal")).to_contain_text("taxi to runway 33 via Bravo, hold short of runway 33")
        card("Plane A asks").locator("button.approve").click()
        readback("N123AB", "taxi to runway 33 via Bravo, hold short", "taxi to runway 33 via bravo, hold short of runway 33, Cessna 123")
        wait_feed("Plane A read it back correctly")
        wait_plane("N123AB", lambda p: p["state"] == "holding" and p["x"] == -33)

    def plane_b_lineup():
        tower("Helicopter 456 line up and wait runway 15")
        readback("H456", "line up and wait runway 15", "line up and wait runway 15, helicopter 456")
        wait_feed("Plane B read it back correctly")
        wait_plane("H456", lambda p: p["state"] == "lined_up")

    def plane_b_departure():
        expect(card("Next for Plane B")).to_be_visible(timeout=t)
        expect(card("Next for Plane B").locator(".proposal")).to_contain_text("cleared for takeoff")
        card("Next for Plane B").locator("button.approve").click()
        readback("H456", "runway 15, cleared for takeoff", "runway 15 cleared for takeoff, helicopter 456")
        wait_plane("H456", lambda p: p["alt"] > 1)

    def step_on():
        # DOM clicks dispatch at once; Playwright's actionability waits can separate the
        # two radio calls by several seconds after the scene gets busy.
        atc.locator('[data-say*="hold short runway three three"]').evaluate("button => button.click()")
        b.get_by_role("button", name="Request transition").evaluate("button => button.click()")

    step("console signed in", login)
    step("auto-resend off, so the decision card shows", autonomy_off)
    step("both planes queue on Taxiway B with Geo rows", queue)
    step("Plane A requests, reads back, and taxis to runway 33", request_taxi)
    step("Plane B reads back line up and wait runway 15", plane_b_lineup)
    step("Next for Plane B is sent and read back; Plane B departs", plane_b_departure)
    b.get_by_role("button", name="More").click(timeout=t)
    expect(b.get_by_role("button", name="Request transition")).to_be_visible(timeout=t)
    step("tower says hold short 33 while Plane B talks", step_on)
    step("TALKED OVER on the console", lambda: expect(atc.locator(".talked-over >> visible=true").first).to_be_visible(timeout=t))  # the Legend also says "talked over"
    page.wait_for_timeout(1500)
    step("decision card: Approve and send",
         lambda: atc.get_by_role("button", name="Approve and send").first.click(timeout=t))
    step("Plane A hears 'From Tower' privately",
         lambda: expect(a.get_by_text("From Tower").first).to_be_visible(timeout=t))
    page.wait_for_timeout(2500)
    step("recovery line to the tower for Plane B",
         lambda: expect(atc.get_by_text("was blocked").locator("visible=true").first).to_be_visible(timeout=t))
    page.wait_for_timeout(3000)

    def wrong_then_correct():
        tower("Cessna 123 line up and wait runway 33")
        readback("N123AB", "line up and wait runway 33", "line up and wait runway 13, Cessna 123")
        wait_feed("Wrong readback from Plane A")
        if next(p for p in planes() if p["id"] == "N123AB")["state"] != "holding":
            raise AssertionError("Plane A moved after a wrong readback")
        pilots.say("N123AB", "line up and wait runway 33, Cessna 123")
        wait_feed("Plane A read it back correctly")
        wait_plane("N123AB", lambda p: p["state"] == "lined_up")

    step("wrong readback flagged, then corrected", wrong_then_correct)

    def panels():  # the calm console keeps these behind the evidence sheet and the Safety tab
        atc.locator("#show-evidence").click(timeout=t)
        expect(atc.locator(".waterfall").first).to_be_visible(timeout=t)
        page.wait_for_timeout(3000)
        atc.locator("#close-evidence").click(timeout=t)
        atc.locator('.side-tabs [data-tab="safety"]').click(timeout=t)
        expect(atc.locator("#stats-source")).to_be_visible(timeout=t)
    step("waterfall and Elastic panel on screen", panels)
    page.wait_for_timeout(5000)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--offline", action="store_true", help="fake speech, no Cartesia, Moss or Elastic")
    p.add_argument("--out", default=str(ROOT / "data" / "video" / "unstep-live.mp4"))
    p.add_argument("--port", type=int, help="use an already running hub on this port")
    args = p.parse_args(argv)
    if not (ROOT / "app" / "dist" / "index.html").is_file():
        print("Build the pilot app first: cd app && npm install && npm run build", file=sys.stderr)
        return 1
    from playwright.sync_api import sync_playwright

    port = args.port or free_port()
    server = None if args.port else start_hub(port, args.offline)
    try:
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
            pilots = Pilots(port)
            launch = dict(args=["--autoplay-policy=no-user-gesture-required"])
            try:
                browser = pw.chromium.launch(**launch)
            except Exception:
                browser = pw.chromium.launch(channel="msedge", **launch)
            context = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, record_video_dir=tmp,
                                          record_video_size={"width": WIDTH, "height": HEIGHT})
            context.add_init_script(SOCKET_PROBE)  # runs in every frame
            page = context.new_page()
            t0 = page.evaluate("performance.timeOrigin")  # the recording starts with the page
            page.set_content(layout_html(port, os.environ.get("UNSTEP_GATEWAY_TOKEN")))
            failed = None
            try:
                run_story(page, os.environ.get("UNSTEP_ATC_PASSWORD"), pilots)
            except StepFailed as exc:
                failed = exc
            events = []
            for frame in page.frames[1:]:
                try:
                    events += frame.evaluate("window.__audio || []")
                except Exception:
                    pass
            video = Path(page.video.path())
            context.close()
            browser.close()
            pilots.close()
            out = Path(args.out)
            mix(video, audio_plan(events, t0), out, Path(tmp))
            print(f"wrote {out} ({len(events)} audio messages)")
            if failed:
                print(f"FAILED: {failed}", file=sys.stderr)
                return 1
        return 0
    finally:
        if server:
            server.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
