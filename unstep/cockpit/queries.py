"""Pilot voice queries (task A10), text in and text out. STT and TTS are wired in later.

Intents: last clearance, say again, which taxiway. Answers come from the Moss
flight session, with the source record and search time. Unknown or unmatched
questions get "Advisory. No record found. Ask the controller."
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal, Optional

from unstep.clock import now_ms
from unstep.cockpit.memory import Doc, Memory
from unstep.cockpit.seed import COCKPIT
from unstep.contracts import PilotQuery

Intent = Literal["last_clearance", "say_again", "taxi_route", "unknown"]

NO_RECORD = "Advisory. No record found. Ask the controller."

_INTENTS: list[tuple[Intent, re.Pattern]] = [
    ("say_again", re.compile(r"\b(say again|repeat( that)?|what did (you|it) say)\b")),
    ("taxi_route", re.compile(r"\b(which|what) (taxiway|route)\b|\btaxi (route|via)\b|\bwhere do i taxi\b")),
    ("last_clearance", re.compile(r"\b(last|latest|current|my) (clearance|instruction)\b")),
]


def classify_intent(question: str) -> Intent:
    q = question.lower()
    for intent, pattern in _INTENTS:
        if pattern.search(q):
            return intent
    return "unknown"


def _ts(doc: Doc) -> float:
    try:
        return float(doc.metadata.get("ts", 0))
    except (TypeError, ValueError):
        return 0.0


def _hhmm(ts_ms: float) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%H%M") + " Zulu"


async def record(memory: Memory, flight_index: str, callsign: str, doc_id: str, text: str,
                 kind: Literal["clearance", "advisory"], ts: Optional[int] = None) -> None:
    """Add an approved directive (clearance) or a spoken advisory to the flight session."""
    await memory.add_docs(
        flight_index,
        [Doc(id=doc_id, text=text, metadata={"callsign": callsign, "type": kind, "ts": ts or now_ms()})],
        writer=COCKPIT,
    )


async def _latest(memory: Memory, flight_index: str, callsign: str, kind: str, text: str) -> tuple[Optional[Doc], float]:
    res = await memory.query(
        flight_index, text, top_k=10, alpha=0.5,
        filter={"$and": [{"callsign": {"$eq": callsign}}, {"type": {"$eq": kind}}]},
    )
    docs = sorted(res.docs, key=_ts, reverse=True)
    return (docs[0] if docs else None), res.time_taken_ms


async def answer_query(memory: Memory, flight_index: str, callsign: str, question: str,
                       query_id: Optional[str] = None) -> PilotQuery:
    intent = classify_intent(question)
    answer, source, moss_ms = NO_RECORD, None, None

    if intent == "last_clearance":
        doc, moss_ms = await _latest(memory, flight_index, callsign, "clearance", "clearance runway taxi hold")
        if doc:
            answer, source = f"Advisory. Last clearance: {doc.text}, issued {_hhmm(_ts(doc))}.", doc
    elif intent == "say_again":
        doc, moss_ms = await _latest(memory, flight_index, callsign, "advisory", "advisory transmission")
        if doc:
            answer, source = doc.text, doc
    elif intent == "taxi_route":
        res = await memory.query(
            flight_index, "taxi via route", top_k=10, alpha=0.3,
            filter={"$and": [{"callsign": {"$eq": callsign}}, {"type": {"$eq": "clearance"}}]},
        )
        moss_ms = res.time_taken_ms
        routes = sorted((d for d in res.docs if re.search(r"\btaxi via\b", d.text, re.I)), key=_ts, reverse=True)
        if routes:
            m = re.search(r"taxi via ([\w ,]+?)(?:[.,]|$)", routes[0].text, re.I)
            rwy = re.search(r"runway\s+(\d{1,2}[LRC]?)", routes[0].text, re.I)
            route = m.group(1).strip() if m else routes[0].text
            to = f" to Runway {rwy.group(1)}" if rwy else ""
            answer, source = f"Advisory. Taxi via {route}{to}.", routes[0]

    return PilotQuery(
        query_id=query_id or f"q-{now_ms()}",
        callsign=callsign,
        question=question,
        answer=answer,
        source_doc_id=f"{flight_index}/{source.id}" if source else None,
        moss_ms=round(moss_ms, 3) if moss_ms is not None else None,
    )
