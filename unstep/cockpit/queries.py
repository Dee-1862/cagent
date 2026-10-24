"""Pilot voice queries (task A10), text in and text out. STT and TTS are wired in later.

Intents: last clearance, say again, which taxiway. Answers come from the Moss
flight session, with the source record and search time. Unmatched questions may
use an injected answerer with locally retrieved, validated record quotes.

"Latest" always means newest by `ts` from a filter-only fetch, never the best
ranked search hit. "Say again" never reads back an unapproved "Likely" hint.
Any memory error (Moss offline) answers "No record found" instead of crashing.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Literal, Optional

from unstep.clock import now_ms
from unstep.cockpit.hint import names_other_aircraft
from unstep.cockpit.inference import Answerer
from unstep.cockpit.memory import Doc, Memory
from unstep.cockpit.seed import COCKPIT
from unstep.contracts import PilotQuery

log = logging.getLogger("unstep.queries")

Intent = Literal["recent", "last_clearance", "say_again", "taxi_route", "unknown"]

NO_RECORD = "Advisory. No record found. Ask the controller."
SAY_AGAIN = "Advisory. Say again."

# Order matters: "repeat the last clearance" is a last-clearance question, not a say again.
_INTENTS: list[tuple[Intent, re.Pattern]] = [
    # "What did the tower tell me in the last minute?", "what did I miss?" (P4: Moss session search)
    ("recent", re.compile(r"\b(last|past) (minute|\d+ (seconds?|minutes?)|few minutes)\b"
                          r"|\bwhat did (the )?tower (say|tell)|\bwhat did i miss\b")),
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


RECENT_WINDOW_MS = 60_000
NOTHING_RECENT = "Advisory. Nothing heard for you on the frequency in that time. Ask the controller."


def recent_window_ms(question: str) -> int:
    """'last 2 minutes' -> 120000, 'last 30 seconds' -> 30000, otherwise one minute."""
    m = re.search(r"\b(\d+) (second|minute)s?\b", question.lower())
    if not m:
        return 3 * 60_000 if "few minutes" in question.lower() else RECENT_WINDOW_MS
    return min(int(m[1]) * (1000 if m[2] == "second" else 60_000), 30 * 60_000)


async def _recent(memory: Memory, flight_index: str, callsign: str, question: str,
                  now: Optional[int] = None) -> tuple[str, Optional[Doc], float]:
    """What this cockpit heard in the last window: a Moss session search filtered on ts.

    Semantic search ranks the heard transmissions against the question; the answer then
    reads the newest matches, oldest first. Only what this cockpit actually heard is
    indexed, so a stepped-on call comes back with its gaps, never the tower's full text.
    """
    since = (now or now_ms()) - recent_window_ms(question)
    clauses: list[dict] = [{"callsign": {"$eq": callsign}}, {"type": {"$eq": "heard"}}, {"ts": {"$gte": since}}]
    if "tower" in question.lower():
        clauses.append({"speaker": {"$eq": "atc"}})
    flt = {"$and": clauses}
    res = await memory.query(flight_index, question, top_k=5, filter=flt)
    moss_ms = res.time_taken_ms
    docs = res.docs
    if not docs:  # nothing ranked (keyword stand-in offline): every heard doc in the window
        fetched = await memory.fetch(flight_index, filter=flt)
        moss_ms += fetched.time_taken_ms
        docs = fetched.docs
    docs = [d for d in docs if not names_other_aircraft(d.text, callsign)]
    if not docs:
        return NOTHING_RECENT, None, moss_ms
    newest = sorted(docs, key=_ts, reverse=True)[:2]
    parts = []
    for d in reversed(newest):
        note = " (stepped on, words missing)" if str(d.metadata.get("stepped_on")).lower() == "true" else ""
        parts.append(f"\"{d.text}\" at {_hhmm(_ts(d))}{note}")
    who = "Heard from tower" if "tower" in question.lower() else "Heard on frequency"
    answer = f"Advisory. {who} in the last {recent_window_ms(question) // 1000} seconds: " + "; then ".join(parts) + "."
    return answer, newest[0], moss_ms


def _clearance_answer(doc: Doc) -> str:
    return f"Advisory. Last clearance: {doc.text}, issued {_hhmm(_ts(doc))}."


async def _answer(memory: Memory, flight_index: str, callsign: str, intent: Intent, question: str = ""):
    answer, source, moss_ms = NO_RECORD, None, None

    if intent == "recent":
        answer, source, moss_ms = await _recent(memory, flight_index, callsign, question)
    elif intent == "last_clearance":
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


def quoted_source(answer: str, records: list[Doc]) -> Optional[Doc]:
    """Accept only an attributable quote, never an invented prefix or suffix.

    Requiring the whole quote to occur in a record is stronger than a three-word
    overlap, which could otherwise launder an invented clearance beside a quote.
    """
    match = re.fullmatch(r'(?:Recorded: )?["“]([^"“”\n]+)["”][.]?', answer)
    if not match:
        return None
    quote = " ".join(match[1].casefold().split())
    if len(re.findall(r"\b\w+\b", quote)) < 3:
        return None
    for doc in records:
        text = " ".join(doc.text.casefold().split())
        if re.search(r"(?<!\w)" + re.escape(quote) + r"(?!\w)", text):
            return doc
    return None


async def _freeform(memory, flight_index, airport_index, callsign, question, answerer, metrics):
    # Only approved flight clearances, never a local 'Likely' advisory.
    flight, moss_ms = await _all(memory, flight_index, callsign, "clearance")
    flight = [d for d in flight if d.metadata.get("callsign") == callsign
              and d.metadata.get("type") == "clearance"]
    records = [Doc(f"{flight_index}/{d.id}", d.text, d.metadata) for d in flight[:3]]
    if airport_index:
        airport = await memory.query(airport_index, question, top_k=3)
        moss_ms += airport.time_taken_ms
        records.extend(Doc(f"{airport_index}/{d.id}", d.text, d.metadata)
                       for d in airport.docs[:3] if not names_other_aircraft(d.text, callsign))
    if not records:
        return "No record found.", None, moss_ms
    result = await answerer.answer(question, records)
    if metrics is not None and result.first_token_ms is not None:
        metrics["llm_first_token_ms"] = result.first_token_ms
    answer = result.text.strip()
    if answer == "No record found.":
        return answer, None, moss_ms
    source = quoted_source(answer, records)
    if source is None:
        return NO_RECORD, None, moss_ms
    if airport_index and source.id.startswith(f"{airport_index}/"):
        # Airport procedures and NOTAMs must never sound like a clearance.
        answer = "Airport information, not a clearance: " + answer.removeprefix("Recorded: ")
    return answer, source, moss_ms


async def answer_query(memory: Memory, flight_index: str, callsign: str, question: str,
                       query_id: Optional[str] = None, *, airport_index: Optional[str] = None,
                       answerer: Optional[Answerer] = None,
                       metrics: Optional[dict[str, float]] = None) -> PilotQuery:
    intent = classify_intent(question)
    if not question.strip():
        # Nothing was understood: ask again, never answer a question nobody asked.
        return PilotQuery(query_id=query_id or f"q-{now_ms()}", callsign=callsign, question=question,
                          answer=SAY_AGAIN, source_doc_id=None, moss_ms=None)
    try:
        if intent == "unknown" and answerer is not None:
            answer, source, moss_ms = await asyncio.wait_for(
                _freeform(memory, flight_index, airport_index, callsign, question, answerer, metrics),
                timeout=5.0,  # a slightly cold Moss Inference needs more than 3 s
            )
        else:
            answer, source, moss_ms = await _answer(memory, flight_index, callsign, intent, question)
    except Exception:  # Moss offline or session closed: say so rather than crash
        log.warning("pilot query failed; answering no record", exc_info=True)
        answer, source, moss_ms = NO_RECORD, None, None

    return PilotQuery(
        query_id=query_id or f"q-{now_ms()}",
        callsign=callsign,
        question=question,
        answer=answer,
        source_doc_id=(source.id if intent == "unknown" else f"{flight_index}/{source.id}") if source else None,
        moss_ms=round(moss_ms, 3) if moss_ms is not None else None,
    )
