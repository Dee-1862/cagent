"""The passcode gate for a hosted hub.

On a public address, the tower's pages and the endpoints behind them must not answer a stranger: the console page and
`/live/pilot-link` carry the room code, and `/live/ask-audit`, `/live/reports/run` and `/live/geo/positions` spend
Elastic and write to it. When `UNSTEP_ATC_PASSWORD` is set, every such path asks for it with HTTP Basic (any user
name, the passcode as the password), so a browser asks once and then sends it by itself.

Open on purpose: `/health` (hosting checks), `/pilot/` (the phone app is only static files), `/live/static/` (the
console's scripts and models), `/live/stations`, `/live/join` (needs the room code), and the sockets (the room code,
and the tower password sent inside the socket). With no password set nothing is gated, so a local run is unchanged.
"""

from __future__ import annotations

import base64
import hmac

from unstep.config import env

# Exact paths, and path prefixes, that belong to the tower.
GATED_PATHS = {"/", "/live/pilot-link", "/live/addresses", "/live/pi-join", "/live/qr.svg", "/live/stats",
               "/live/ask-audit", "/live/reports", "/live/flightlog"}
GATED_PREFIXES = ("/live/atc", "/live/record", "/demo", "/live/reports/", "/live/clearance-context/", "/live/geo/")
REALM = "Unstep tower"


def is_gated(path: str) -> bool:
    return path in GATED_PATHS or path.startswith(GATED_PREFIXES)


def passcode_ok(authorization: str | None, passcode: str) -> bool:
    """True for `Authorization: Basic base64(user:passcode)` with the right passcode (the user name is ignored)."""
    if not authorization or not authorization.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:].strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    supplied = decoded.partition(":")[2]  # everything after the first colon: a passcode may contain colons
    return hmac.compare_digest(supplied.encode("utf-8"), passcode.encode("utf-8"))


class PasscodeGate:
    """Pure ASGI middleware: 401 with a Basic challenge for a gated path without the passcode."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        passcode = env("UNSTEP_ATC_PASSWORD") if scope["type"] == "http" else None
        if passcode and scope["method"] != "OPTIONS" and is_gated(scope["path"]):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            if not passcode_ok(headers.get("authorization"), passcode):
                body = b"Passcode required"
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"www-authenticate", f'Basic realm="{REALM}", charset="UTF-8"'.encode()),
                                        (b"content-type", b"text/plain; charset=utf-8"),
                                        (b"content-length", str(len(body)).encode()),
                                        (b"cache-control", b"no-store")]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
