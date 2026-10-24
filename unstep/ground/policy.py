"""Policy agent: decides which proposals need the human (docs/11-live-demo.md).

The blocked instruction was already spoken by the controller on the radio. When
the agents can show they are re-delivering exactly those words, the policy may
relay them without asking again. Everything else goes to the controller:

    auto-relay only if every check passes
      tower_transcript  the ground heard the controller's own words
      addressed         those words were addressed to this aircraft
      restrictive       the instruction makes the aircraft wait (hold short, stop, ...)
      confidence        the agents rated the match high
      hint_agrees       the cockpit's local hint does not contradict it
      fresh             the controller spoke within the last max_age_s seconds
      autonomy_on       the controller has not switched auto-relay off

No agent ever creates an instruction: an auto-relay repeats the controller's own
transmission, and the gateway double-checks restrictive and high confidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from unstep.clock import now_ms
from unstep.cockpit.phraseology import callsigns_match, is_restrictive, parse_callsign, parse_instruction
from unstep.config import env
from unstep.contracts import (AnomalyEvent, ApprovedDirective, AuditRecord, ProposedDirective,
                              TowerTranscript)

DEFAULT_MAX_AGE_S = 30.0


def auto_max_age_s() -> float:
    return float(env("UNSTEP_AUTO_MAX_AGE_S", default=str(DEFAULT_MAX_AGE_S)))


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class PolicyDecision:
    event_id: str
    auto: bool
    checks: list[Check] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        """Why it needs the human: the details of every failed check."""
        return [c.detail for c in self.checks if not c.ok]

    def payload(self) -> dict:
        return {"decision": "auto_relay" if self.auto else "escalate",
                "checks": [asdict(c) for c in self.checks], "reasons": self.reasons}


def evaluate(proposal: ProposedDirective, transcript: TowerTranscript | None, event: AnomalyEvent | None,
             *, enabled: bool = True, now: int | None = None, max_age_s: float | None = None) -> PolicyDecision:
    now = now_ms() if now is None else now
    max_age_s = auto_max_age_s() if max_age_s is None else max_age_s
    slots = proposal.slots
    checks = [Check("tower_transcript", transcript is not None,
                    "ground heard the controller's own words" if transcript is not None
                    else "no tower transcript for this call, the words are unknown")]
    if transcript is not None:
        addressed = transcript.callsign or parse_callsign(transcript.text) or ""
        checks.append(Check("addressed", callsigns_match(addressed, slots.callsign),
                            f"tower call was to {addressed or 'an unknown callsign'}, event is for {slots.callsign}"))
        age_s = (now - transcript.ptt_end) / 1000
        checks.append(Check("fresh", age_s <= max_age_s,
                            f"controller spoke {age_s:.0f} s ago (limit {max_age_s:.0f} s)"))
    checks.append(Check("restrictive", is_restrictive(slots.action),
                        f"'{slots.action}' {'makes the aircraft wait' if is_restrictive(slots.action) else 'is not a restrictive instruction'}"))
    checks.append(Check("confidence", proposal.confidence == "high",
                        f"agents rated the match {proposal.confidence} ({proposal.confidence_method})"))
    hint = event.local_hint if event is not None else None
    hint_slots = parse_instruction(hint.text or "") if hint is not None and hint.kind == "restrictive" else None
    agrees = hint_slots is None or (hint_slots.action, hint_slots.runway) == (slots.action, slots.runway)
    checks.append(Check("hint_agrees", agrees,
                        "cockpit hint agrees or gave none" if agrees
                        else f"cockpit hint '{hint.text}' disagrees with '{proposal.instruction_text}'"))
    checks.append(Check("autonomy_on", enabled,
                        "auto-relay is on" if enabled else "controller switched auto-relay off"))
    return PolicyDecision(proposal.event_id, all(c.ok for c in checks), checks)


class PolicyAgent:
    """Watches the gateway and auto-relays proposals that pass every check.

    `send` delivers a message to the gateway as role "policy". Escalated proposals
    stay pending at the gateway for the controller to decide.
    """

    def __init__(self, send, enabled: bool = True):
        self.send = send
        self.enabled = enabled
        self.transcripts: dict[str, TowerTranscript] = {}
        self.events: dict[str, AnomalyEvent] = {}
        self.decisions: dict[str, PolicyDecision] = {}

    async def on_message(self, msg) -> PolicyDecision | None:
        if isinstance(msg, TowerTranscript):
            self.transcripts[msg.transcript_id] = msg
        elif isinstance(msg, AnomalyEvent):
            self.events[msg.event_id] = msg
        elif isinstance(msg, ProposedDirective):
            return await self.decide(msg)
        return None

    async def decide(self, proposal: ProposedDirective) -> PolicyDecision:
        decision = evaluate(proposal, self.transcripts.get(proposal.transcript_id or ""),
                            self.events.get(proposal.event_id), enabled=self.enabled)
        self.decisions[proposal.event_id] = decision
        await self.send(AuditRecord(event_id=proposal.event_id, stage="policy", actor="policy",
                                    payload=decision.payload()))
        if decision.auto:
            # The gateway rebuilds the directive from its stored proposal; these fields are not trusted.
            await self.send(ApprovedDirective(event_id=proposal.event_id, instruction_text=proposal.instruction_text,
                                              slots=proposal.slots, approved_by="unstep-policy",
                                              approved_via="auto"))
        return decision
