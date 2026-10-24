"""Keyword tags for live captions (display only): which words are a callsign, an action, a runway or a taxiway.

Pure functions over the words as spoken or as Cartesia wrote them ("Cessna one two three",
"Cessna 1-2-3", "runway three three", "Runway 33", "via Bravo"). Every token of the input
comes back once, in order, with its original spelling and a kind or None, so the screen can
colour words in place without re-spacing the caption.
"""

from __future__ import annotations

import re

from unstep.cockpit.phraseology import ACTIONS, AIRCRAFT_TYPES, PHONETIC_LETTERS, SPOKEN_DIGITS, SIDES

KINDS = ("callsign", "action", "runway", "taxiway")
_AMBIGUOUS = {"to", "too", "for", "oh", "won"}
# Longest phrases first, so "cleared for takeoff" wins over "cleared".
# "cross runway" keeps "runway" for the runway tag, so the digits after it are tagged too.
_PHRASES = sorted({re.sub(r"\s+runway$", "", alias) for _, aliases in ACTIONS for alias in aliases},
                  key=lambda a: -len(a.split()))


def _norm(token: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", token.lower()).strip("-")


def _is_digit(n: str, strict: bool = True) -> bool:
    """'3', '33', '1-2-3', 'three', 'tree', 'niner'; 'to'/'for' only when strict is False."""
    if not n:
        return False
    if re.fullmatch(r"\d+(-\d+)*[lrc]?", n):
        return True
    return n in SPOKEN_DIGITS and (not strict or n not in _AMBIGUOUS)


def tag(text: str) -> list[dict]:
    """[{text, kind}] for every whitespace token of `text`."""
    raw = text.split()
    norm = [_norm(t) for t in raw]
    kinds: list[str | None] = [None] * len(raw)
    i = 0
    while i < len(raw):
        n = norm[i]
        # Actions (multi-word phrases)
        matched = False
        for phrase in _PHRASES:
            words = phrase.split()
            if norm[i:i + len(words)] == words:
                for k in range(i, i + len(words)):
                    kinds[k] = "action"
                i += len(words)
                matched = True
                break
        if matched:
            continue
        # Runway and its digits, side word included: "runway three three left", "Runway 33L"
        if n in ("runway", "rwy"):
            kinds[i] = "runway"
            j = i + 1
            while j < len(raw) and (_is_digit(norm[j], strict=False) or norm[j] in SIDES):
                kinds[j] = "runway"
                j += 1
            i = j
            continue
        # Taxiway: "taxiway Bravo", "via Bravo", "via B 2"
        if n in ("taxiway", "via") and i + 1 < len(raw) and (norm[i + 1] in PHONETIC_LETTERS
                                                              or re.fullmatch(r"[a-z]\d?", norm[i + 1])):
            if n == "taxiway":
                kinds[i] = "taxiway"
            j = i + 1
            while j < len(raw) and (norm[j] in PHONETIC_LETTERS or re.fullmatch(r"[a-z]\d?", norm[j])
                                    or _is_digit(norm[j])):
                kinds[j] = "taxiway"
                j += 1
            i = j
            continue
        # Callsign: aircraft type word plus its digits or letters, or a registration (N123AB)
        if n in AIRCRAFT_TYPES and i + 1 < len(raw) and (_is_digit(norm[i + 1]) or norm[i + 1] in PHONETIC_LETTERS):
            kinds[i] = "callsign"
            j = i + 1
            while j < len(raw) and (_is_digit(norm[j]) or norm[j] in PHONETIC_LETTERS):
                kinds[j] = "callsign"
                j += 1
            i = j
            continue
        if re.fullmatch(r"n\d{1,5}[a-z]{0,2}", n):
            kinds[i] = "callsign"
        i += 1
    return [{"text": t, "kind": k} for t, k in zip(raw, kinds)]


def keywords(text: str) -> list[dict]:
    """Only the tagged words, joined into phrases: [{text: "hold short", kind: "action"}, ...]."""
    result, prev_kind = [], None
    for w in tag(text):
        if w["kind"] is None:
            prev_kind = None
            continue
        if result and prev_kind == w["kind"]:
            result[-1]["text"] += " " + w["text"].strip(",.")
        else:
            result.append({"text": w["text"].strip(",."), "kind": w["kind"]})
        prev_kind = w["kind"]
    return result
