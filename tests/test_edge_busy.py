"""Offline frequency arbitration, using cooperative FakeTTS cancellation."""
import asyncio
from unittest.mock import AsyncMock

from unstep.cockpit.edge import AudioOut, CockpitEdge
from unstep.cockpit.memory import LocalMemory
from unstep.cockpit.stt import FakeManualSTT, TurnEvent
from unstep.cockpit.tts import FakeTTS
from unstep.contracts import ApprovedDirective, AuditRecord, Slots


def make_edge():
    tts = FakeTTS(word_s=0.001)
    return CockpitEdge(memory=LocalMemory(), tts=tts, audio_out=AudioOut(None),
                       manual_stt_factory=lambda: FakeManualSTT([])), tts


async def queued(edge, text, event_id, **kwargs):
    task = asyncio.create_task(edge.speak(text, event_id, **kwargs))
    await asyncio.sleep(0)
    return task


async def started(edge):
    for _ in range(100):
        if edge.voice.current is not None:
            return
        await asyncio.sleep(0)
    raise AssertionError("speech did not start")


def audits(edge, stage):
    return [m for m in edge.outbox if isinstance(m, AuditRecord) and m.stage == stage]


def test_busy_cancels_and_replays_from_start():
    async def go():
        edge, tts = make_edge()
        task = await queued(edge, "Hold short runway three three and wait for clearance", "a")
        await started(edge)
        context = edge.voice.current
        await edge.set_frequency_busy(True)
        assert context in tts.cancelled
        await asyncio.sleep(0)
        assert not task.done() and not edge.out.clips
        await edge.set_frequency_busy(False)
        result = await task
        assert not result.speech.cancelled
        assert tts.spoken == [result.text, result.text]
        assert len(edge.out.clips) == 1
        assert [a.event_id for a in audits(edge, "held")] == ["a"]
        assert [a.event_id for a in audits(edge, "released")] == ["a"]
        assert audits(edge, "released")[0].payload["waited_ms"] >= 0
    asyncio.run(go())


def test_busy_queues_and_releases_in_order_without_dropping_critical_speech():
    async def go():
        edge, tts = make_edge()
        await edge.set_frequency_busy(True)
        tasks = [await queued(edge, text, event, kind=kind) for text, event, kind in [
            ("Hold position", "a", "directive"),
            ("Readback incorrect. Runway three three", "a", "advisory"),
            ("Stop", "b", "directive"),
            ("Hold short", "b", "directive"),
        ]]
        await edge.set_frequency_busy(True)
        assert tts.spoken == [] and all(not t.done() for t in tasks)
        await edge.set_frequency_busy(False)
        results = await asyncio.gather(*tasks)
        assert tts.spoken == [r.text for r in results]
        assert [a.event_id for a in audits(edge, "released")] == ["a", "a", "b", "b"]
        assert len(audits(edge, "held")) == 4
    asyncio.run(go())


def test_superseded_hint_keeps_original_event_position():
    async def go():
        edge, tts = make_edge()
        await edge.set_frequency_busy(True)
        hint = await queued(edge, "Likely hold short", "a", kind="hint")
        other = await queued(edge, "Stop", "b", kind="directive")
        directive = await queued(edge, "Hold short runway three three. Read back.", "a", kind="directive")
        await edge.set_frequency_busy(False)
        assert await hint is None
        assert tts.spoken == [(await directive).text, (await other).text]
        assert [a.event_id for a in audits(edge, "released")] == ["a", "b"]
    asyncio.run(go())


def test_cancelled_hint_can_be_superseded_before_cancel_finishes():
    async def go():
        edge, tts = make_edge()
        hint = await queued(edge, "Likely hold short runway three three awaiting controller", "a", kind="hint")
        await started(edge)
        await edge.set_frequency_busy(True)
        directive = await queued(edge, "Hold position. Read back.", "a", kind="directive")
        await edge.set_frequency_busy(False)
        assert await hint is None
        assert tts.spoken[-1] == (await directive).text
        assert len(tts.spoken) == 2
    asyncio.run(go())


def test_free_behavior_and_pilot_interrupt_are_unchanged():
    async def go():
        edge, tts = make_edge()
        result = await edge.speak("Hold position", "a")
        assert not result.speech.cancelled and len(edge.out.clips) == 1
        task = await queued(edge, "Hold short runway three three and wait for clearance", "b")
        await started(edge)
        await edge.on_turn(TurnEvent("turn.start"))
        assert (await task).speech.cancelled
        assert len(tts.spoken) == 2
        assert not audits(edge, "held") and not audits(edge, "released")
    asyncio.run(go())


def test_frequency_becomes_busy_again_during_release():
    async def go():
        edge, tts = make_edge()
        await edge.set_frequency_busy(True)
        first = await queued(edge, "Hold short runway three three and wait for clearance", "a", kind="directive")
        second = await queued(edge, "Stop", "b", kind="directive")
        release = asyncio.create_task(edge.set_frequency_busy(False))
        await started(edge)
        await edge.set_frequency_busy(True)
        await release
        assert not first.done() and not second.done()
        await edge.set_frequency_busy(False)
        assert tts.spoken == [(await first).text, (await first).text, (await second).text]
    asyncio.run(go())


def test_approved_handler_waits_for_delivery_before_readback():
    async def go():
        edge, tts = make_edge()
        edge.readback = AsyncMock(return_value="confirmed")
        edge._record = AsyncMock()
        await edge.set_frequency_busy(True)
        hint = await queued(edge, "Likely hold short", "a", kind="hint")
        msg = ApprovedDirective(event_id="a", instruction_text="Hold short runway 33",
                                slots=Slots(callsign=edge.callsign, action="hold_short", runway="33"),
                                approved_by="controller", approved_via="click")
        handler = asyncio.create_task(edge._on_approved(msg))
        await asyncio.sleep(0)
        assert not tts.spoken
        edge.readback.assert_not_awaited()
        assert not audits(edge, "directive_spoken")
        await edge.set_frequency_busy(False)
        await handler
        assert await hint is None
        assert len(tts.spoken) == 1 and "Read back" in tts.spoken[0]
        edge.readback.assert_awaited_once_with(msg)
        assert edge.outcomes["a"] == "confirmed"
    asyncio.run(go())


def test_offline_alert_is_held_and_uses_cached_audio():
    async def go():
        edge, tts = make_edge()
        await edge.start(connect=False)
        generated = list(tts.spoken)
        await edge.set_frequency_busy(True)
        alert = asyncio.create_task(edge.offline())
        await asyncio.sleep(0)
        assert not edge.out.clips
        await edge.set_frequency_busy(False)
        await alert
        assert tts.spoken == generated
        assert len(edge.out.clips) == 1
        assert [a.event_id for a in audits(edge, "released")] == ["offline"]
    asyncio.run(go())
