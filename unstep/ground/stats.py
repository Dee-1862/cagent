"""Live stats per frequency for the console (W4): blocked calls, readback errors, auto-relays.

With Elastic configured, the numbers come from ES|QL over the events index the
gateway writes (unstep/gateway/sink.py), and the query text goes back with them so
the console can show it. Without Elastic, or if the cluster doesn't answer, the
same numbers are counted from the room's own traces (backend "local").

Definitions:
  blocked_calls    AnomalyEvent on this frequency (a stepped-on call the cockpit detected)
  readback_errors  ReadbackResult with match false, for those events
  auto_resends     ApprovedDirective with approved_via "auto" (the policy agent re-sent
                   the controller's own words without asking), for those events

ReadbackResult and ApprovedDirective carry no frequency or callsign, so they are
joined to their AnomalyEvent by event_id here, after two small ES|QL queries.
Elastic counts can trail the room by a second or two (the sink writes in batches).
"""

from __future__ import annotations

import re
import time

import httpx

from unstep.clock import now_ms
from unstep.config import elastic_events_index, elastic_settings

_FREQ = re.compile(r"^[0-9]{2,3}(\.[0-9]{1,3})?$")


def esql_queries(frequency: str, since_ms: int, index: str | None = None) -> tuple[str, str]:
    """The two ES|QL queries. Values are checked and inlined (a frequency and an int), never free text."""
    if not _FREQ.match(frequency):
        raise ValueError(f"not a frequency: {frequency!r}")
    since_ms = int(since_ms)
    index = index or elastic_events_index()
    events = (f'FROM {index}\n| WHERE type == "AnomalyEvent" AND frequency == "{frequency}" AND ts >= {since_ms}\n'
              f"| STATS n = COUNT(*) BY event_id, callsign\n| LIMIT 1000")
    outcomes = (f'FROM {index}\n| WHERE ts >= {since_ms} AND type IN ("ReadbackResult", "ApprovedDirective")\n'
                f'| EVAL wrong = CASE(type == "ReadbackResult" AND match == false, 1, 0),\n'
                f'       auto = CASE(type == "ApprovedDirective" AND approved_via == "auto", 1, 0)\n'
                f"| STATS readback_errors = SUM(wrong), auto_resends = SUM(auto) BY event_id\n| LIMIT 1000")
    return events, outcomes


def _rows(body: dict) -> list[dict]:
    names = [c["name"] for c in body.get("columns", [])]
    return [dict(zip(names, row)) for row in body.get("values", [])]


def combine(events: list[dict], outcomes: list[dict]) -> dict:
    """Join outcome rows to this frequency's events by event_id and total per callsign."""
    owner = {e["event_id"]: e.get("callsign") or "unknown" for e in events}
    per: dict[str, dict] = {}
    for e in events:
        cs = owner[e["event_id"]]
        per.setdefault(cs, {"callsign": cs, "blocked": 0, "readback_errors": 0, "auto_resends": 0})
        per[cs]["blocked"] += 1
    for o in outcomes:
        cs = owner.get(o.get("event_id"))
        if cs is None:  # another frequency's event, or one from before since_ms
            continue
        per[cs]["readback_errors"] += int(o.get("readback_errors") or 0)
        per[cs]["auto_resends"] += int(o.get("auto_resends") or 0)
    rows = sorted(per.values(), key=lambda r: (-r["blocked"], r["callsign"]))
    return {"blocked_calls": sum(r["blocked"] for r in rows),
            "readback_errors": sum(r["readback_errors"] for r in rows),
            "auto_resends": sum(r["auto_resends"] for r in rows),
            "per_callsign": rows}


def local_stats(traces: dict, since_ms: int) -> dict:
    """The same numbers from the room's traces (one trace per detected blocked call)."""
    events, outcomes = [], []
    for t in traces.values():
        if t.get("created_ms", 0) < since_ms:
            continue
        events.append({"event_id": t["event_id"], "callsign": t.get("callsign")})
        decision = t.get("decision") or {}
        outcomes.append({"event_id": t["event_id"],
                         "readback_errors": sum(1 for r in t.get("readbacks", []) if r.get("match") is False),
                         "auto_resends": 1 if decision.get("approved_via") == "auto" else 0})
    return combine(events, outcomes)


async def frequency_stats(frequency: str, since_ms: int, traces: dict, *, settings=None,
                          transport: httpx.AsyncBaseTransport | None = None, timeout_s: float = 3.0) -> dict:
    """Stats for the console: from Elastic when configured and answering, else from the room."""
    since_ms = max(0, int(since_ms))
    events_q, outcomes_q = esql_queries(frequency, since_ms)
    out = {"frequency": frequency, "since_ms": since_ms, "window_s": round((now_ms() - since_ms) / 1000, 1),
           "esql": events_q + "\n\n" + outcomes_q}
    settings = settings if settings is not None else elastic_settings()
    if settings:
        url, key = settings
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(headers={"Authorization": f"ApiKey {key}"}, timeout=timeout_s,
                                         transport=transport) as client:
                bodies = []
                for q in (events_q, outcomes_q):
                    r = await client.post(f"{url.rstrip('/')}/_query", json={"query": q})
                    r.raise_for_status()
                    bodies.append(r.json())
            return {**out, "backend": "elastic", "took_ms": round((time.perf_counter() - started) * 1000, 1),
                    **combine(_rows(bodies[0]), _rows(bodies[1]))}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            out["elastic_error"] = type(exc).__name__
    return {**out, "backend": "local", "took_ms": None, **local_stats(traces, since_ms)}
