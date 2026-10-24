"""M2 first wire: a fake stepped-on event goes cockpit to gateway to dashboard,
approval comes back, the cockpit gets the directive. Work Split checkpoint:
run the full fake path 10 times in a row without errors.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from unstep import scenario
from unstep.contracts import (
    MODELS,
    AnomalyEvent,
    ApprovedDirective,
    Envelope,
    ProposedDirective,
    RejectedDirective,
    VoiceApproval,
    unwrap,
    wrap,
)
from unstep.gateway.server import create_app
from unstep.gateway.sink import MemorySink
from unstep.ground.mock_agents import propose

EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "examples"


@pytest.fixture
def setup():
    sink = MemorySink()
    client = TestClient(create_app(sink))
    return client, sink


def recv(ws):
    return unwrap(ws.receive_text())[1]


def test_contract_examples_parse():
    files = sorted(EXAMPLES.glob("*.json"))
    assert {f.stem for f in files} == set(MODELS)
    for f in files:
        env = Envelope.model_validate(json.loads(f.read_text()))
        env.parse()


def test_round_trip_ten_times_voice_and_click(setup):
    client, sink = setup
    with client.websocket_connect("/ws/cockpit") as cockpit, \
         client.websocket_connect("/ws/agents") as agents, \
         client.websocket_connect("/ws/dashboard") as dashboard, \
         client.websocket_connect("/ws/controller_voice") as voice:
        for i in range(10):
            event = scenario.anomaly_event(event_id=f"evt-{i}")
            cockpit.send_text(wrap(event))

            got = recv(agents)
            assert isinstance(got, AnomalyEvent) and got.event_id == event.event_id
            assert isinstance(recv(dashboard), AnomalyEvent)
            agents.send_text(wrap(propose(got)))

            proposal = recv(dashboard)
            assert isinstance(proposal, ProposedDirective)
            assert isinstance(recv(voice), ProposedDirective)

            if i % 2 == 0:  # voice approval
                voice.send_text(wrap(VoiceApproval(event_id=event.event_id, heard_text="Approve", decision="approve")))
                assert isinstance(recv(dashboard), VoiceApproval)
                expected_via = "voice"
            else:  # click fallback
                dashboard.send_text(wrap(ApprovedDirective(
                    event_id=event.event_id, instruction_text=proposal.instruction_text,
                    slots=proposal.slots, approved_by="controller", approved_via="click")))
                expected_via = "click"

            directive = recv(cockpit)
            assert isinstance(directive, ApprovedDirective)
            assert directive.event_id == event.event_id
            assert directive.approved_via == expected_via
            assert directive.instruction_text == "N123AB, hold short Runway 33"
            recv(dashboard)  # dashboard sees the approval
            recv(voice)
            recv(agents)

    # Per run: event, proposal, voice or click decision, gateway's directive.
    assert len(sink.records) == 40


def test_reject_and_double_decision(setup):
    client, _ = setup
    with client.websocket_connect("/ws/cockpit") as cockpit, \
         client.websocket_connect("/ws/agents") as agents, \
         client.websocket_connect("/ws/dashboard") as dashboard, \
         client.websocket_connect("/ws/controller_voice") as voice:
        agents.send_text(wrap(scenario.proposed_directive("evt-r")))
        recv(voice)
        recv(dashboard)

        voice.send_text(wrap(VoiceApproval(event_id="evt-r", heard_text="Reject", decision="reject")))
        recv(dashboard)  # the VoiceApproval itself
        assert isinstance(recv(cockpit), RejectedDirective)
        recv(dashboard)

        # A late click on the same event is refused.
        dashboard.send_text(wrap(scenario.approved_directive("evt-r")))
        err = json.loads(dashboard.receive_text())
        assert err["type"] == "Error"


def test_unclear_voice_sends_nothing(setup):
    client, _ = setup
    with client.websocket_connect("/ws/agents") as agents, \
         client.websocket_connect("/ws/dashboard") as dashboard, \
         client.websocket_connect("/ws/controller_voice") as voice:
        agents.send_text(wrap(scenario.proposed_directive("evt-u")))
        recv(voice)
        recv(dashboard)
        voice.send_text(wrap(VoiceApproval(event_id="evt-u", heard_text="uh", decision="unclear")))
        recv(dashboard)
        assert client.get("/health").json()["pending"] == 1


def test_bad_message_returns_error(setup):
    client, _ = setup
    with client.websocket_connect("/ws/cockpit") as cockpit:
        cockpit.send_text(json.dumps({"type": "AnomalyEvent", "data": {"event_id": "x"}}))
        assert json.loads(cockpit.receive_text())["type"] == "Error"
        cockpit.send_text(json.dumps({"type": "Nope", "data": {}}))
        assert json.loads(cockpit.receive_text())["type"] == "Error"


def test_roles_cannot_send_other_types(setup):
    client, _ = setup
    with client.websocket_connect("/ws/cockpit") as cockpit, \
         client.websocket_connect("/ws/monitor") as monitor:
        cockpit.send_text(wrap(scenario.approved_directive("evt-x")))
        assert json.loads(cockpit.receive_text())["type"] == "Error"
        monitor.send_text(wrap(scenario.voice_approval("evt-x")))
        assert json.loads(monitor.receive_text())["type"] == "Error"
        monitor.send_text(wrap(scenario.proposed_directive("evt-x")))
        assert json.loads(monitor.receive_text())["type"] == "Error"


def test_click_cannot_change_text_and_no_reproposal(setup):
    client, _ = setup
    with client.websocket_connect("/ws/cockpit") as cockpit, \
         client.websocket_connect("/ws/agents") as agents, \
         client.websocket_connect("/ws/dashboard") as dashboard:
        agents.send_text(wrap(scenario.proposed_directive("evt-t")))
        recv(dashboard)
        forged = scenario.approved_directive("evt-t").model_copy(
            update={"instruction_text": "Cessna 1-2-3, cleared for takeoff Runway 33"})
        dashboard.send_text(wrap(forged))
        directive = recv(cockpit)
        assert directive.instruction_text == "Cessna 1-2-3, hold short Runway 33"
        assert directive.approved_via == "click"
        recv(agents)
        # The same event can't be proposed again after a decision.
        agents.send_text(wrap(scenario.proposed_directive("evt-t")))
        assert json.loads(agents.receive_text())["type"] == "Error"


def test_expired_proposal_sends_nothing():
    client = TestClient(create_app(MemorySink(), pending_ttl_s=0))
    with client.websocket_connect("/ws/agents") as agents, \
         client.websocket_connect("/ws/controller_voice") as voice:
        agents.send_text(wrap(scenario.proposed_directive("evt-e")))
        recv(voice)
        import time
        time.sleep(0.01)
        voice.send_text(wrap(scenario.voice_approval("evt-e")))
        assert json.loads(voice.receive_text())["type"] == "Error"


def test_dashboard_reconnect_replays_pending(setup):
    client, _ = setup
    with client.websocket_connect("/ws/agents") as agents:
        agents.send_text(wrap(scenario.proposed_directive("evt-p")))
        with client.websocket_connect("/ws/dashboard") as dashboard:
            assert recv(dashboard).event_id == "evt-p"


def test_hint_rules_enforced_in_contract():
    from pydantic import ValidationError
    from unstep.contracts import LocalHint

    with pytest.raises(ValidationError):
        LocalHint(text="cleared for takeoff Runway 33", kind="restrictive", source_doc_id="d1")
    with pytest.raises(ValidationError):
        LocalHint(text="hold short Runway 33", kind="restrictive")
    assert LocalHint(text="hold short Runway 33", kind="restrictive", source_doc_id="d1").kind == "restrictive"


def test_unknown_role_rejected(setup):
    client, _ = setup
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/hacker") as ws:
            ws.receive_text()


def test_tower_word_times_line_up_with_overlap():
    from unstep.clock import word_to_epoch_ms

    tx = scenario.tower_transcript()
    ev = scenario.anomaly_event()
    blocked = [w.word for w in tx.words
               if word_to_epoch_ms(tx.ptt_start, w.start) >= ev.overlap_start
               and word_to_epoch_ms(tx.ptt_start, w.end) <= ev.overlap_end]
    assert blocked == ["hold", "short", "Runway", "33"]
