"""Local hint (task A4): the cockpit's own guess at a blocked instruction.

PRD local hint rules:
- Always "Likely ..." and "Awaiting controller." Never phrased as a clearance.
- Restrictive instructions only (hold short, stop, hold position, go around).
  Anything permissive gets no hint (M-014).
- Every hint has a source Moss record. No source, no hint.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from unstep.cockpit.memory import Doc, Memory
from unstep.contracts import LocalHint

Kind = Literal["restrictive", "permissive", "unknown"]

# Checked first: if any permissive phrase appears, the whole thing is permissive.
PERMISSIVE = (
    "cleared for takeoff", "cleared for the option", "cleared to land", "cleared for landing",
    "cross runway", "line up and wait", "position and hold", "taxi into position",
    "cleared for", "cleared to",
)
RESTRICTIVE = ("hold short", "hold position", "stop", "go around", "hold")

# Fragment words that suggest the blocked call was a permission, so we don't guess.
PERMISSIVE_FRAGMENTS = ("cleared", "takeoff", "land", "cross", "line up", "position")

MIN_SCORE = 0.05


def classify(text: str) -> Kind:
    t = text.lower()
    if any(p in t for p in PERMISSIVE):
        return "permissive"
    if any(re.search(rf"\b{re.escape(r)}\b", t) for r in RESTRICTIVE):
        return "restrictive"
    return "unknown"


_RUNWAY = re.compile(r"\brunway\s+(\d{1,2}[LRC]?)\b", re.I)


def likely_instruction(source: str) -> Optional[str]:
    """Derive the likely next instruction from an earlier clearance.

    - Taxi to a runway ("Runway 33, taxi via Bravo"): the aircraft must stop at that
      runway, so the likely instruction is "hold short Runway 33".
    - An earlier hold short is likely being repeated.
    - Anything else: no guess.
    """
    s = source.lower()
    if classify(source) == "permissive":
        return None
    m = _RUNWAY.search(source)
    if not m:
        return None
    runway = m.group(1).upper()
    if "hold short" in s or "taxi" in s:
        return f"hold short Runway {runway}"
    return None


def none_hint(moss_ms: Optional[float] = None) -> LocalHint:
    return LocalHint(kind="none", moss_ms=moss_ms)


async def derive_hint(
    memory: Memory,
    callsign: str,
    heard_text: str,
    flight_index: str,
    airport_index: str,
    since_ts: Optional[int] = None,
) -> LocalHint:
    """Search the flight session (and confirm in the airport index) for a safe hint."""
    if any(w in heard_text.lower() for w in PERMISSIVE_FRAGMENTS):
        return none_hint()

    fragment = re.sub(r"\[.*?\]", " ", heard_text)
    flt: dict = {"$and": [{"callsign": {"$eq": callsign}}, {"type": {"$eq": "clearance"}}]}
    if since_ts is not None:
        flt["$and"].append({"ts": {"$gte": since_ts}})

    # Keyword-leaning: callsigns and runway numbers matter more than meaning here.
    res = await memory.query(flight_index, f"{fragment} runway taxi hold short", top_k=3, alpha=0.4, filter=flt)
    moss_ms = res.time_taken_ms

    best: Optional[Doc] = None
    for doc in sorted(res.docs, key=lambda d: (d.score, _ts(d)), reverse=True):
        if doc.score >= MIN_SCORE and likely_instruction(doc.text):
            best = doc
            break
    if best is None:
        return none_hint(moss_ms)

    text = likely_instruction(best.text)
    if text is None or classify(text) != "restrictive":
        return none_hint(moss_ms)

    # Confirm the runway exists at this airport before speaking it.
    runway = _RUNWAY.search(text).group(1)
    check = await memory.query(airport_index, f"Runway {runway}", top_k=3, alpha=0.2, filter={"type": {"$eq": "runway"}})
    moss_ms += check.time_taken_ms
    if not any(re.search(rf"\b{runway}\b", d.text, re.I) for d in check.docs):
        return none_hint(moss_ms)

    return LocalHint(
        text=text,
        kind="restrictive",
        source_doc_id=f"{flight_index}/{best.id}",
        source_text=best.text,
        moss_ms=round(moss_ms, 3),
    )


def advisory_text(hint: LocalHint) -> str:
    """What the pilot hears before any controller approval."""
    if hint.kind == "restrictive" and hint.text:
        return f"Advisory. Transmission blocked. Likely {hint.text}. Awaiting controller."
    return "Advisory. Transmission blocked. Awaiting controller."


def _ts(doc: Doc) -> float:
    try:
        return float(doc.metadata.get("ts", 0))
    except (TypeError, ValueError):
        return 0.0
