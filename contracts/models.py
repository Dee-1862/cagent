"""Unstep message contracts.

Mirrors docs/04-work-split.md section 3. Every timestamp is epoch milliseconds
from the gateway clock, except TowerTranscript.words, which are seconds from
ptt_start.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    # Unknown fields are rejected so the two halves can't drift apart silently.
    model_config = ConfigDict(extra="forbid")


class Word(Contract):
    word: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class Slots(Contract):
    callsign: str
    action: str
    runway: str | None = None


class LocalHint(Contract):
    text: str | None
    kind: Literal["restrictive", "none"]
    source_doc_id: str | None
    source_text: str | None
    moss_ms: float | None


class Gps(Contract):
    lat: float
    lon: float


class TowerTranscript(Contract):
    transcript_id: str
    frequency: str
    callsign: str | None
    ptt_start: int
    ptt_end: int
    text: str
    words: list[Word]
    confidence: float = Field(ge=0, le=1)


class AnomalyEvent(Contract):
    event_id: str
    callsign: str
    frequency: str
    squelch_open: int
    squelch_close: int
    overlap_start: int
    overlap_end: int
    heard_text: str
    local_hint: LocalHint
    gps: Gps | None
    taxiway_node: str | None


class ProposedDirective(Contract):
    event_id: str
    transcript_id: str
    blocked_words: list[str]
    instruction_text: str
    slots: Slots
    confidence: float = Field(ge=0, le=1)
    confidence_method: str
    rule_citation: str


class VoiceApproval(Contract):
    event_id: str
    heard_text: str
    decision: Literal["approve", "reject", "unclear"]
    attempt: int = Field(ge=1)
    ts: int


class ClickApproval(Contract):
    """Proposed by Dev B: the dashboard's click fallback for VoiceApproval."""

    event_id: str
    decision: Literal["approve", "reject"]
    approved_by: str
    ts: int


class ApprovedDirective(Contract):
    """Only the gateway creates this, from a VoiceApproval or ClickApproval."""

    event_id: str
    instruction_text: str
    slots: Slots
    approved_by: str
    approved_via: Literal["voice", "click"]
    approved_at: int


class DirectiveRejected(Contract):
    """Proposed by Dev B: tells the cockpit to say "request say again"."""

    event_id: str
    rejected_by: str
    rejected_via: Literal["voice", "click"]
    rejected_at: int


class ReadbackResult(Contract):
    event_id: str
    readback_text: str
    slots: Slots
    match: bool
    attempt: int = Field(ge=1)


class PilotQuery(Contract):
    query_id: str
    callsign: str
    question: str
    answer: str
    source_doc_id: str | None
    moss_ms: float | None
    ts: int


class Insight(Contract):
    insight_id: str
    frequency: str
    callsign: str | None
    kind: str
    text: str
    ts: int


class AuditRecord(Contract):
    event_id: str
    stage: str
    actor: str
    ts: int
    latency_ms: float | None
    payload: dict


CONTRACTS: dict[str, type[Contract]] = {
    cls.__name__: cls
    for cls in (
        TowerTranscript,
        AnomalyEvent,
        ProposedDirective,
        VoiceApproval,
        ClickApproval,
        ApprovedDirective,
        DirectiveRejected,
        ReadbackResult,
        PilotQuery,
        Insight,
        AuditRecord,
    )
}


class Envelope(BaseModel):
    """What goes over the WebSocket: {"type": "AnomalyEvent", "payload": {...}}."""

    model_config = ConfigDict(extra="forbid")

    type: str
    payload: dict
    sent_at: int | None = None
    gateway_ts: int | None = None
