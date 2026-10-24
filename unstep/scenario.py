"""The demo scenario (PRD section 11): Cessna 1-2-3 is told to hold short of Runway 33
while a helicopter steps on the call.

Used for the contract examples, the mocks and the tests, so every part of the
system agrees on the same fake data until real audio is wired in.
"""

from unstep.contracts import (
    AnomalyEvent,
    ApprovedDirective,
    AuditRecord,
    Gps,
    Insight,
    LocalHint,
    PilotQuery,
    ProposedDirective,
    ReadbackResult,
    RejectedDirective,
    Slots,
    TowerTranscript,
    VoiceApproval,
    Word,
)

CALLSIGN = "N123AB"
SPOKEN_CALLSIGN = "Cessna 1-2-3"
FREQUENCY = "118.700"

# Fixed base time so examples are stable. Live runs use clock.now_ms().
T0 = 1_792_800_000_000

SLOTS = Slots(callsign=CALLSIGN, action="hold short", runway="33")


def tower_transcript(t0: int = T0) -> TowerTranscript:
    return TowerTranscript(
        transcript_id="tx-0001",
        frequency=FREQUENCY,
        callsign=CALLSIGN,
        ptt_start=t0,
        ptt_end=t0 + 2600,
        text="Cessna 1-2-3, hold short Runway 33",
        words=[
            Word(word="Cessna", start=0.10, end=0.55),
            Word(word="1-2-3,", start=0.60, end=1.20),
            Word(word="hold", start=1.35, end=1.60),
            Word(word="short", start=1.62, end=1.90),
            Word(word="Runway", start=1.95, end=2.25),
            Word(word="33", start=2.28, end=2.55),
        ],
        confidence=0.94,
    )


def anomaly_event(event_id: str = "evt-0001", t0: int = T0) -> AnomalyEvent:
    return AnomalyEvent(
        event_id=event_id,
        callsign=CALLSIGN,
        frequency=FREQUENCY,
        squelch_open=t0 + 40,
        squelch_close=t0 + 2650,
        overlap_start=t0 + 1300,
        overlap_end=t0 + 2600,
        heard_text="Cessna 1-2-3 [static]",
        local_hint=LocalHint(
            text="hold short Runway 33",
            kind="restrictive",
            source_doc_id="flight-N123AB/clr-0007",
            source_text="Cessna 1-2-3, Runway 33, taxi via Bravo",
            moss_ms=3.1,
        ),
        gps=Gps(lat=37.6188, lon=-122.3750),
        taxiway_node="B4",
    )


def proposed_directive(event_id: str = "evt-0001") -> ProposedDirective:
    return ProposedDirective(
        event_id=event_id,
        transcript_id="tx-0001",
        blocked_words=["hold", "short", "Runway", "33"],
        instruction_text="Cessna 1-2-3, hold short Runway 33",
        slots=SLOTS,
        confidence="high",
        confidence_method="tower transcript match + rule match",
        rule_citation="FAA JO 7110.65, paragraph TBD",
    )


def voice_approval(event_id: str = "evt-0001") -> VoiceApproval:
    return VoiceApproval(event_id=event_id, heard_text="Approve", decision="approve", ts=T0 + 9000)


def approved_directive(event_id: str = "evt-0001") -> ApprovedDirective:
    return ApprovedDirective(
        event_id=event_id,
        instruction_text="Cessna 1-2-3, hold short Runway 33",
        slots=SLOTS,
        approved_by="controller",
        approved_via="voice",
        approved_at=T0 + 9100,
    )


def rejected_directive(event_id: str = "evt-0001") -> RejectedDirective:
    return RejectedDirective(
        event_id=event_id, rejected_by="controller", rejected_via="voice", rejected_at=T0 + 9100
    )


def readback_result(event_id: str = "evt-0001", match: bool = False, attempt: int = 1) -> ReadbackResult:
    runway = "33" if match else "23"
    return ReadbackResult(
        event_id=event_id,
        readback_text=f"Hold short Runway {runway}, Cessna 1-2-3",
        slots=Slots(callsign=CALLSIGN, action="hold short", runway=runway),
        match=match,
        attempt=attempt,
    )


def pilot_query() -> PilotQuery:
    return PilotQuery(
        query_id="q-0001",
        callsign=CALLSIGN,
        question="Unstep, what was my last clearance?",
        answer="Hold short Runway tree tree, issued one four zero two.",
        source_doc_id="flight-N123AB/clr-0008",
        moss_ms=2.7,
        ts=T0 + 30_000,
    )


def insight() -> Insight:
    return Insight(
        insight_id="ins-0001",
        frequency=FREQUENCY,
        callsign=CALLSIGN,
        kind="repeated_blocked_calls",
        text="N123AB has had 2 blocked calls in 5 minutes.",
        ts=T0 + 31_000,
    )


def audit_record(event_id: str = "evt-0001") -> AuditRecord:
    return AuditRecord(
        event_id=event_id,
        stage="local_hint",
        actor="cockpit",
        ts=T0 + 2700,
        latency_ms=3.1,
        payload={"source_doc_id": "flight-N123AB/clr-0007"},
    )


ALL_EXAMPLES = [
    tower_transcript(),
    anomaly_event(),
    proposed_directive(),
    voice_approval(),
    approved_directive(),
    rejected_directive(),
    readback_result(),
    pilot_query(),
    insight(),
    audit_record(),
]
