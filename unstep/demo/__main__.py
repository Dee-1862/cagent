"""python -m unstep.demo [--live [--mic]] [--port 8765] [--no-browser]."""
import argparse
import asyncio
import socket
import webbrowser

import uvicorn

from .presenter import create_demo_app


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


async def serve(args):
    if not port_free(args.port):
        # Check before the live warm-up, which takes about 30 s.
        raise SystemExit(f"Port {args.port} is busy: is presenter mode already running? "
                         f"Open http://127.0.0.1:{args.port}/demo/ or pass --port.")
    server = uvicorn.Server(uvicorn.Config(create_demo_app(live=args.live, mic=args.mic),
        host="127.0.0.1", port=args.port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started and not task.done():
        await asyncio.sleep(.05)
    if server.started:
        url = f"http://127.0.0.1:{args.port}/demo/"
        mode = "LIVE" if args.live else "REPLAY / fakes"
        if args.mic:
            mode += ", live mic: hold V to talk"
        print(f"Unstep presenter: {url} ({mode})")
        if not args.no_browser:
            webbrowser.open(url)
    await task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--mic", action="store_true",
                        help="presenter speaks the controller and pilot lines live (hold V); needs --live")
    args = parser.parse_args()
    if args.mic and not args.live:
        parser.error("--mic needs --live: live speech goes to Cartesia STT")
    asyncio.run(serve(args))


if __name__ == "__main__":
    main()
