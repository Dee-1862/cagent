"""Policy agent: auto-relay only the controller's own verified restrictive words."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from unstep import scenario
from unstep.clock import now_ms
from unstep.contracts import (AnomalyEvent, ApprovedDirective, LocalHint, ProposedDirective, Slots,
                              TowerTranscript, unwrap, wrap)
from unstep.gateway.server import create_app
from unstep.gateway.sink import MemorySink
from unstep.ground.policy import PolicyAgent, evaluate

NOW = 1_800_000_000_000


def transcript(text="Cessna 1-2-3, hold short Runway 33", callsign=None, ended=NOW - 2000):
    return TowerTranscript(transcript_id="tx-1", frequency=scenario.FREQUENCY, callsign=callsign,
                           ptt_start=ended - 2500, ptt_end=ended, text=text)


def proposal(action="hold short", confidence="high", callsign="N123AB", runway="33"):
    return ProposedDirective(event_id="evt-1", transcript_id="tx-1",
                             instruction_text=f"Cessna 1-2-3, {action} Runway {runway}",
                             slots=Slots(callsign=callsign, action=action, runway=runway),
                             confidence=confidence, confidence_method="test")


def event(hint="hold short Runway 33"):
    return AnomalyEvent(event_id="evt-1", callsign="N123AB", frequency=scenario.FREQUENCY,
                        squelch_open=NOW - 4000, squelch_close=NOW - 1500, overlap_start=NOW - 3000,
                        overlap_end=NOW - 1600, heard_text="Cessna 1-2-3 [static]",
                        local_hint=LocalHint(text=hint, kind="restrictive", source_doc_id="clr-7") if hint
                        else LocalHint())


def failed(decision):
    return {c.name for c in decision.checks if not c.ok}


def test_verified_restrictive_words_are_auto_relayed():
    d = evaluate(proposal(), transcript(), event(), now=NOW, max_age_s=30)
    assert d.auto and failed(d) == set()
    assert d.payload()["decision"] == "auto_relay"


@pytest.mark.parametrize("args,why", [
    (dict(t=None), "tower_transcript"),
    (dict(t=transcript(text="Helicopter 4-5-6, hold short Runway 33")), "addressed"),
    (dict(t=transcript(ended=NOW - 60_000)), "fresh"),
    (dict(p=proposal(action="cleared for takeoff")), "restrictive"),
    (dict(p=proposal(confidence="medium")), "confidence"),
    (dict(e=event(hint="hold short Runway 28L")), "hint_agrees"),
    (dict(enabled=False), "autonomy_on"),
])
def test_each_failed_check_escalates_to_the_controller(args, why):
    d = evaluate(args.get("p", proposal()), args["t"] if "t" in args else transcript(),
                 args.get("e", event()), enabled=args.get("enabled", True), now=NOW, max_age_s=30)
    assert not d.auto
    assert why in failed(d)
    assert d.reasons  # a human-readable reason for every escalation


def test_no_hint_is_not_a_conflict():
    assert evaluate(proposal(), transcript(), event(hint=None), now=NOW, max_age_s=30).auto


def test_agent_sends_audit_and_approval_only_when_auto():
    sent = []

    async def send(msg):
        sent.append(msg)

    async def go(enabled):
        agent = PolicyAgent(send, enabled=enabled)
        await agent.on_message(transcript(ended=now_ms()))
        await agent.on_message(event())
        return await agent.on_message(proposal())

    assert asyncio.run(go(True)).auto
    assert [type(m).__name__ for m in sent] == ["AuditRecord", "ApprovedDirective"]
    sent.clear()
    assert not asyncio.run(go(False)).auto
    assert [type(m).__name__ for m in sent] == ["AuditRecord"]
    assert sent[0].payload["decision"] == "escalate"


def gateway_round(proposal_msg, expect_error: bool):
    """Agents propose, the policy agent approves. Returns (what came back, gateway)."""
    client = TestClient(create_app(MemorySink()))
    with client.websocket_connect("/ws/agents") as agents, client.websocket_connect("/ws/policy") as policy,             client.websocket_connect("/ws/cockpit") as cockpit:
        agents.send_text(wrap(proposal_msg))
        assert unwrap(policy.receive_text())[0].type == "ProposedDirective"
        policy.send_text(wrap(ApprovedDirective(event_id="evt-1", instruction_text="forged",
                                                slots=proposal_msg.slots, approved_by="x", approved_via="auto")))
        if expect_error:
            env = unwrap(policy.receive_text())[0]
            assert env.type == "Error"
            return env.data["message"], client.app.state.gateway
        env = unwrap(cockpit.receive_text())[0]
        assert env.type == "ApprovedDirective"
        return env.data, client.app.state.gateway


def test_gateway_relays_policy_approval_from_the_stored_proposal():
    data, gw = gateway_round(proposal(), expect_error=False)
    assert data["approved_via"] == "auto" and data["approved_by"] == "unstep-policy"
    assert data["instruction_text"] == "Cessna 1-2-3, hold short Runway 33"  # not the forged text
    assert "evt-1" not in gw.pending


@pytest.mark.parametrize("p", [proposal(action="cleared for takeoff"), proposal(confidence="low")])
def test_gateway_refuses_auto_relay_of_unsafe_proposals(p):
    message, gw = gateway_round(p, expect_error=True)
    assert "may not be auto-relayed" in message
    assert "evt-1" in gw.pending  # still waiting for the controller


def test_policy_can_never_reject():
    client = TestClient(create_app(MemorySink()))
    with client.websocket_connect("/ws/policy") as policy:
        policy.send_text('{"type": "RejectedDirective", "data": {"event_id": "evt-1", "rejected_by": "x", '
                         '"rejected_via": "click"}}')
        assert "may not send RejectedDirective" in unwrap(policy.receive_text())[0].data["message"]
