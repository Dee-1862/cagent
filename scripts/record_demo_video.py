"""Record a backup video of presenter mode, with the real audio, as an MP4.

Playwright records the screen while presenter mode runs (live by default). An
injected script logs when each audio file actually starts playing in the page;
ffmpeg then places every clip at that moment and muxes it with the video. The
result is what an audience would have seen and heard, for demo-day fallback.

Run: python scripts/record_demo_video.py [--offline] [--out data/video/unstep-demo.mp4]
Pauses between scenes are short and fixed; edit PAUSE_S to change the pacing.
"""

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "data" / "demo" / "audio"
SCENES = 7
PAUSE_S = {1: 3.0, 2: 3.0, 3: 3.0, 4: 3.0, 5: 6.0, 6: 7.0, 7: 5.0}  # after a scene is Ready

# Logs every audio file the page plays: url, and ms since navigation start.
AUDIO_PROBE = """
(() => {
  const urls = new WeakMap(), buffers = new WeakMap();
  window.__plays = [];
  const fetch0 = window.fetch;
  window.fetch = async (input, init) => {
    const res = await fetch0(input, init);
    const url = typeof input === 'string' ? input : input.url;
    if (url.includes('/demo/audio/')) {
      const ab0 = res.arrayBuffer.bind(res);
      res.arrayBuffer = async () => { const ab = await ab0(); urls.set(ab, url); return ab; };
    }
    return res;
  };
  const decode0 = BaseAudioContext.prototype.decodeAudioData;
  BaseAudioContext.prototype.decodeAudioData = function (ab, ...rest) {
    const url = urls.get(ab);
    return decode0.call(this, ab, ...rest).then(buf => { if (url) buffers.set(buf, url); return buf; });
  };
  const start0 = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function (...args) {
    const url = this.buffer && buffers.get(this.buffer);
    if (url) window.__plays.push({ url, t: performance.now() });
    return start0.apply(this, args);
  };
  const play0 = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    if (this.src && this.src.includes('/demo/audio/')) window.__plays.push({ url: this.src, t: performance.now() });
    return play0.call(this);
  };
})();
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(page, timeout_s: float = 120) -> str:
    deadline = time.time() + timeout_s
    status = ""
    while time.time() < deadline:
        status = page.locator("#status").inner_text()
        if "Ready for next scene" in status or "failed" in status.lower():
            return status
        page.wait_for_timeout(300)
    return status


def mix(video: Path, plays: list[dict], out: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    inputs, filters, labels = ["-i", str(video)], [], []
    for i, play in enumerate(plays, start=1):
        name = play["url"].rsplit("/", 1)[-1]
        path = AUDIO_DIR / name
        if not path.is_file():
            continue
        inputs += ["-i", str(path)]
        delay = max(0, int(play["t"]))
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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--offline", action="store_true", help="fakes instead of live Cartesia and Moss")
    p.add_argument("--out", default=str(ROOT / "data" / "video" / "unstep-demo.mp4"))
    args = p.parse_args()

    port = free_port()
    cmd = [sys.executable, "-m", "unstep.demo", "--no-browser", "--port", str(port)] + ([] if args.offline else ["--live"])
    server = subprocess.Popen(cmd, cwd=ROOT)
    try:
        for _ in range(1200):  # live mode warms up first
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
            launch = dict(args=["--autoplay-policy=no-user-gesture-required"])
            try:
                browser = pw.chromium.launch(**launch)
            except Exception:
                browser = pw.chromium.launch(channel="msedge", **launch)
            context = browser.new_context(viewport={"width": 1920, "height": 1080},
                                          record_video_dir=tmp, record_video_size={"width": 1920, "height": 1080})
            context.add_init_script(AUDIO_PROBE)
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{port}/demo/")
            page.wait_for_timeout(1500)
            if page.locator("#start").count() and page.locator("#start").is_visible():
                page.locator("#start").click()
            for scene in range(1, SCENES + 1):
                page.keyboard.press("Space")
                page.wait_for_timeout(800)
                status = wait_ready(page)
                print(f"scene {scene}: {status}")
                if "failed" in status.lower():
                    print("scene failed; stopping the recording")
                    break
                page.wait_for_timeout(int(PAUSE_S.get(scene, 3) * 1000))
            plays = page.evaluate("window.__plays")
            video_path = Path(page.video.path())
            context.close()
            browser.close()
            out = Path(args.out)
            mix(video_path, plays, out)
        (Path(args.out).with_suffix(".plays.json")).write_text(json.dumps(plays, indent=2))
        print(f"wrote {args.out} ({len(plays)} audio clips placed)")
        return 0
    finally:
        server.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
