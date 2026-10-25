"""Cartesia HTTP 429 handling shared by the STT and TTS sockets.

Cartesia documents two 429 causes (docs.cartesia.ai, "Concurrency Limits and
Timeouts"): too many active generations for the plan, and too many open
WebSockets (10x the concurrency limit; the docs say this is usually unclosed
idle connections). Both look the same to us, so we only back off and say so.

To tell the two apart next time, every 429 is logged with its status, the
response body (truncated, secrets removed, never any headers) and how many
sockets this process holds open. The STT and TTS classes keep that count with
`socket_opened` / `socket_closed`. A leak shows as a count that keeps growing;
a plan limit shows as a 429 at a low, steady count.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import deque

log = logging.getLogger("unstep.cartesia")

BODY_LIMIT = 500  # characters of a 429 body that we keep
_ALLOWED_EVENT_FIELDS = ("status_code", "error_code", "title", "message", "type")


class CartesiaRateLimited(RuntimeError):
    """HTTP 429 from Cartesia, on the handshake or as a WebSocket error event.

    `status` and `body` are what Cartesia sent (body truncated and redacted);
    `open_sockets` is how many sockets this process held when it happened."""

    def __init__(self, message: str, status: int = 429, body: str = "", open_sockets: int | None = None):
        super().__init__(message)
        self.status = status
        self.body = body
        self.open_sockets = open_sockets


def is_rate_limited(exc: BaseException) -> bool:
    if isinstance(exc, CartesiaRateLimited):
        return True
    response = getattr(exc, "response", None)  # websockets InvalidStatus
    return getattr(response, "status_code", None) == 429


# ---------------------------------------------------------------- open socket count

_open: dict[str, int] = {}


def socket_opened(kind: str) -> None:
    _open[kind] = _open.get(kind, 0) + 1


def socket_closed(kind: str) -> None:
    _open[kind] = max(0, _open.get(kind, 0) - 1)


def open_socket_count() -> int:
    """Sockets this process opened through our STT and TTS classes and has not closed."""
    return sum(_open.values())


def open_socket_counts() -> dict[str, int]:
    return {k: v for k, v in _open.items() if v}


# ---------------------------------------------------------------- what a 429 looked like

RATE_LIMIT_EVENTS: deque = deque(maxlen=50)  # newest last; scripts read and clear it


def redact(text: str) -> str:
    """Remove anything that looks like our key, and any Bearer token, before text is logged."""
    key = os.environ.get("CARTESIA_API_KEY")
    if key:
        text = text.replace(key, "[redacted]")
    return re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", text)


def _body_text(source) -> str:
    """The body of a 429: a websockets InvalidStatus response body, or a TTS error event dict."""
    if isinstance(source, dict):  # error event: keep only the fields that describe the error
        return json.dumps({k: source[k] for k in _ALLOWED_EVENT_FIELDS if k in source}, ensure_ascii=False)
    response = getattr(source, "response", None)
    body = getattr(response, "body", None)
    if body is None:
        body = getattr(source, "body", None)
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    return body if isinstance(body, str) else ""


def rate_limit_detail(source, where: str = "") -> dict:
    """Status, body and open-socket count for one 429. `source` is an exception or an error event dict.
    Never includes headers."""
    if isinstance(source, CartesiaRateLimited):
        body = source.body
    else:
        body = _body_text(source)
    body = redact(body)[:BODY_LIMIT]
    return {"where": where, "status": 429, "body": body, "open_sockets": open_socket_count(),
            "open_by_kind": open_socket_counts(), "at": time.strftime("%H:%M:%S")}


def log_rate_limited(source, where: str = "") -> dict:
    """Log one 429 (status, body, open sockets), remember it in RATE_LIMIT_EVENTS and return the detail."""
    detail = rate_limit_detail(source, where)
    RATE_LIMIT_EVENTS.append(detail)
    log.warning("Cartesia 429 %s: status=%s body=%r open_sockets=%s %s", detail["where"] or "?", detail["status"],
                detail["body"], detail["open_sockets"], detail["open_by_kind"])
    return detail


def rate_limited_from_event(msg: dict, where: str = "tts") -> CartesiaRateLimited:
    """Build (and log) the exception for a WebSocket error event whose status_code is 429."""
    detail = log_rate_limited(msg, where)
    return CartesiaRateLimited(f"Cartesia {where.upper()} rate limited: {msg.get('title')}: {msg.get('message')}",
                               body=detail["body"], open_sockets=detail["open_sockets"])


async def connect_with_backoff(open_socket, attempts: int = 3, base_delay_s: float = 0.5):
    """Await `open_socket()`; on a 429 handshake wait and retry, then raise CartesiaRateLimited."""
    for attempt in range(1, attempts + 1):
        try:
            return await open_socket()
        except Exception as exc:
            if not is_rate_limited(exc):
                raise
            detail = log_rate_limited(exc, f"handshake attempt {attempt}")
            if attempt == attempts:
                raise CartesiaRateLimited(
                    "Cartesia answered HTTP 429 to the WebSocket handshake; close idle sockets "
                    "or lower concurrency (see docs/24-cartesia-findings.md)",
                    body=detail["body"], open_sockets=detail["open_sockets"]) from exc
            await asyncio.sleep(base_delay_s * 2 ** (attempt - 1))
