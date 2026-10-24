"""Observer transport, tower recovery and demo speech artifacts."""

import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from unstep import scenario
from unstep.cockpit.audio import ArraySource
from unstep.cockpit.edge import AudioOut, CockpitEdge
from unstep.cockpit.memory import LocalMemory
from unstep.cockpit.stt import CartesiaManualSTT, FakeManualSTT, FakeTurnSTT, Transcript
from unstep.cockpit.tts import FakeTTS
from unstep.contracts import AuditRecord, LocalHint, Word, unwrap, wrap
from unstep.gateway.server import ALLOWED_SENDERS, create_app
from unstep.gateway.sink import MemorySink
from unstep.ground import mock_agents, tower
from unstep.ground.blocked import blocked_words
from unstep.ground.voice_approval import ApprovalLoop, ControllerVoice, _answer


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr("unstep.gateway.server.gateway_token", lambda: None)
    return create_app(MemorySink(), demo_audio_dir=tmp_path)


@pytest.mark.parametrize("message", scenario.ALL_EXAMPLES, ids=lambda m: type(m).__name__)
def test_observer_receives_every_contract(app, message):
    kind = type(message).__name__
    role = next(role for role, types in ALLOWED_SENDERS.items() if kind in types)
    with TestClient(app) as client:
        if kind in {"VoiceApproval", "ApprovedDirective", "RejectedDirective"}:
            app.state.gateway.pending[message.event_id] = (scenario.proposed_directive(message.event_id), 10**15)
        with client.websocket_connect("/ws/observer") as observer:
            with client.websocket_connect(f"/ws/{role}") as sender:
                sender.send_text(wrap(message))
                received = observer.receive_json()
                assert received["type"] == kind
                if kind == "VoiceApproval":
                    assert observer.receive_json()["type"] == "ApprovedDirective"
                if kind in {"ApprovedDirective", "RejectedDirective"}:
                    assert app.state.gateway.sink.records[-1]["source"] == "gateway"


@pytest.mark.parametrize("payload", ["not json", wrap(scenario.anomaly_event()), b"binary"])
def test_observer_cannot_send(app, payload):
    with TestClient(app) as client, client.websocket_connect("/ws/observer") as observer:
        if isinstance(payload, bytes):
            observer.send_bytes(payload)
        else:
            observer.send_text(payload)
        assert observer.receive_json()["type"] == "Error"
        assert not app.state.gateway.sink.records
        assert not app.state.gateway.history


def test_replay_is_bounded_and_followed_by_live_messages(app):
    async def populate():
        for i in range(205):
            await app.state.gateway.emit(AuditRecord(event_id=str(i), stage="test", actor="test"))

    asyncio.run(populate())
    with TestClient(app) as client, client.websocket_connect("/ws/observer") as observer:
        assert [observer.receive_json()["data"]["event_id"] for _ in range(200)] == [str(i) for i in range(5, 205)]
        with client.websocket_connect("/ws/cockpit") as cockpit:
            cockpit.send_text(wrap(scenario.audit_record("live")))
            assert observer.receive_json()["data"]["event_id"] == "live"
    with TestClient(app) as client, client.websocket_connect("/ws/observer") as observer:
        replay = [observer.receive_json() for _ in range(200)]
        assert replay[-1]["data"]["event_id"] == "live"


def test_demo_static_and_audio(app, tmp_path):
    sf.write(tmp_path / "utterance.wav", np.zeros(160), 16000)
    with TestClient(app) as client:
        page = client.get("/demo/")
        assert page.status_code == 200 and "/ws/observer" in page.text
        assert "__UNSTEP_TOKEN_QUERY__" not in page.text
        assert client.get("/demo/index.html").status_code == 200
        assert client.get("/demo/audio/utterance.wav").headers["content-type"] == "audio/wav"
        assert client.get("/demo/audio/missing.wav").status_code == 404


def test_observer_keeps_token_and_origin_rules(app, monkeypatch):
    monkeypatch.setattr("unstep.gateway.server.gateway_token", lambda: "demo-test")
    with TestClient(app) as client:
        # The read-only page never carries the token; a local observer doesn't need it.
        assert "demo-test" not in client.get("/demo/").text
        for url, headers in [
            ("/ws/observer?token=demo-test", {"origin": "https://elsewhere.example"}),
            ("/ws/dashboard", {}),
        ]:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(url, headers=headers):
                    pass
        with client.websocket_connect("/ws/observer?token=demo-test") as observer:
            observer.send_text("hello")
            assert observer.receive_json()["type"] == "Error"


@pytest.mark.parametrize("start,end,expected", [
    (0, 499, []), (0, 500, ["word"]), (500, 1000, ["word"]),
    (501, 1000, []), (1000, 1500, []), (0, 0, []), (1000, 0, []),
    (-1000, 2000, ["word"]),
])
def test_blocked_words_partial_overlap_and_offsets(start, end, expected):
    transcript = scenario.tower_transcript(900000)
    transcript.words = [Word(word="word", start=0, end=1), Word(word="zero", start=0.2, end=0.2)]
    assert blocked_words(transcript, 900000 + start, 900000 + end) == expected
    transcript.words = []
    assert blocked_words(transcript, 900000 + start, 900000 + end) == []


def test_mock_proposal_uses_tower_and_hint_agreement():
    event, transcript = scenario.anomaly_event(), scenario.tower_transcript()
    proposal = mock_agents.propose(event, transcript)
    assert proposal.instruction_text == transcript.text
    assert proposal.transcript_id == transcript.transcript_id
    assert proposal.blocked_words == ["hold", "short", "Runway", "33"]
    assert proposal.confidence == "high"
    assert proposal.confidence_method == "tower transcript match + local hint agrees"
    event.local_hint = LocalHint()
    assert mock_agents.propose(event, transcript).confidence == "medium"
    transcript.ptt_end = event.squelch_open
    assert mock_agents.propose(event, transcript).transcript_id is None
    transcript = scenario.tower_transcript()
    transcript.frequency = "123.450"
    assert mock_agents.propose(event, transcript).confidence == "low"


def test_mock_runner_remembers_latest_per_frequency(monkeypatch):
    class Socket:
        def __init__(self):
            self.sent = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def __aiter__(self):
            async def messages():
                old = scenario.tower_transcript()
                old.transcript_id = "old"
                other = scenario.tower_transcript()
                other.frequency = "123.450"
                for message in (old, scenario.tower_transcript(), other, scenario.anomaly_event()):
                    yield wrap(message)
            return messages()

        async def send(self, raw):
            self.sent.append(unwrap(raw)[1])

    socket = Socket()
    monkeypatch.setattr(mock_agents.websockets, "connect", lambda *a, **kw: socket)
    asyncio.run(mock_agents.run("ws://localhost"))
    assert socket.sent[0].transcript_id == "tx-0001"


def test_fake_tower_alignment():
    transcript = asyncio.run(tower.FakeTowerTranscriber().transcribe(b"", 800000, 802600, "123.450", "N456"))
    assert (transcript.ptt_start, transcript.ptt_end) == (800000, 802600)
    assert (transcript.frequency, transcript.callsign) == ("123.450", "N456")
    assert transcript.words == scenario.tower_transcript().words
    assert blocked_words(transcript, 801300, 802600) == ["hold", "short", "Runway", "33"]


def test_tower_dual_stream_text_words_and_pacing(monkeypatch):
    streams, sleeps = [], []

    class Stream(FakeManualSTT):
        def __init__(self, **kwargs):
            self.options = kwargs
            self.audio = []
            result = Transcript("keyed text") if kwargs["model"] == "ink-2" else Transcript(
                "different text", [Word(word=" word", start=0.02, end=0.1)])
            super().__init__([result])
            streams.append(self)

        async def send_audio(self, pcm):
            self.audio.append(pcm)

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(tower.asyncio, "sleep", sleep)
    monkeypatch.setattr(tower.time, "monotonic", lambda: 0)
    pcm = b"\x00\x00" * 2400
    result = asyncio.run(tower.TowerTranscriber(Stream).transcribe(pcm, 1000, 1150, "118.7", "N123"))
    assert result.text == "keyed text" and result.words[0].word == "word"
    assert result.words[0].start == 0.02 and result.ptt_start == 1000
    assert all(b"".join(stream.audio) == pcm for stream in streams)
    assert "N123" in streams[0].options["keyterms"]
    assert streams[1].options == {"model": "ink-whisper", "timestamp_granularities": ["word"]}
    assert sleeps[:2] == pytest.approx([0.1, 0.15])
    query = parse_qs(urlsplit(CartesiaManualSTT(api_key="test", model="ink-whisper",
                                              timestamp_granularities=["word"]).url).query)
    assert query["timestamp_granularities"] == ["word"] and "keyterm" not in query


class Link:
    async def send(self, message):
        return True


@pytest.mark.parametrize("enabled", [False, True])
def test_edge_audit_text_words_and_optional_audio(tmp_path, enabled):
    async def go():
        edge = CockpitEdge(link=Link(), memory=LocalMemory(), tts=FakeTTS(), audio_out=AudioOut(None),
                           manual_stt_factory=lambda: FakeManualSTT(["heard on radio"]),
                           demo_audio_dir=tmp_path if enabled else None)
        spoken = await edge.speak("Hold short Runway 33", event_id="event")
        await edge.run_audio(ArraySource(np.full(320, 0.1, dtype=np.float32)))
        return edge, spoken

    edge, spoken = asyncio.run(go())
    payload = edge.sent[0].payload
    assert payload["spoken_text"] == spoken.text and payload["party"] == "pilot_ear"
    assert payload["words"][0]["start"] == pytest.approx(0.22)
    radio = next(m.payload for m in edge.sent if m.stage == "radio_received")
    assert radio["heard_text"] == "heard on radio" and radio["party"] == "radio"
    if enabled:
        for entry in (payload, radio):
            assert (tmp_path / Path(entry["audio_url"]).name).is_file()
    else:
        assert "audio_url" not in payload and "audio_url" not in radio
        assert not list(tmp_path.iterdir()) and edge.demo_audio_dir is None


@pytest.mark.parametrize("enabled", [False, True])
def test_controller_audit_text_and_audio(tmp_path, enabled):
    async def go():
        loop, messages = ApprovalLoop(), []
        loop.enqueue(scenario.proposed_directive())

        async def send(raw):
            messages.append(unwrap(raw)[1])

        await _answer(loop, loop.start_next(), ControllerVoice(FakeTTS(), tmp_path if enabled else None),
                      lambda: FakeTurnSTT(["Approve"]), send)
        return messages

    messages = asyncio.run(go())
    payload = next(m.payload for m in messages if isinstance(m, AuditRecord) and m.stage == "controller_voice")
    assert payload["heard_text"] == "Approve" and payload["party"] == "controller"
    spoken = [u for u in payload["utterances"] if u["party"] == "controller_ear"]
    assert len(spoken) == 2 and spoken[0]["spoken_text"].endswith("Approve?")
    assert spoken[1]["spoken_text"].startswith("Approved, sending")
    if enabled:
        assert all((tmp_path / Path(u["audio_url"]).name).is_file() for u in spoken)
    else:
        assert len(messages) == 2 and not list(tmp_path.iterdir())


def test_pilot_readback_and_query_audits(tmp_path):
    async def go():
        edge = CockpitEdge(link=Link(), memory=LocalMemory(), tts=FakeTTS(), audio_out=AudioOut(None),
                           manual_stt_factory=lambda: FakeManualSTT([]),
                           turn_stt_factory=lambda: FakeTurnSTT(["Hold short runway 33, N123AB"]),
                           demo_audio_dir=tmp_path)
        await edge.start(connect=False)
        await edge.readback(scenario.approved_directive())
        question = "Unstep, which taxiway?"
        query = await edge.ask(question, audio=b"\x00\x00" * 160)
        return edge, question, query

    edge, question, query = asyncio.run(go())
    readback = next(m.payload for m in edge.sent if isinstance(m, AuditRecord) and m.stage == "readback")
    assert readback["heard_text"] == "Hold short runway 33, N123AB" and readback["party"] == "pilot"
    payload = next(m.payload for m in edge.sent if isinstance(m, AuditRecord) and m.stage == "pilot_query")
    assert payload["heard_text"] == question and payload["answer"] == query.answer
    assert (tmp_path / Path(payload["audio_url"]).name).is_file()


def test_demo_page_never_carries_token_and_observer_is_local_only(monkeypatch):
    import pytest
    from fastapi.testclient import TestClient
    from unstep.gateway.server import create_app
    from unstep.gateway.sink import MemorySink

    monkeypatch.setenv("UNSTEP_GATEWAY_TOKEN", "s3cret")
    client = TestClient(create_app(MemorySink()))
    page = client.get("/demo/")
    assert "s3cret" not in page.text
    with client.websocket_connect("/ws/observer"):
        pass  # local observer needs no token
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/dashboard") as ws:
            ws.receive_text()  # a role that can approve still needs the token
