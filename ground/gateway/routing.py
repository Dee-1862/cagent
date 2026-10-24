"""Who may send each message, and who receives it.

Mirrors the table in docs/05-architecture.md section 5. A message type with no
allowed senders can only be created by the gateway itself.
"""

ROLES = frozenset({"cockpit", "tower", "agents", "controller_voice", "dashboard", "monitor"})

SENDERS: dict[str, frozenset[str]] = {
    "TowerTranscript": frozenset({"tower"}),
    "AnomalyEvent": frozenset({"cockpit"}),
    "ProposedDirective": frozenset({"agents"}),
    "VoiceApproval": frozenset({"controller_voice"}),
    "ClickApproval": frozenset({"dashboard"}),
    # FR-6: no client can approve a directive by sending one directly.
    "ApprovedDirective": frozenset(),
    "DirectiveRejected": frozenset(),
    "ReadbackResult": frozenset({"cockpit"}),
    "PilotQuery": frozenset({"cockpit"}),
    "Insight": frozenset({"monitor"}),
    "AuditRecord": ROLES,
}

RECIPIENTS: dict[str, frozenset[str]] = {
    "TowerTranscript": frozenset({"monitor", "agents", "dashboard"}),
    "AnomalyEvent": frozenset({"agents", "dashboard"}),
    "ProposedDirective": frozenset({"controller_voice", "dashboard"}),
    "VoiceApproval": frozenset({"dashboard"}),
    "ClickApproval": frozenset(),
    "ApprovedDirective": frozenset({"cockpit", "controller_voice", "dashboard"}),
    "DirectiveRejected": frozenset({"cockpit", "controller_voice", "dashboard"}),
    "ReadbackResult": frozenset({"agents", "dashboard"}),
    # Audit only: stored in Elastic, not relayed.
    "PilotQuery": frozenset(),
    "Insight": frozenset({"dashboard"}),
    "AuditRecord": frozenset(),
}
