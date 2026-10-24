"""Drive presenter mode in a headless browser and save one screenshot per scene.

Starts `python -m unstep.demo` (offline fakes unless --live), presses Space through
every scene like a presenter, and writes PNGs for review or the README.

Run: python scripts/demo_screenshots.py [--live] [--out data/screenshots] [--size 1920x1080]
"""

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SCENE_WAIT_S = {1: 4, 2: 4, 3: 12, 4: 10}  # audio still playing after a scene is Ready


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true")
    p.add_argument("--out", default=str(ROOT / "data" / "screenshots"))
    p.add_argument("--size", default="1920x1080")
    args = p.parse_args()
    width, height = (int(v) for v in args.size.split("x"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    port = free_port()
    cmd = [sys.executable, "-m", "unstep.demo", "--no-browser", "--port", str(port)] + (["--live"] if args.live else [])
    server = subprocess.Popen(cmd, cwd=ROOT)
    try:
        url = f"http://127.0.0.1:{port}/demo/"
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        with sync_playwright() as pw:
            launch = dict(args=["--autoplay-policy=no-user-gesture-required"])
            try:
                browser = pw.chromium.launch(**launch)
            except Exception:  # bundled Chromium not downloaded: use the system Edge
                browser = pw.chromium.launch(channel="msedge", **launch)
            page = browser.new_page(viewport={"width": width, "height": height})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(url)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / "scene0-start.png"))
            start = page.locator("#start")
            if start.count() and start.is_visible():
                start.click()
            for scene in range(1, 8):
                page.keyboard.press("Space")
                # Like a presenter: wait until the scene reports Ready, then let audio finish.
                page.wait_for_timeout(1000)
                for _ in range(120):
                    if "Ready for next scene" in page.locator("#status").inner_text():
                        break
                    page.wait_for_timeout(500)
                page.wait_for_timeout(int(SCENE_WAIT_S.get(scene, 2) * 1000))
                page.screenshot(path=str(out / f"scene{scene}.png"))
                status = page.locator("#status").inner_text() if page.locator("#status").count() else ""
                print(f"scene {scene}: {status}")
            page.keyboard.press("a")
            page.wait_for_timeout(800)
            page.screenshot(path=str(out / "scene7-toggled.png"))
            browser.close()
        for e in errors:
            print("browser error:", e)
        print(f"screenshots in {out}")
        return 1 if errors else 0
    finally:
        server.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
