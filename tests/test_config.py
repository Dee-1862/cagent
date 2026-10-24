"""Connection settings come from the environment, and the token reaches every client."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from unstep import config
from unstep.gateway.server import create_app
from unstep.gateway.sink import MemorySink


@pytest.fixture
def no_token(monkeypatch):
    monkeypatch.delenv("UNSTEP_GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("unstep_gateway_token", raising=False)


def test_gateway_url_defaults_and_override(monkeypatch, no_token):
    monkeypatch.delenv("UNSTEP_GATEWAY_URL", raising=False)
    assert config.ws_url("cockpit") == "ws://127.0.0.1:8765/ws/cockpit"
    monkeypatch.setenv("UNSTEP_GATEWAY_URL", "ws://ground.example:9000/")
    assert config.ws_url("monitor") == "ws://ground.example:9000/ws/monitor"
    assert config.ws_url("agents", "ws://other:1") == "ws://other:1/ws/agents"


def test_token_is_added_and_escaped(monkeypatch):
    monkeypatch.setenv("UNSTEP_GATEWAY_TOKEN", "a b&c")
    assert config.ws_url("cockpit", "ws://g:1") == "ws://g:1/ws/cockpit?token=a%20b%26c"


def test_vendor_settings_have_defaults_and_overrides(monkeypatch):
    for name in ("CARTESIA_VERSION", "CARTESIA_STT_MODEL", "CARTESIA_TTS_MODEL", "ELASTIC_EVENTS_INDEX"):
        monkeypatch.delenv(name, raising=False)
    assert config.cartesia_version() == config.DEFAULT_CARTESIA_VERSION
    assert config.cartesia_stt_model() == config.DEFAULT_CARTESIA_STT_MODEL
    assert config.cartesia_tts_model() == config.DEFAULT_CARTESIA_TTS_MODEL
    assert config.elastic_events_index() == config.DEFAULT_EVENTS_INDEX
    monkeypatch.setenv("CARTESIA_STT_MODEL", "ink-whisper")
    assert config.cartesia_stt_model() == "ink-whisper"


def test_gateway_requires_the_token_when_set(monkeypatch):
    monkeypatch.setenv("UNSTEP_GATEWAY_TOKEN", "s3cret")
    client = TestClient(create_app(MemorySink()))
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/cockpit") as ws:
            ws.receive_text()
    path = config.ws_url("cockpit", "").split("/ws/", 1)[1]
    with client.websocket_connect(f"/ws/{path}") as ws:
        ws.send_text('{"type": "Nope", "data": {}}')
        assert ws.receive_json()["type"] == "Error"  # connected and talking


def test_dashboard_page_carries_the_token(monkeypatch):
    monkeypatch.setenv("UNSTEP_GATEWAY_TOKEN", "s3cret")
    html = TestClient(create_app(MemorySink())).get("/").text
    assert "/ws/dashboard?token=s3cret" in html
    assert "__UNSTEP_TOKEN_QUERY__" not in html


def test_dashboard_page_without_token(monkeypatch, no_token):
    html = TestClient(create_app(MemorySink())).get("/").text
    assert "/ws/dashboard`" in html


def test_token_already_in_the_url_is_kept(monkeypatch):
    monkeypatch.setenv("UNSTEP_GATEWAY_TOKEN", "from-env")
    assert config.ws_url("controller_voice", "ws://test?token=test") == "ws://test/ws/controller_voice?token=test"
    assert config.ws_url("cockpit", "ws://g:1/base/") == "ws://g:1/base/ws/cockpit?token=from-env"
