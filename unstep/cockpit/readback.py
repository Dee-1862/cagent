"""Readback checking (task A7, PRD FR-9).

Compares the pilot's readback with the approved directive on three slots:
callsign, action and runway. This is a slot comparison in our own code, not a
Moss search (Architecture section 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from unstep.contracts import ReadbackResult, Slots
from unstep.cockpit.phraseology import (
    callsigns_match,
    parse_instruction,
    speak_digits,
    speak_runway,
)


def check_readback(directive: Slots, readback_text: str) -> tuple[bool, Optional[Slots], str]:
    """Returns (match, parsed readback slots, reason). Reason is "" on a match."""
    heard = parse_instruction(readback_text)
    if heard is None:
        return False, None, "no instruction heard in readback"
    if heard.action != directive.action:
        return False, heard, f"action '{heard.action}' instead of '{directive.action}'"
    if directive.runway and heard.runway != directive.runway:
        got = heard.runway or "none"
        return False, heard, f"runway {got} instead of {directive.runway}"
    if not heard.callsign:
        return False, heard, "callsign missing"
    if not callsigns_match(heard.callsign, directive.callsign):
        return False, heard, f"callsign {heard.callsign} instead of {directive.callsign}"
    return True, heard, ""


def correction_text(directive: Slots, heard: Optional[Slots]) -> str:
    """What Unstep says after a wrong readback, for example "Readback incorrect. Runway tree tree."

    Corrects the first wrong slot. The advisory voice adds the "Advisory." prefix.
    """
    if heard is None or heard.action != directive.action:
        what = directive.action.capitalize()
        if directive.runway:
            what += f" {speak_runway(directive.runway)}"
        return f"Readback incorrect. {what}."
    if directive.runway and heard.runway != directive.runway:
        return f"Readback incorrect. Runway {speak_digits(directive.runway)}."
    return "Readback incorrect. Say callsign."


StepAction = Literal["confirmed", "repeat", "flag_controller"]


@dataclass
class ReadbackStep:
    result: ReadbackResult
    action: StepAction
    say: str  # without the "Advisory." prefix
    reason: str = ""


class ReadbackSession:
    """One directive's readback loop.

    Wrong readback: say the correction and repeat, up to `max_repeats` times.
    The next wrong readback stops repeating and flags the controller.
    """

    def __init__(self, event_id: str, directive: Slots, max_repeats: int = 2):
        self.event_id = event_id
        self.directive = directive
        self.max_repeats = max_repeats
        self.attempt = 0
        self.repeats = 0
        self.done = False

    def on_readback(self, readback_text: str) -> ReadbackStep:
        if self.done:
            raise RuntimeError(f"readback session for {self.event_id} is finished")
        self.attempt += 1
        match, heard, reason = check_readback(self.directive, readback_text)
        result = ReadbackResult(
            event_id=self.event_id,
            readback_text=readback_text,
            slots=heard,
            match=match,
            attempt=self.attempt,
        )
        if match:
            self.done = True
            return ReadbackStep(result, "confirmed", "Readback correct.")
        if self.repeats < self.max_repeats:
            self.repeats += 1
            return ReadbackStep(result, "repeat", correction_text(self.directive, heard), reason)
        self.done = True
        return ReadbackStep(result, "flag_controller", "Readback incorrect. Advising controller.", reason)
