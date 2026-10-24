"""Local hint (task A4): the cockpit's own guess at a blocked instruction.

PRD local hint rules:
- Always "Likely ..." and "Awaiting controller." Never phrased as a clearance.
- Restrictive instructions only (hold short, stop, hold position, go around).
  Anything permissive gets no hint (M-014).
- Every hint has a source Moss record. No source, no hint.
- Only the newest taxi clearance for this aircraft counts, and only while it is
  recent. A superseded or stale clearance never produces a hint.
"""

from __future__ import annotations

import logging
import re
from typing import Literal, Optional

from unstep.clock import now_ms
from unstep.cockpit.memory import Doc, Memory
from unstep.cockpit.phraseology import callsigns_match, parse_callsign
from unstep.contracts import LocalHint

log = logging.getLogger("unstep.hint")

Kind = Literal["restrictive", "permissive", "unknown"]

# Checked first: if any permissive phrase appears, the whole thing is permissive.
PERMISSIVE = (
    "cleared for takeoff", "cleared for the option", "cleared to land", "cleared for landing",
    "cross runway", "line up and wait", "position and hold", "taxi into position",
    "cleared for", "cleared to",
)
RESTRICTIVE = ("hold short", "hold position", "stop", "go around", "hold")

# Fragment words that suggest the blocked call was a permission, so we don't guess.
# Matched on normalized text (see `normalize`). Any one of them means no hint.
PERMISSIVE_FRAGMENT = re.compile(
    r"\b(takeoff|take off|cleared|clear|depart\w*|cross\w*|line up|lineup|land\w*|option"
    r"|position and hold|into position)\b"
)
# Restrictive actions other than hold short. If the fragment carries one, a
# "hold short" guess from an old taxi clearance would be the wrong instruction.
OTHER_ACTION_FRAGMENT = re.compile(r"\b(go around|going around|hold position|holding position|stop)\b")

# A taxi clearance older than this is not trusted for a hint.
DEFAULT_MAX_AGE_MS = 15 * 60_000


def normalize(text: str) -> str:
    """Lowercase, drop [noise] markers, join hyphenated spellings ("C-LEARED", "1-2-3"), collapse spaces."""
    t = re.sub(r"\[.*?\]", " ", text.lower())
    t = re.sub(r"(?<=\w)-(?=\w)", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def classify(text: str) -> Kind:
    t = normalize(text)
    if any(p in t for p in PERMISSIVE) or re.search(r"\b(take ?off|line ?up)\b", t):
        return "permissive"
    if any(re.search(rf"\b{re.escape(r)}\b", t) for r in RESTRICTIVE):
        return "restrictive"
    return "unknown"


def fragment_is_permissive(heard_text: str) -> bool:
    return bool(PERMISSIVE_FRAGMENT.search(normalize(heard_text)))


_RUNWAY = re.compile(r"\brunway\s+(\d{1,2}[LRC]?)\b", re.I)
_HOLD_SHORT_RWY = re.compile(r"\bhold(?:ing)?\s+short\s+(?:of\s+)?(?:runway\s+)?(\d{1,2}[LRC]?)\b", re.I)
_CROSS_RWY = re.compile(r"\bcross(?:ing)?\s+(?:runway\s+)?(\d{1,2}[LRC]?)\b", re.I)


def likely_instruction(source: str) -> Optional[str]:
    """Derive the likely next instruction from an earlier clearance.

    - An explicit hold short ("..., hold short Runway 28L"): that runway, even if the
      clearance names another runway first.
    - Taxi to a runway ("Runway 33, taxi via Bravo"): the aircraft must stop at that
      runway, so the likely instruction is "hold short Runway 33".
    - Anything else: no guess.
    """
    if classify(source) == "permissive":
        return None
    m = _HOLD_SHORT_RWY.search(source)
    if m:
        return f"hold short Runway {m.group(1).upper()}"
    if not re.search(r"\btaxi\b", source, re.I):
        return None
    crossed = {c.upper() for c in _CROSS_RWY.findall(source)}
    for rwy in _RUNWAY.findall(source):
        if rwy.upper() not in crossed:
            return f"hold short Runway {rwy.upper()}"
    return None


def none_hint(moss_ms: Optional[float] = None) -> LocalHint:
    return LocalHint(kind="none", moss_ms=moss_ms)


def names_other_aircraft(text: str, callsign: str) -> bool:
    """True if the record text names a callsign that isn't this aircraft."""
    named = parse_callsign(text)
    return bool(named) and not callsigns_match(named, callsign)


def _is_movement_clearance(text: str) -> bool:
    """Clearances that say where the aircraft may go, so they supersede older taxi ones."""
    return bool(_RUNWAY.search(text)) or classify(text) != "unknown" or bool(re.search(r"\btaxi\b", text, re.I))


async def derive_hint(
    memory: Memory,
    callsign: str,
    heard_text: str,
    flight_index: str,
    airport_index: str,
    since_ts: Optional[int] = None,
    now: Optional[int] = None,
    max_age_ms: int = DEFAULT_MAX_AGE_MS,
) -> LocalHint:
    """Hint from the newest recent taxi clearance. Fails safe: any memory error gives no hint."""
    try:
        return await _derive_hint(memory, callsign, heard_text, flight_index, airport_index,
                                  since_ts, now, max_age_ms)
    except Exception:  # Moss offline, session not open, anything: no hint beats a crash
        log.exception("local hint failed; returning no hint")
        return none_hint()


async def _derive_hint(memory, callsign, heard_text, flight_index, airport_index, since_ts, now, max_age_ms):
    if fragment_is_permissive(heard_text) or OTHER_ACTION_FRAGMENT.search(normalize(heard_text)):
        return none_hint()

    flt: dict = {"$and": [{"callsign": {"$eq": callsign}}, {"type": {"$eq": "clearance"}}]}
    if since_ts is not None:
        flt["$and"].append({"ts": {"$gte": since_ts}})

    # Filter-only fetch, newest by ts: ranking must never revive a superseded clearance.
    res = await memory.fetch(flight_index, filter=flt)
    moss_ms = res.time_taken_ms
    candidates = [d for d in res.docs
                  if _is_movement_clearance(d.text) and not names_other_aircraft(d.text, callsign)]
    if not candidates:
        return none_hint(moss_ms)
    best = max(candidates, key=_ts)
    now = now_ms() if now is None else now
    if now - _ts(best) > max_age_ms:
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
