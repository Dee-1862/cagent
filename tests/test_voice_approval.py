"""Controller approval logic, audio ordering, cancellation and gateway authority."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from unstep.cockpit.stt import FakeTurnSTT
from unstep.cockpit.tts import FakeTTS
from unstep.contracts import ApprovedDirective, ProposedDirective, RejectedDirective, Slots, TowerTranscript, VoiceApproval, unwrap, wrap
from unstep.gateway.server import create_app
from unstep.gateway.sink import MemorySink
from unstep.ground import voice_approval
from unstep.ground.voice_approval import ApprovalLoop, ControllerVoice, _answer


def proposal(event_id="event-1"):
    return ProposedDirective(event_id=event_id, instruction_text="hold short Runway 33",
                             slots=Slots(callsign="Cessna 1-2-3", action="hold short", runway="33"),
                             confidence="high", confidence_method="test")


def listening(clock=lambda: 0):
    loop = ApprovalLoop(clock)
    loop.enqueue(proposal())
    assert loop.start_next() == "Blocked call to Cessna 1-2-3: hold short Runway 33. Approve?"
    loop.prompted()
    return loop


@pytest.mark.parametrize("text", ["approve", "Approved!", " AFFIRM ", "send it", "yes approve"])
def test_approve_variants(text):
    assert ApprovalLoop.classify(text) == "approve"


@pytest.mark.parametrize("text", ["reject", "Negative.", "cancel", "I'll reissue", "I’ll reissue"])
def test_reject_variants(text):
    assert ApprovalLoop.classify(text) == "reject"


@pytest.mark.parametrize("text", ["", "yes", "maybe", "do not approve", "approve reject", "cancel then approve",
                                  "affirm negative", "send it I'll reissue", "approve event-2", "unapproved"])
def test_unclear_variants(text):
    assert ApprovalLoop.classify(text) == "unclear"


def test_repeat_back_gates_approval():
    loop = listening()
    assert loop.repeated() is None
    assert loop.heard("event-1", "Approve") == "Approved, sending to Cessna 1-2-3."
    assert loop.current is not None
    result = loop.repeated()
    assert (result.decision, result.attempt, result.heard_text) == ("approve", 1, "Approve")
    assert loop.current is None and loop.repeated() is None


def test_reject():
    loop = listening()
    assert loop.heard("event-1", "negative") == "Rejected. Reissue by voice."
    assert loop.repeated().decision == "reject"


def test_unclear_twice_and_different_event():
    loop = listening()
    assert loop.heard("another-event", "Approve") == "Say again, approve or reject?"
    result = loop.heard("event-1", "approve reject")
    assert (result.decision, result.attempt) == ("unclear", 2)
    assert loop.heard("event-1", "Approve") is None


def test_retry_then_approve():
    loop = listening()
    loop.heard("event-1", "maybe")
    loop.heard("event-1", "approve")
    assert loop.repeated().attempt == 2


def test_timeout_shared_by_both_attempts():
    now = [0.0]
    loop = listening(lambda: now[0])
    now[0] = 9.0
    assert loop.timeout() is None
    loop.heard("event-1", "maybe")
    now[0] = 10.0
    result = loop.heard("event-1", "Approve")
    assert result.decision == "unclear" and result.attempt == 2
    assert loop.repeated() is None


def test_silence_timeout():
    now = [0.0]
    loop = listening(lambda: now[0])
    now[0] = 10.0
    result = loop.timeout()
    assert result.decision == "unclear" and result.attempt == 1
    assert loop.timeout() is None


@pytest.mark.parametrize("approved", [True, False])
def test_decided_elsewhere_cancels(approved):
    loop = listening()
    loop.heard("event-1", "Approve")
    if approved:
        message = ApprovedDirective(event_id="event-1", instruction_text="hold short Runway 33",
                                    slots=proposal().slots, approved_by="controller", approved_via="click")
    else:
        message = RejectedDirective(event_id="event-1", rejected_by="controller", rejected_via="click")
    assert loop.decided(message)
    assert loop.repeated() is None
    assert loop.heard("event-1", "Approve") is None
    loop.enqueue(proposal())
    assert loop.start_next() is None


def test_two_proposals_in_order_and_queued_cancellation():
    loop = listening()
    loop.enqueue(proposal("event-2"))
    loop.enqueue(proposal("event-2"))
    loop.enqueue(proposal("event-3"))
    assert loop.start_next() is None
    loop.decided(RejectedDirective(event_id="event-3", rejected_by="controller", rejected_via="click"))
    loop.heard("event-1", "approve")
    assert loop.repeated().event_id == "event-1"
    assert loop.start_next()
    loop.prompted()
    loop.heard("event-2", "reject")
    result = loop.repeated()
    assert result.event_id == "event-2" and result.attempt == 1
    assert loop.start_next() is None


@pytest.mark.parametrize("answers,decision", [(["Approve"], "approve"), (["Reject"], "reject"),
                                              (["maybe", "maybe"], "unclear")])
def test_audio_before_send(answers, decision):
    async def go():
        loop, tts, messages = ApprovalLoop(), FakeTTS(), []
        loop.enqueue(proposal())

        async def send(raw):
            _, msg = unwrap(raw)
            if isinstance(msg, VoiceApproval):
                if decision == "approve":
                    assert tts.spoken[-1] == "Approved, sending to Cessna one two tree."
                elif decision == "reject":
                    assert tts.spoken[-1] == "Rejected. Reissue by voice."
            messages.append(msg)

        await _answer(loop, loop.start_next(), ControllerVoice(tts), lambda: FakeTurnSTT(answers), send)
        assert messages[0].decision == decision
        assert messages[1].stage == "controller_voice"
        if decision == "unclear":
            assert tts.spoken[-1] == "Say again, approve or reject?"
            assert messages[0].attempt == 2

    asyncio.run(go())


def test_gateway_spoken_approval_and_other_roles_cannot_approve():
    sink = MemorySink()
    app = create_app(sink)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/agents") as agents, client.websocket_connect("/ws/cockpit") as cockpit:
            agents.send_text(wrap(proposal()))
            with client.websocket_connect("/ws/controller_voice") as controller:
                _, replayed = unwrap(controller.receive_text())
                assert replayed.event_id == "event-1"
                # Even a valid VoiceApproval is powerless from every other role.
                for role in ("agents", "cockpit", "tower", "dashboard", "monitor"):
                    with client.websocket_connect(f"/ws/{role}") as wrong:
                        if role == "dashboard":
                            wrong.receive_text()  # pending replay
                        wrong.send_text(wrap(VoiceApproval(event_id="event-1", heard_text="Approve", decision="approve")))
                        assert wrong.receive_json()["type"] == "Error"
                        assert "event-1" in app.state.gateway.pending
                with client.websocket_connect("/ws/tower") as tower:
                    tower.send_text(wrap(TowerTranscript(transcript_id="radio", frequency="118.7",
                                                        ptt_start=0, ptt_end=1, text="Approve")))
                    tower.send_text(wrap(VoiceApproval(event_id="event-1", heard_text="Approve", decision="approve")))
                    assert tower.receive_json()["type"] == "Error"
                assert not any(r["type"] == "ApprovedDirective" for r in sink.records)

                async def speak_approval():
                    loop, tts = ApprovalLoop(), FakeTTS()
                    loop.enqueue(replayed)

                    async def send(raw):
                        if unwrap(raw)[0].type == "VoiceApproval":
                            assert tts.spoken[-1] == "Approved, sending to Cessna one two tree."
                        controller.send_text(raw)

                    await _answer(loop, loop.start_next(), ControllerVoice(tts), lambda: FakeTurnSTT(["Approve"]), send)

                asyncio.run(speak_approval())
                _, directive = unwrap(cockpit.receive_text())
                assert isinstance(directive, ApprovedDirective)
                assert directive.approved_via == "voice"
                assert directive.instruction_text == proposal().instruction_text


@pytest.mark.parametrize("during_repeat", [False, True])
def test_runner_cancels_speech_and_continues_queue(monkeypatch, during_repeat):
    async def go():
        incoming, sent = asyncio.Queue(), []
        speaking, cancelled, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class SlowTTS(FakeTTS):
            async def speak(self, text, context_id=None, on_chunk=None):
                if not speaking.is_set() and (not during_repeat or text.startswith("Approved")):
                    speaking.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.set()
                return await super().speak(text, context_id, on_chunk)

        class Socket:
            def __aiter__(self):
                return self

            async def __anext__(self):
                return await incoming.get()

            async def send(self, raw):
                sent.append(unwrap(raw)[1])
                if len(sent) == 2:
                    completed.set()

        @asynccontextmanager
        async def connect(url):
            assert url == "ws://test/ws/controller_voice?token=test"
            yield Socket()

        monkeypatch.setattr(voice_approval.websockets, "connect", connect)
        tts = SlowTTS()
        task = asyncio.create_task(voice_approval.run("ws://test?token=test", tts, lambda: FakeTurnSTT(["Approve"])))
        try:
            await incoming.put(wrap(proposal()))
            await asyncio.wait_for(speaking.wait(), 2)
            await incoming.put(wrap(proposal("event-2")))
            await incoming.put('{"type":"Error","data":{"message":"test"}}')
            await incoming.put(wrap(RejectedDirective(event_id="event-1", rejected_by="controller", rejected_via="click")))
            await asyncio.wait_for(completed.wait(), 2)
            assert cancelled.is_set() and tts.cancelled
            assert sent[0].event_id == "event-2" and sent[0].decision == "approve"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(go())


@pytest.mark.parametrize("empty", [False, True])
def test_runner_silence_sends_only_unclear(empty):
    async def go():
        class ShortWindow(ApprovalLoop):
            def prompted(self):
                super().prompted()
                self.deadline = self.clock() + 0.01

        class SilentSTT(FakeTurnSTT):
            async def events(self):
                await asyncio.Event().wait()
                yield  # keep the source an async generator

        loop, sent = ShortWindow(), []
        loop.enqueue(proposal())

        async def send(raw):
            sent.append(unwrap(raw)[1])

        factory = (lambda: FakeTurnSTT([])) if empty else (lambda: SilentSTT([]))
        await asyncio.wait_for(_answer(loop, loop.start_next(), ControllerVoice(FakeTTS()), factory, send), 2)
        assert sent[0].decision == "unclear" and sent[0].attempt == 1
        assert len(sent) == 2 and loop.current is None

    asyncio.run(go())


def test_failed_repeat_back_never_sends_approval():
    async def go():
        class BrokenTTS(FakeTTS):
            async def speak(self, text, context_id=None, on_chunk=None):
                if text.startswith("Approved"):
                    raise RuntimeError("audio unavailable")
                return await super().speak(text, context_id, on_chunk)

        loop, sent = ApprovalLoop(), []
        loop.enqueue(proposal())

        async def send(raw):
            sent.append(raw)

        with pytest.raises(RuntimeError, match="audio unavailable"):
            await _answer(loop, loop.start_next(), ControllerVoice(BrokenTTS()), lambda: FakeTurnSTT(["Approve"]), send)
        assert not sent

    asyncio.run(go())
