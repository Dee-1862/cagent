"""ATC phraseology: how Unstep says things, and how it reads what people said.

`normalize_for_speech` turns text into ATC pronunciation for TTS
("Runway 33" -> "runway tree tree"). `parse_instruction` pulls the slots
(callsign, action, runway) out of a transcript, tolerant of STT variants
("three three", "tree tree", "runway 33", "two three").
"""

from __future__ import annotations

import re
from typing import Optional

from unstep.contracts import Slots

DIGIT_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "tree", "4": "four",
    "5": "fife", "6": "six", "7": "seven", "8": "eight", "9": "niner",
}

SIDE_WORDS = {"L": "left", "R": "right", "C": "center"}

PHONETIC = {
    "A": "alpha", "B": "bravo", "C": "charlie", "D": "delta", "E": "echo", "F": "foxtrot",
    "G": "golf", "H": "hotel", "I": "india", "J": "juliett", "K": "kilo", "L": "lima",
    "M": "mike", "N": "november", "O": "oscar", "P": "papa", "Q": "quebec", "R": "romeo",
    "S": "sierra", "T": "tango", "U": "uniform", "V": "victor", "W": "whiskey", "X": "x-ray",
    "Y": "yankee", "Z": "zulu",
}

# Words an STT engine may produce for each digit.
SPOKEN_DIGITS = {
    "zero": "0", "oh": "0", "one": "1", "won": "1", "two": "2", "to": "2", "too": "2",
    "three": "3", "tree": "3", "four": "4", "fower": "4", "for": "4", "five": "5", "fife": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "niner": "9",
}
# "to", "too", "for" are only digits when next to another digit (handled in _digit_tokens).
AMBIGUOUS_DIGIT_WORDS = {"to", "too", "for", "oh", "won"}

SIDES = {"l": "L", "left": "L", "r": "R", "right": "R", "c": "C", "center": "C", "centre": "C"}

PHONETIC_LETTERS = {v.replace("-", ""): k for k, v in PHONETIC.items()}
PHONETIC_LETTERS.update({"alfa": "A", "juliet": "J", "xray": "X"})

AIRCRAFT_TYPES = {
    "cessna", "piper", "cirrus", "skyhawk", "cherokee", "bonanza", "beech", "beechcraft",
    "mooney", "diamond", "citation", "gulfstream", "learjet", "helicopter", "robinson",
    "november", "skylane", "archer", "warrior", "baron", "king",
}

# Most specific first, so "line up and wait" isn't read as something shorter.
ACTIONS: list[tuple[str, tuple[str, ...]]] = [
    ("line up and wait", ("line up and wait", "line up wait", "lineup and wait", "position and hold")),
    ("cleared for takeoff", ("cleared for takeoff", "cleared for take off", "clear for takeoff",
                             "clear for take off", "cleared takeoff")),
    ("cleared to land", ("cleared to land", "clear to land", "cleared land")),
    ("go around", ("go around", "going around")),
    ("hold short", ("hold short", "holds short", "holding short", "hold shorts")),
    ("hold position", ("hold position", "holding position")),
    ("stop", ("stop immediately", "stop stop")),
    ("cross", ("cross runway", "crossing runway", "cross")),
    ("taxi", ("taxi", "taxiing")),
]

# A wrong guess at a restrictive instruction is safe. A wrong permissive one is not (PRD local hint rules).
RESTRICTIVE_ACTIONS = {"hold short", "hold position", "go around", "stop"}
PERMISSIVE_ACTIONS = {"cleared for takeoff", "cleared to land", "cross", "line up and wait", "taxi"}


def is_restrictive(action: Optional[str]) -> bool:
    return action in RESTRICTIVE_ACTIONS


# ---------------------------------------------------------------- speech output


def speak_digits(s: str) -> str:
    """'33' -> 'tree tree', '28L' -> 'two eight left'."""
    out = []
    for ch in s:
        if ch.isdigit():
            out.append(DIGIT_WORDS[ch])
        elif ch.upper() in SIDE_WORDS:
            out.append(SIDE_WORDS[ch.upper()])
    return " ".join(out)


def speak_registration(reg: str) -> str:
    """'N123AB' -> 'November one two tree alpha bravo'."""
    words = []
    for ch in reg.upper():
        words.append(DIGIT_WORDS[ch] if ch.isdigit() else PHONETIC.get(ch, ch))
    return " ".join(words).capitalize()


def speak_runway(designator: str) -> str:
    return f"runway {speak_digits(designator)}"


def normalize_for_speech(text: str) -> str:
    """Rewrite text so TTS says it the ATC way."""
    # Times: 14:02 -> one four zero two
    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: speak_digits(m.group(1).zfill(2) + m.group(2)), text)
    # Runway designators
    text = re.sub(
        r"\b[Rr]unway\s+(\d{1,2})\s*([LRC])?\b",
        lambda m: speak_runway(m.group(1) + (m.group(2) or "")),
        text,
    )
    # US registrations: N123AB
    text = re.sub(r"\bN(\d{1,5}[A-Z]{0,2})\b", lambda m: speak_registration("N" + m.group(1)), text)
    # Hyphenated digits: 1-2-3
    text = re.sub(r"\b\d(?:-\d)+\b", lambda m: speak_digits(m.group(0).replace("-", "")), text)
    # Any other number: digit by digit
    text = re.sub(r"\b\d+\b", lambda m: speak_digits(m.group(0)), text)
    return re.sub(r"\s+", " ", text).strip()


_SPOKEN_DIGIT_WORD = r"(?:zero|one|two|tree|three|four|fife|five|six|seven|eight|niner|nine)"
_SPOKEN_TO_DIGIT = {"zero": "0", "one": "1", "two": "2", "tree": "3", "three": "3", "four": "4",
                    "fife": "5", "five": "5", "six": "6", "seven": "7", "eight": "8",
                    "niner": "9", "nine": "9"}


def _digits_of(words: str) -> str:
    return "".join(_SPOKEN_TO_DIGIT[w.lower()] for w in words.split())


def display_text(text: str) -> str:
    """Readable on-screen form of a message: 'runway tree tree' -> 'Runway 33'.

    The inverse of the runway and digit rewrites in `normalize_for_speech`, for
    text that was built with spoken digits (readback corrections). Text that
    already reads normally passes through unchanged.
    """
    text = re.sub(
        rf"\b[Rr]unway((?:\s+{_SPOKEN_DIGIT_WORD}\b){{1,2}})(?:\s+(left|right|center)\b)?",
        lambda m: "Runway " + _digits_of(m.group(1)) + ((m.group(2) or "")[:1].upper()),
        text,
    )
    # Other runs of two or more spoken digits, e.g. a time "one four zero two".
    return re.sub(
        rf"\b{_SPOKEN_DIGIT_WORD}(?:\s+{_SPOKEN_DIGIT_WORD}\b)+",
        lambda m: _digits_of(m.group(0)),
        text,
        flags=re.IGNORECASE,
    )


def spoken_callsign(callsign: str) -> str:
    """How a callsign is said on frequency: fleet registrations use their type and digits."""
    from unstep import scenario

    return scenario.SPOKEN.get(callsign, callsign)


# ---------------------------------------------------------------- parsing input


def _tokens(text: str) -> list[str]:
    text = text.lower().replace("take-off", "takeoff")
    text = re.sub(r"(?<=\d)-(?=\d)", " ", text)  # 1-2-3 -> 1 2 3
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    text = text.replace("-", " ")
    return text.split()


def _digit_tokens(tokens: list[str]) -> list[str]:
    """Convert spoken digits to digit tokens; ambiguous words only next to other digits."""

    def is_digitish(t: str) -> bool:
        return t.isdigit() or (t in SPOKEN_DIGITS and t not in AMBIGUOUS_DIGIT_WORDS)

    out = []
    for i, t in enumerate(tokens):
        if t in SPOKEN_DIGITS:
            if t in AMBIGUOUS_DIGIT_WORDS:
                prev_d = i > 0 and is_digitish(tokens[i - 1])
                next_d = i + 1 < len(tokens) and is_digitish(tokens[i + 1])
                out.append(SPOKEN_DIGITS[t] if (prev_d or next_d) else t)
            else:
                out.append(SPOKEN_DIGITS[t])
        else:
            out.append(t)
    return out


def _take_digits(tokens: list[str], i: int, max_digits: int) -> tuple[str, int]:
    """Collect up to max_digits digits starting at i. Returns (digits, next index)."""
    digits = ""
    while i < len(tokens) and tokens[i].isdigit() and len(digits) < max_digits:
        room = max_digits - len(digits)
        digits += tokens[i][:room]
        i += 1
    return digits, i


def parse_runway(tokens: list[str]) -> Optional[str]:
    for i, t in enumerate(tokens):
        if t in ("runway", "rwy"):
            digits, j = _take_digits(tokens, i + 1, 2)
            if not digits:
                continue
            side = ""
            if j < len(tokens) and tokens[j] in SIDES:
                side = SIDES[tokens[j]]
            return digits + side
        m = re.fullmatch(r"(\d{1,2})([lrc])", t)
        if m and i > 0 and tokens[i - 1] in ("runway", "rwy"):
            return m.group(1) + m.group(2).upper()
    return None


def parse_callsign(text: str, tokens: Optional[list[str]] = None) -> Optional[str]:
    """Returns 'N123AB' for registrations, else e.g. 'Cessna 123'."""
    m = re.search(r"\bN\s?(\d{1,5}[A-Za-z]{0,2})\b", text)
    if m and re.search(r"\d", m.group(1)):
        return "N" + m.group(1).upper()
    tokens = tokens if tokens is not None else _digit_tokens(_tokens(text))
    for i, t in enumerate(tokens):
        if t in AIRCRAFT_TYPES:
            digits, j = _take_digits(tokens, i + 1, 5)
            letters = ""
            while j < len(tokens) and tokens[j] in PHONETIC_LETTERS and len(letters) < 2:
                letters += PHONETIC_LETTERS[tokens[j]]
                j += 1
            if not digits:
                continue
            if t == "november":
                return "N" + digits + letters
            return f"{t.capitalize()} {digits}{letters}"
    return None


def parse_action(tokens: list[str]) -> Optional[str]:
    joined = " " + " ".join(tokens) + " "
    for action, variants in ACTIONS:
        for v in variants:
            if f" {v} " in joined:
                return action
    return None


def parse_instruction(text: str) -> Optional[Slots]:
    """Extract callsign, action and runway. None if no known action is found.

    `callsign` is "" when none was heard (Slots requires a string).
    """
    tokens = _digit_tokens(_tokens(text))
    action = parse_action(tokens)
    if action is None:
        return None
    return Slots(
        callsign=parse_callsign(text, tokens) or "",
        action=action,
        runway=parse_runway(tokens),
    )


def callsign_digits(callsign: str) -> str:
    return "".join(ch for ch in callsign if ch.isdigit())


def callsigns_match(a: str, b: str) -> bool:
    """'N123AB' matches 'Cessna 123' and 'N123AB'. Empty never matches."""
    if not a or not b:
        return False
    ca = re.sub(r"[^A-Z0-9]", "", a.upper())
    cb = re.sub(r"[^A-Z0-9]", "", b.upper())
    if ca == cb:
        return True
    da, db = callsign_digits(a), callsign_digits(b)
    if not da or not db:
        return False
    return da in db or db in da
