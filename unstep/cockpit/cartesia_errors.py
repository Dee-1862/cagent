"""Cartesia HTTP 429 handling shared by the STT and TTS sockets.

Cartesia documents two 429 causes (docs.cartesia.ai, "Concurrency Limits and
Timeouts"): too many active generations for the plan, and too many open
WebSockets (10x the concurrency limit; the docs say this is usually unclosed
idle connections). Both look the same to us, so we only back off and say so.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("unstep.cartesia")


class CartesiaRateLimited(RuntimeError):
    """HTTP 429 from Cartesia, on the handshake or as a WebSocket error event."""


def is_rate_limited(exc: BaseException) -> bool:
    if isinstance(exc, CartesiaRateLimited):
        return True
    response = getattr(exc, "response", None)  # websockets InvalidStatus
    return getattr(response, "status_code", None) == 429


async def connect_with_backoff(open_socket, attempts: int = 3, base_delay_s: float = 0.5):
    """Await `open_socket()`; on a 429 handshake wait and retry, then raise CartesiaRateLimited."""
    for attempt in range(1, attempts + 1):
        try:
            return await open_socket()
        except Exception as exc:
            if not is_rate_limited(exc):
                raise
            if attempt == attempts:
                raise CartesiaRateLimited(
                    "Cartesia answered HTTP 429 to the WebSocket handshake; close idle sockets "
                    "or lower concurrency (see docs/24-cartesia-findings.md)") from exc
            log.warning("Cartesia 429 on handshake (attempt %d); backing off", attempt)
            await asyncio.sleep(base_delay_s * 2 ** (attempt - 1))
