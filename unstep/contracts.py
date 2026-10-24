"""Shared message contracts (Work Split, section 3).

Every message travels over the gateway as an Envelope: {"type", "ts", "data"}.
Field names match the work split exactly. Change them only when both developers
agree, and log the change in docs/02-changes.md.
"""

from __future__ import annotations

import re
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from unstep.clock import now_ms


class Slots(BaseModel):
    callsign: str
    action: str
    runway: Optional[str] = None


class Word(BaseModel):
    word: str
    start: float  # seconds from ptt_start
    end: float  # seconds from ptt_start


class Gps(BaseModel):
    lat: float
    lon: float


# PRD local hint rules: only instructions where a wrong guess makes the aircraft wait.
RESTRICTIVE_ACTIONS = ("hold short", "hold position", "stop", "go around")
RESTRICTIVE_HINT = re.compile(
    r"(hold short( of)?( runway \d{1,2}[lrc]?)?|hold position|stop|go around)", re.IGNORECASE
)


class LocalHint(BaseModel):
    text: Optional[str] = None
    kind: Literal["restrictive", "none"] = "none"
    source_doc_id: Optional[str] = None
    source_text: Optional[str] = None
    moss_ms: Optional[float] = None

    @model_validator(mode="after")
    def _enforce_hint_rules(self):
        if self.kind == "restrictive":
            if not self.text or not self.source_doc_id:
                raise ValueError("a restrictive hint needs text and a source_doc_id")
            # The whole text must be one restrictive instruction, so clearance
            # wording like "cleared for takeoff, don't stop" can't slip through.
            if not RESTRICTIVE_HINT.fullmatch(self.text.strip()):
                raise ValueError(f"hint is not a restrictive instruction: {self.text!r}")
        return self


class TowerTranscript(BaseModel):
    transcript_id: str
    frequency: str
    callsign: Optional[str] = None
    ptt_start: int
    ptt_end: int
    text: str
    words: list[Word] = Field(default_factory=list)
    confidence: Optional[float] = None


class AnomalyEvent(BaseModel):
    event_id: str
    callsign: str
    frequency: str
    squelch_open: int
    squelch_close: int
    overlap_start: int
    overlap_end: int
    heard_text: str
    local_hint: LocalHint = Field(default_factory=LocalHint)
    gps: Optional[Gps] = None
    taxiway_node: Optional[str] = None


class ProposedDirective(BaseModel):
    event_id: str
    transcript_id: Optional[str] = None
    blocked_words: list[str] = Field(default_factory=list)
    instruction_text: str
    slots: Slots
    confidence: Literal["high", "medium", "low"]
    confidence_method: str
    rule_citation: Optional[str] = None


class VoiceApproval(BaseModel):
    event_id: str
    heard_text: str
    decision: Literal["approve", "reject", "unclear"]
    attempt: int = 1
    ts: int = Field(default_factory=now_ms)


class ApprovedDirective(BaseModel):
    event_id: str
    instruction_text: str
    slots: Slots
    approved_by: str
    # "auto": relayed by the policy agent without asking (docs/11-live-demo.md, needs both developers).
    approved_via: Literal["voice", "click", "auto"]
    approved_at: int = Field(default_factory=now_ms)


class RejectedDirective(BaseModel):
    """Not in the v0.4 table yet: the cockpit needs it to say "request say again"."""

    event_id: str
    rejected_by: str
    rejected_via: Literal["voice", "click", "timeout"]
    rejected_at: int = Field(default_factory=now_ms)


class ReadbackResult(BaseModel):
    event_id: str
    readback_text: str
    slots: Optional[Slots] = None
    match: bool
    attempt: int = 1


class PilotQuery(BaseModel):
    query_id: str
    callsign: str
    question: str
    answer: str
    source_doc_id: Optional[str] = None
    moss_ms: Optional[float] = None
    ts: int = Field(default_factory=now_ms)


class Insight(BaseModel):
    insight_id: str
    frequency: str
    callsign: Optional[str] = None
    kind: str
    text: str
    ts: int = Field(default_factory=now_ms)


class AuditRecord(BaseModel):
    event_id: str
    stage: str
    actor: str
    ts: int = Field(default_factory=now_ms)
    latency_ms: Optional[float] = None
    payload: dict = Field(default_factory=dict)


Message = Union[
    TowerTranscript,
    AnomalyEvent,
    ProposedDirective,
    VoiceApproval,
    ApprovedDirective,
    RejectedDirective,
    ReadbackResult,
    PilotQuery,
    Insight,
    AuditRecord,
]

MODELS: dict[str, type[BaseModel]] = {m.__name__: m for m in Message.__args__}


class Envelope(BaseModel):
    type: str
    ts: int = Field(default_factory=now_ms)
    data: dict

    def parse(self) -> BaseModel:
        return MODELS[self.type].model_validate(self.data)


def wrap(msg: BaseModel) -> str:
    """Serialize a contract model into an Envelope JSON string."""
    return Envelope(type=type(msg).__name__, data=msg.model_dump(mode="json")).model_dump_json()


def unwrap(raw: str) -> tuple[Envelope, Optional[BaseModel]]:
    """Parse an Envelope JSON string and validate its payload.

    Gateway error replies ({"type": "Error"}) return (envelope, None) so clients
    can log them without crashing.
    """
    env = Envelope.model_validate_json(raw)
    if env.type == "Error":
        return env, None
    if env.type not in MODELS:
        raise ValueError(f"unknown message type: {env.type}")
    return env, env.parse()
