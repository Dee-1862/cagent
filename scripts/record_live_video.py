"""Record the live room demo (R24): ATC console plus two pilot phones, one 1920x1080 video with sound.

Starts `python -m unstep.live` (warm start) on a free port, opens one browser page that holds
three frames side by side (the ATC console, Plane A = N123AB, Plane B = H456) and drives only
real UI clicks and taps:

  1. Auto-resend off on the console, so the decision card appears.
  2. The tower says "hold short Runway 33" to Plane A (console suggestion button) and,
     at the same moment, Plane B taps "Request transition": a real step-on.
  3. TALKED OVER on the console.  4. The decision card: Approve and send.
  5. Plane A's private advisory, "From Tower".  6. Plane A taps the correct readback.
  7. The recovery line to the tower for Plane B.  8. The waterfall and the Elastic panel.

Every step must appear within 15 s or the run stops with an error naming the step.

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
import base64
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STEP_TIMEOUT_MS = 15_000
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
<iframe id="atc" src="{base}/live/atc/{q}" style="border:0;width:1080px;height:{HEIGHT}px" allow="autoplay"></iframe>
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


def run_story(page, password: str | None) -> None:
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

    def phones_ready():
        for f in (a, b):
            f.get_by_role("button", name="More").click(timeout=t)  # 325cdf7 put the typed lines behind "More"
            expect(f.get_by_role("button", name="Request transition").or_(
                f.get_by_role("button", name="Request taxi"))).to_be_visible(timeout=t)

    def step_on():
        atc.locator('[data-say*="hold short runway three three"]').click()
        b.get_by_role("button", name="Request transition").click()

    step("console signed in", login)
    step("auto-resend off, so the decision card shows", autonomy_off)
    step("both phones on the radio", phones_ready)
    step("tower says hold short 33 while Plane B talks", step_on)
    step("TALKED OVER on the console", lambda: expect(atc.get_by_text("TALKED OVER").first).to_be_visible(timeout=t))
    page.wait_for_timeout(1500)
    step("decision card: Approve and send",
         lambda: atc.get_by_role("button", name="Approve and send").first.click(timeout=t))
    step("Plane A hears 'From Tower' privately",
         lambda: expect(a.get_by_text("From Tower").first).to_be_visible(timeout=t))
    page.wait_for_timeout(2500)
    step("Plane A reads back correctly",
         lambda: a.get_by_role("button", name="Read back: hold short 33").click(timeout=t))
    step("recovery line to the tower for Plane B",
         lambda: expect(atc.get_by_text("was blocked").first).to_be_visible(timeout=t))
    page.wait_for_timeout(3000)

    def panels():
        atc.locator("#steps").scroll_into_view_if_needed(timeout=t)
        expect(atc.locator(".waterfall").first).to_be_visible(timeout=t)
        atc.locator("#stats-source").scroll_into_view_if_needed(timeout=t)
    step("waterfall and Elastic panel on screen", panels)
    page.wait_for_timeout(5000)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--offline", action="store_true", help="fake speech, no Cartesia, Moss or Elastic")
    p.add_argument("--out", default=str(ROOT / "data" / "video" / "unstep-live.mp4"))
    args = p.parse_args(argv)
    if not (ROOT / "app" / "dist" / "index.html").is_file():
        print("Build the pilot app first: cd app && npm install && npm run build", file=sys.stderr)
        return 1
    from playwright.sync_api import sync_playwright

    port = free_port()
    server = start_hub(port, args.offline)
    try:
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
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
                run_story(page, os.environ.get("UNSTEP_ATC_PASSWORD"))
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
            out = Path(args.out)
            mix(video, audio_plan(events, t0), out, Path(tmp))
            print(f"wrote {out} ({len(events)} audio messages)")
            if failed:
                print(f"FAILED: {failed}", file=sys.stderr)
                return 1
        return 0
    finally:
        server.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
