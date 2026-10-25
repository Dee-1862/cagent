"""Context for the console's Clearance agent: each plane's flight plan, stored in Elastic, and the last
thing the tower told it, from the plane's own Moss session.

The decision itself stays with fixed rules in the console (web/live/atc/clearance.js): the agent reads
these facts, proposes a clearance, and the controller sends it. A plane's plan is created in Elastic on
first request (departure, runway alternating 33/15 so both ends get used, via Bravo) and then kept for the
flight. Without Elastic the plans live in memory, labelled "local".
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

import httpx

from unstep.config import elastic_settings

log = logging.getLogger("unstep.flightplans")

FLIGHTPLAN_INDEX = "unstep-flightplans"
RUNWAYS = ("33", "15")
NUMBER_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "tree": "3", "four": "4", "fower": "4",
                "five": "5", "fife": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "niner": "9"}


def default_plan(callsign: str, order: int) -> dict:
    runway = RUNWAYS[order % len(RUNWAYS)]
    return {"callsign": callsign, "kind": "departure", "runway": runway, "route": "Bravo",
            "summary": f"departure, runway {runway} via Bravo"}


def digits_of(text: str) -> str:
    """"Cessna one two three" and "Cessna 1-2-3" both give "123"."""
    return "".join(NUMBER_WORDS.get(w, re.sub(r"\D", "", w)) for w in re.split(r"[^a-z0-9]+", (text or "").lower()))


class FlightPlans:
    def __init__(self, settings: Optional[tuple[str, str]] = None, timeout_s: float = 8.0):
        self.settings = settings if settings is not None else elastic_settings()
        self.timeout_s = timeout_s
        self.local: dict[str, dict] = {}
        self.cached: dict[str, dict] = {}  # read from Elastic once per flight; a plan doesn't change mid-flight
        self._client: Optional[httpx.AsyncClient] = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:  # one kept-alive connection: no TLS handshake per request
            self._client = httpx.AsyncClient(headers={"Authorization": f"ApiKey {self.settings[1]}"}, timeout=self.timeout_s)
        return self._client

    async def get(self, callsign: str, order: int) -> dict:
        """The plane's plan with where it came from ("elastic" or "local") and how long it took."""
        started = time.perf_counter()
        ms = lambda: round((time.perf_counter() - started) * 1000, 1)  # noqa: E731
        if callsign in self.cached:
            return {**self.cached[callsign], "source": "elastic", "cached": True, "ms": ms()}
        if self.settings:
            base = f"{self.settings[0].rstrip('/')}/{FLIGHTPLAN_INDEX}/_doc/{callsign}"
            try:
                r = await self._http().get(base)
                if r.status_code == 200:
                    self.cached[callsign] = r.json()["_source"]
                    return {**self.cached[callsign], "source": "elastic", "ms": ms()}
                plan = default_plan(callsign, order)
                w = await self._http().put(base + "?refresh=wait_for", json=plan)
                w.raise_for_status()
                self.cached[callsign] = plan
                return {**plan, "source": "elastic", "created": True, "ms": ms()}
            except Exception:
                log.warning("flight plan from Elastic failed for %s; using a local plan", callsign, exc_info=True)
        plan = self.local.setdefault(callsign, default_plan(callsign, order))
        return {**plan, "source": "local", "ms": ms()}

    def forget(self, callsign: str) -> None:
        """A new flight in the same seat reads its plan again."""
        self.cached.pop(callsign, None)


async def last_tower_call(edge, spoken: str = "") -> Optional[dict]:
    """The newest tower transmission addressed to this plane, from its own memory (Moss when live).
    Calls to other planes on the shared frequency are skipped."""
    mine = digits_of(spoken or getattr(edge, "callsign", ""))
    try:
        res = await edge.memory.fetch(edge.flight_idx, filter={"$and": [{"speaker": {"$eq": "atc"}}]},
                                      sort_by="ts", ascending=False, limit=20)
    except Exception:
        log.warning("plane memory lookup failed", exc_info=True)
        return None
    doc = next((d for d in res.docs if not mine or mine in digits_of(d.text)), None)
    return {"text": doc.text if doc else None, "ts": (doc.metadata or {}).get("ts") if doc else None,
            "ms": round(res.time_taken_ms, 3), "backend": res.backend}
