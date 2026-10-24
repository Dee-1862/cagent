import asyncio
import json
from contextlib import ExitStack
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ground.gateway.app import create_app
from ground.gateway.sinks import QueuedSink, MemorySink
from ground.gateway.workflow import NoopTrigger

EXAMPLES = Path(__file__).resolve().parent.parent / "contracts" / "examples"
NOW = 1792771340000


def example(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def envelope(type_name: str, payload: dict | None = None) -> dict:
    return {"type": type_name, "payload": payload if payload is not None else example(type_name)}


@pytest.fixture
def gateway():
    sink, trigger = MemorySink(), NoopTrigger()
    app = create_app(sink, trigger, voice_controller_id="controller-1", clock=lambda: NOW)
    with TestClient(app) as client, ExitStack() as sockets:
        client.sockets = sockets
        yield client, sink, trigger


def connect(client, role):
    socket = client.sockets.enter_context(client.websocket_connect(f"/ws/{role}"))
    welcome = socket.receive_json()
    assert welcome == {"type": "Welcome", "payload": {"role": role, "now_ms": NOW}}
    return socket


def sync(socket):
    """Waits until the gateway has handled everything this socket sent."""
    socket.send_text("sync")
    assert socket.receive_json()["type"] == "Error"


def stored_types(sink):
    return [d["type"] for d in sink.documents]


def test_anomaly_event_reaches_dashboard_and_agents_and_is_stored(gateway):
    client, sink, trigger = gateway
    dashboard = connect(client, "dashboard")
    agents = connect(client, "agents")
    cockpit = connect(client, "cockpit")

    cockpit.send_json(envelope("AnomalyEvent"))

    for receiver in (dashboard, agents):
        message = receiver.receive_json()
        assert message["type"] == "AnomalyEvent"
        assert message["gateway_ts"] == NOW
        assert message["payload"]["event_id"] == "evt-0001"
    assert stored_types(sink) == ["AnomalyEvent"]
    assert sink.documents[0]["event_id"] == "evt-0001"
    assert sink.documents[0]["sender_role"] == "cockpit"
    assert trigger.fired == ["evt-0001"]


def test_voice_approval_creates_one_approved_directive(gateway):
    client, sink, _ = gateway
    cockpit = connect(client, "cockpit")
    agents = connect(client, "agents")
    voice = connect(client, "controller_voice")

    agents.send_json(envelope("ProposedDirective"))
    assert voice.receive_json()["type"] == "ProposedDirective"

    voice.send_json(envelope("VoiceApproval"))
    approved = cockpit.receive_json()
    assert approved["type"] == "ApprovedDirective"
    assert approved["payload"]["approved_via"] == "voice"
    assert approved["payload"]["approved_by"] == "controller-1"
    assert approved["payload"]["instruction_text"] == "Cessna 1-2-3, hold short Runway 33"
    assert voice.receive_json()["type"] == "ApprovedDirective"

    # A second "Approve" for the same event must not send the directive again.
    voice.send_json(envelope("VoiceApproval"))
    sync(voice)
    assert stored_types(sink).count("ApprovedDirective") == 1


def test_click_rejection_tells_the_cockpit(gateway):
    client, _, _ = gateway
    cockpit = connect(client, "cockpit")
    agents = connect(client, "agents")
    dashboard = connect(client, "dashboard")

    agents.send_json(envelope("ProposedDirective"))
    assert dashboard.receive_json()["type"] == "ProposedDirective"

    dashboard.send_json(envelope("ClickApproval", {**example("ClickApproval"), "decision": "reject"}))
    rejected = cockpit.receive_json()
    assert rejected["type"] == "DirectiveRejected"
    assert rejected["payload"]["rejected_via"] == "click"


def test_unclear_reply_sends_nothing_to_the_cockpit(gateway):
    client, sink, _ = gateway
    agents = connect(client, "agents")
    voice = connect(client, "controller_voice")
    dashboard = connect(client, "dashboard")

    agents.send_json(envelope("ProposedDirective"))
    dashboard.receive_json()
    voice.receive_json()

    voice.send_json(envelope("VoiceApproval", {**example("VoiceApproval"), "decision": "unclear"}))
    assert dashboard.receive_json()["type"] == "VoiceApproval"
    assert "ApprovedDirective" not in stored_types(sink)


@pytest.mark.parametrize("role", ["cockpit", "dashboard", "agents", "controller_voice"])
def test_no_client_can_send_an_approved_directive(gateway, role):
    client, sink, _ = gateway
    socket = connect(client, role)
    socket.send_json(envelope("ApprovedDirective"))
    error = socket.receive_json()
    assert error["type"] == "Error"
    assert f"{role} may not send ApprovedDirective" in error["payload"]["reason"]
    assert sink.documents == []


def test_approval_without_a_proposal_is_rejected(gateway):
    client, sink, _ = gateway
    voice = connect(client, "controller_voice")
    voice.send_json(envelope("VoiceApproval"))
    error = voice.receive_json()
    assert error["type"] == "Error"
    assert "no proposed directive" in error["payload"]["reason"]
    assert sink.documents == []


def test_wrong_sender_is_rejected(gateway):
    client, _, _ = gateway
    tower = connect(client, "tower")
    tower.send_json(envelope("AnomalyEvent"))
    assert tower.receive_json()["payload"]["reason"] == "tower may not send AnomalyEvent"


def test_invalid_payload_names_the_field(gateway):
    client, _, _ = gateway
    cockpit = connect(client, "cockpit")
    payload = example("AnomalyEvent")
    del payload["overlap_start"]
    cockpit.send_json(envelope("AnomalyEvent", payload))
    reason = cockpit.receive_json()["payload"]["reason"]
    assert reason.startswith("invalid AnomalyEvent: overlap_start")


def test_garbage_and_unknown_types_are_rejected(gateway):
    client, _, _ = gateway
    cockpit = connect(client, "cockpit")
    cockpit.send_text("not json")
    assert cockpit.receive_json()["type"] == "Error"
    cockpit.send_json({"type": "Nope", "payload": {}})
    assert cockpit.receive_json()["payload"]["reason"] == "unknown message type Nope"


def test_unknown_role_is_refused(gateway):
    client, _, _ = gateway
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/hacker") as ws:
            ws.receive_json()


def test_pilot_query_is_stored_but_not_relayed(gateway):
    client, sink, _ = gateway
    cockpit = connect(client, "cockpit")
    dashboard = connect(client, "dashboard")
    cockpit.send_json(envelope("PilotQuery"))
    cockpit.send_json(envelope("AnomalyEvent"))
    # The dashboard's next message is the AnomalyEvent, so the query was not relayed.
    assert dashboard.receive_json()["type"] == "AnomalyEvent"
    assert stored_types(sink) == ["PilotQuery", "AnomalyEvent"]


def test_time_endpoint_is_the_gateway_clock(gateway):
    client, _, _ = gateway
    assert client.get("/time").json() == {"now_ms": NOW}


def test_full_queue_drops_instead_of_blocking():
    class SlowSink(QueuedSink):
        async def store(self, document):
            await asyncio.sleep(1)

    async def run():
        sink = SlowSink(max_queue=1)
        sink.write({"type": "a"})
        sink.write({"type": "b"})
        return sink.dropped

    assert asyncio.run(run()) == 1
