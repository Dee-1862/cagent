"""Turns a controller's decision into an ApprovedDirective or DirectiveRejected.

This is the only place an ApprovedDirective is created, so every directive the
cockpit receives traces back to a human decision on a ProposedDirective (FR-6).
"""

from dataclasses import dataclass, field

from contracts.models import (
    ApprovedDirective,
    ClickApproval,
    DirectiveRejected,
    ProposedDirective,
    VoiceApproval,
)


class ApprovalError(Exception):
    pass


@dataclass
class ApprovalBook:
    voice_controller_id: str
    _pending: dict[str, ProposedDirective] = field(default_factory=dict)
    _decided: set[str] = field(default_factory=set)

    def propose(self, directive: ProposedDirective) -> None:
        if directive.event_id in self._decided:
            raise ApprovalError(f"event {directive.event_id} was already decided")
        self._pending[directive.event_id] = directive

    def decide(
        self, decision: VoiceApproval | ClickApproval, now_ms: int
    ) -> ApprovedDirective | DirectiveRejected | None:
        """Returns None when there is nothing to send, such as an unclear reply."""
        if decision.decision == "unclear":
            return None
        event_id = decision.event_id
        if event_id in self._decided:
            # A second "Approve" (voice and click, or a retry) must not send twice.
            return None
        directive = self._pending.get(event_id)
        if directive is None:
            raise ApprovalError(f"no proposed directive for event {event_id}")

        if isinstance(decision, VoiceApproval):
            via, by = "voice", self.voice_controller_id
        else:
            via, by = "click", decision.approved_by

        del self._pending[event_id]
        self._decided.add(event_id)
        if decision.decision == "approve":
            return ApprovedDirective(
                event_id=event_id,
                instruction_text=directive.instruction_text,
                slots=directive.slots,
                approved_by=by,
                approved_via=via,
                approved_at=now_ms,
            )
        return DirectiveRejected(
            event_id=event_id, rejected_by=by, rejected_via=via, rejected_at=now_ms
        )
