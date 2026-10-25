"""python -m unstep.live [--offline] [--host 127.0.0.1] [--port 8765] [--no-browser] [--https | --cert C --key K]

Starts the live radio room. Everyone opens the printed link, picks a seat
(tower controller, a pilot, or the observer screen) and talks on the shared
frequency. Live mode (Cartesia speech and transcription) is on when
CARTESIA_API_KEY is set, unless --offline is given.

Phones on the same network: run with --host 0.0.0.0 and add this machine's
address to UNSTEP_ALLOWED_HOSTS. Browsers allow the microphone only on
https or localhost; the say box works everywhere. For phone mics on the LAN
without a tunnel, add --https (a self-signed certificate, accepted once per
phone) or pass your own --cert and --key.
"""

import argparse
import os
import socket
import webbrowser

import uvicorn

from unstep.config import env
from unstep.live.addresses import lan_addresses
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
    parser.add_argument("--https", action="store_true",
                        help="serve https with a self-signed certificate (data/certs/), so phone mics work")
    parser.add_argument("--cert", help="certificate file (PEM) to serve https with")
    parser.add_argument("--key", help="private key file (PEM) for --cert")
    args = parser.parse_args()
    if bool(args.cert) != bool(args.key):
        parser.error("--cert and --key go together")
    live = not args.offline and bool(env("CARTESIA_API_KEY"))
    if args.host not in ("127.0.0.1", "localhost"):  # open to the LAN: this computer's own addresses are valid Hosts
        mine = ",".join(a for a in lan_addresses() if a not in (env("UNSTEP_ALLOWED_HOSTS") or ""))
        if mine:
            os.environ["UNSTEP_ALLOWED_HOSTS"] = ",".join(x for x in ((env("UNSTEP_ALLOWED_HOSTS") or ""), mine) if x)
    ip = lan_address() if args.host not in ("127.0.0.1", "localhost") else None
    tls = {}
    if args.cert:
        tls = {"ssl_certfile": args.cert, "ssl_keyfile": args.key}
    elif args.https:
        from unstep.live.certs import self_signed

        cert, key = self_signed([h for h in (ip, args.host) if h and h != "0.0.0.0"])
        tls = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
        print(f"Self-signed certificate: {cert} (each phone accepts the warning once)")
    scheme = "https" if tls else "http"
    url = f"{scheme}://127.0.0.1:{args.port}/live/"
    mode = 'LIVE: Cartesia speech' if live else 'offline: fake speech'
    public = env("UNSTEP_PUBLIC_URL")
    if public:  # hosted (Render): the inside addresses below mean nothing to visitors
        public = public.rstrip("/")
        print(f"Unstep live room ({mode}): tower {public}/live/atc/ · pilots {public}/pilot/")
    else:
        print(f"Unstep live room ({mode}): {url}")
    if ip and not public:
        print(f"Others on this network: {scheme}://{ip}:{args.port}/live/ (add {ip} to UNSTEP_ALLOWED_HOSTS"
              + ("; set UNSTEP_PUBLIC_URL=https://%s:%d for the QR)" % (ip, args.port) if tls
                 else "; microphones need https: add --https)"))
    if not args.no_browser:
        webbrowser.open(url)
    app = create_live_app(live=live, warm_start=True)
    app.state.bind_host = args.host  # the console's "change link" says whether phones can reach this hub
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", **tls)


if __name__ == "__main__":
    main()
