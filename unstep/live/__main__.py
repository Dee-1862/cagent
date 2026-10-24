"""python -m unstep.live [--offline] [--host 127.0.0.1] [--port 8765] [--no-browser]

Starts the live radio room. Everyone opens the printed link, picks a seat
(tower controller, a pilot, or the observer screen) and talks on the shared
frequency. Live mode (Cartesia speech and transcription) is on when
CARTESIA_API_KEY is set, unless --offline is given.

Phones on the same network: run with --host 0.0.0.0 and add this machine's
address to UNSTEP_ALLOWED_HOSTS. Browsers allow the microphone only on
https or localhost; the say box works everywhere.
"""

import argparse
import socket
import webbrowser

import uvicorn

from unstep.config import env
from unstep.live.app import create_live_app


def lan_address() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="fake speech, no Cartesia calls")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    live = not args.offline and bool(env("CARTESIA_API_KEY"))
    url = f"http://127.0.0.1:{args.port}/live/"
    print(f"Unstep live room ({'LIVE: Cartesia speech' if live else 'offline: fake speech'}): {url}")
    if args.host not in ("127.0.0.1", "localhost"):
        ip = lan_address()
        if ip:
            print(f"Others on this network: http://{ip}:{args.port}/live/ "
                  f"(add {ip} to UNSTEP_ALLOWED_HOSTS; microphones need https)")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(create_live_app(live=live), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
