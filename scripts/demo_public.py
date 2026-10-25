"""One command for demo day: a public https link, so a judge just scans the QR and is in.

    python scripts/demo_public.py

1. Starts a Cloudflare quick tunnel to the hub (no account; a random
   https://<words>.trycloudflare.com address with a real certificate). It works on any
   network, including a judge's phone data, and phones allow the microphone on https.
2. Starts the live hub with that address as UNSTEP_PUBLIC_URL, so the console's QR points at it.
3. Opens the console on this laptop.

The console is reachable through the tunnel, so it uses UNSTEP_ATC_PASSWORD from .env when
set. cloudflared: on PATH, at ~/tools/cloudflared.exe, or at $CLOUDFLARED. Ctrl+C stops both.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def find_cloudflared() -> str | None:
    candidates = [os.getenv("CLOUDFLARED"), shutil.which("cloudflared"),
                  str(Path.home() / "tools" / "cloudflared.exe")]
    return next((c for c in candidates if c and Path(c).exists()), None)


def start_tunnel(exe: str, port: int, timeout_s: float = 45.0) -> tuple[subprocess.Popen, str]:
    """Start the quick tunnel and return it with its public URL (cloudflared logs it)."""
    proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    found: list[str] = []

    def read() -> None:
        for line in proc.stdout:  # keep draining so cloudflared never blocks on a full pipe
            if not found and (m := TUNNEL_URL.search(line)):
                found.append(m.group(0))

    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + timeout_s
    while not found and time.monotonic() < deadline and proc.poll() is None:
        time.sleep(0.2)
    if not found:
        proc.terminate()
        raise SystemExit("cloudflared did not report a tunnel URL; check the internet connection")
    return proc, found[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    exe = find_cloudflared()
    if not exe:
        raise SystemExit("cloudflared not found: winget install --id Cloudflare.cloudflared (or set CLOUDFLARED)")
    tunnel, url = start_tunnel(exe, args.port)
    host = url.removeprefix("https://")
    env = {**os.environ,
           "UNSTEP_PUBLIC_URL": url,
           "UNSTEP_ALLOWED_HOSTS": ",".join(filter(None, [os.getenv("UNSTEP_ALLOWED_HOSTS"), "localhost", "127.0.0.1", host])),
           "UNSTEP_ALLOWED_ORIGINS": ",".join(filter(None, [os.getenv("UNSTEP_ALLOWED_ORIGINS"), url]))}
    hub = subprocess.Popen([sys.executable, "-m", "unstep.live", "--host", "127.0.0.1",
                            "--port", str(args.port), "--no-browser"], cwd=ROOT, env=env)
    print(f"\nJudges scan the QR, or open: {url}/pilot/")
    print(f"Console on this laptop:      http://localhost:{args.port}/live/atc/\n", flush=True)
    if not args.no_browser:
        time.sleep(5)
        webbrowser.open(f"http://localhost:{args.port}/live/atc/")
    try:
        hub.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in (hub, tunnel):
            if p.poll() is None:
                p.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
