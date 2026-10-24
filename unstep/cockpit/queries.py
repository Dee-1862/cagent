"""Pilot voice queries (task A10), text in and text out. STT and TTS are wired in later.

Intents: last clearance, say again, which taxiway. Answers come from the Moss
flight session, with the source record and search time. Unknown or unmatched
questions get "Advisory. No record found. Ask the controller."

"Latest" always means newest by `ts` from a filter-only fetch, never the best
ranked search hit. "Say again" never reads back an unapproved "Likely" hint.
Any memory error (Moss offline) answers "No record found" instead of crashing.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Literal, Optional

from unstep.clock import now_ms
from unstep.cockpit.hint import names_other_aircraft
from unstep.cockpit.memory import Doc, Memory
from unstep.cockpit.seed import COCKPIT
from unstep.contracts import PilotQuery

log = logging.getLogger("unstep.queries")

Intent = Literal["last_clearance", "say_again", "taxi_route", "unknown"]

NO_RECORD = "Advisory. No record found. Ask the controller."

# Order matters: "repeat the last clearance" is a last-clearance question, not a say again.
_INTENTS: list[tuple[Intent, re.Pattern]] = [
    ("last_clearance", re.compile(r"\b(last|latest|current|my) (clearance|instruction)\b")),
    ("taxi_route", re.compile(r"\b(which|what) (taxiway|route)\b|\btaxi (route|via)\b|\bwhere do i taxi\b")),
    ("say_again", re.compile(r"\b(say again|repeat( that)?|what did (you|it) say)\b")),
]

_LIKELY = re.compile(r"\s*Likely [^.]*\.", re.I)


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
                 kind: Literal["clearance", "advisory"], ts: Optional[int] = None) -> str:
    """Add an approved directive (clearance) or a spoken advisory to the flight session.

    Never overwrites: if `doc_id` already exists the record gets a versioned id
    (`<id>-v2`, `-v3`, ...). Returns the id actually written.
    """
    has_doc = getattr(memory, "has_doc", None)
    new_id = doc_id
    if has_doc is not None:
        n = 1
        while await has_doc(flight_index, new_id):
            n += 1
            new_id = f"{doc_id}-v{n}"
        if new_id != doc_id:
            log.warning("record %s already exists in %s; writing %s instead", doc_id, flight_index, new_id)
    await memory.add_docs(
        flight_index,
        [Doc(id=new_id, text=text, metadata={"callsign": callsign, "type": kind, "ts": ts or now_ms()})],
        writer=COCKPIT,
    )
    return new_id


async def _all(memory: Memory, flight_index: str, callsign: str, kind: str) -> tuple[list[Doc], float]:
    """Every record of `kind` for this aircraft, newest first (filter-only, no ranking)."""
    res = await memory.fetch(
        flight_index,
        filter={"$and": [{"callsign": {"$eq": callsign}}, {"type": {"$eq": kind}}]},
    )
    docs = [d for d in res.docs if not names_other_aircraft(d.text, callsign)]
    return sorted(docs, key=_ts, reverse=True), res.time_taken_ms


def _clearance_answer(doc: Doc) -> str:
    return f"Advisory. Last clearance: {doc.text}, issued {_hhmm(_ts(doc))}."


async def _answer(memory: Memory, flight_index: str, callsign: str, intent: Intent):
    answer, source, moss_ms = NO_RECORD, None, None

    if intent == "last_clearance":
        docs, moss_ms = await _all(memory, flight_index, callsign, "clearance")
        if docs:
            answer, source = _clearance_answer(docs[0]), docs[0]
    elif intent == "say_again":
        clearances, ms1 = await _all(memory, flight_index, callsign, "clearance")
        advisories, ms2 = await _all(memory, flight_index, callsign, "advisory")
        moss_ms = ms1 + ms2
        clr = clearances[0] if clearances else None
        adv = advisories[0] if advisories else None
        if adv is not None and (clr is None or _ts(adv) > _ts(clr)):
            # Repeat the advisory as an advisory, without its unapproved "Likely" guess.
            text = _LIKELY.sub("", adv.text).strip()
            if not text.lower().startswith("advisory"):
                text = f"Advisory. {text}"
            answer, source = text, adv
        elif clr is not None:
            # A newer approved clearance supersedes any earlier hint.
            answer, source = _clearance_answer(clr), clr
    elif intent == "taxi_route":
        docs, moss_ms = await _all(memory, flight_index, callsign, "clearance")
        routes = [d for d in docs if re.search(r"\btaxi via\b", d.text, re.I)]
        if routes:
            m = re.search(r"taxi via ([\w ,]+?)(?:[.,]|$)", routes[0].text, re.I)
            rwy = re.search(r"runway\s+(\d{1,2}[LRC]?)", routes[0].text, re.I)
            route = m.group(1).strip() if m else routes[0].text
            to = f" to Runway {rwy.group(1)}" if rwy else ""
            answer, source = f"Advisory. Taxi via {route}{to}.", routes[0]
    return answer, source, moss_ms


async def answer_query(memory: Memory, flight_index: str, callsign: str, question: str,
                       query_id: Optional[str] = None) -> PilotQuery:
    intent = classify_intent(question)
    try:
        answer, source, moss_ms = await _answer(memory, flight_index, callsign, intent)
    except Exception:  # Moss offline or session closed: say so rather than crash
        log.exception("pilot query failed; answering no record")
        answer, source, moss_ms = NO_RECORD, None, None

    return PilotQuery(
        query_id=query_id or f"q-{now_ms()}",
        callsign=callsign,
        question=question,
        answer=answer,
        source_doc_id=f"{flight_index}/{source.id}" if source else None,
        moss_ms=round(moss_ms, 3) if moss_ms is not None else None,
    )
