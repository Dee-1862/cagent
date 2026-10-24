"""W3: replays to the manual STT endpoint skip real-time pacing; P7b alignment reports reach the gateway."""

import asyncio

from unstep import config
from unstep.clock import now_ms
from unstep.contracts import AuditRecord
from unstep.ground import tower
from unstep.live.room import LiveRoom

from tests.test_live_room import make_room, wait_for  # noqa: F401 (fixture)
from tests.test_stream_mic import frames
from tests.test_tower_alignment import WHISPER, Pair


def test_realtime_replay_is_off_by_default_and_env_turns_it_on(monkeypatch):
    monkeypatch.delenv("UNSTEP_REALTIME_REPLAY", raising=False)
    assert config.realtime_replay() is False
    monkeypatch.setenv("UNSTEP_REALTIME_REPLAY", "1")
    assert config.realtime_replay() is True
    assert LiveRoom(None, live=False).realtime_replay is True


def test_tower_transcriber_fast_send_never_sleeps(monkeypatch):
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(tower.asyncio, "sleep", sleep)
    pcm = b"\x00\x00" * 16000  # 1 s
    fast = tower.TowerTranscriber(stt_factory=Pair("hold short runway 33", WHISPER), realtime=False)
    asyncio.run(fast.transcribe(pcm, 0, 1000, "118.7"))
    assert sleeps == []
    paced = tower.TowerTranscriber(stt_factory=Pair("hold short runway 33", WHISPER))
    asyncio.run(paced.transcribe(pcm, 0, 1000, "118.7"))
    assert sleeps  # the default still paces, for callers that want it (presenter mode)


def _record_tower_link(room):
    sent = []
    link = room.links["tower"]
    original = link.send

    async def send(msg):
        sent.append(msg)
        return await original(msg)

    link.send = send
    return sent


def test_streamed_tower_call_sends_its_alignment_report(make_room):
    async def go():
        room, atc, pilot = await make_room()
        sent = _record_tower_link(room)
        room.stream_stt_factory = lambda s: tower.TowerStream(
            stt_factory=Pair("Cessna 1-2-3, hold short of runway 33.", WHISPER))
        for f in frames(1.5, now_ms() - 8000):
            await room.handle("atc", f)
        await room.handle("atc", {"type": "mic_end"})
        await wait_for(lambda: any(isinstance(m, AuditRecord) and m.stage == "tower_word_alignment" for m in sent))
        t = next(iter(room.transcripts.values()))
        audit = next(m for m in sent if isinstance(m, AuditRecord) and m.stage == "tower_word_alignment")
        assert audit.event_id == t.transcript_id
        assert audit.payload["interpolated"] == [{"index": 4, "word": "of"}]
        assert [w.word for w in t.words][:2] == ["Cessna", "1-2-3"] and not room.alignments
        await room.stop()

    asyncio.run(go())


def test_key_tells_every_cockpit_when_the_frequency_is_busy_or_free(make_room):
    async def go():
        room, atc, pilot = await make_room()
        calls = []
        for cs, edge in room.edges.items():
            async def busy(b, cs=cs):
                calls.append((cs, b))
            edge.set_frequency_busy = busy
        n = len(room.edges)
        assert n >= 1
        room._key("atc", True)
        room._key("H456", True)  # second key: still busy, no second signal
        await asyncio.sleep(0.05)
        assert sorted(calls) == sorted((cs, True) for cs in room.edges)
        room._key("atc", False)
        await asyncio.sleep(0.05)
        assert len(calls) == n  # H456 still keyed
        room._key("H456", False)
        await asyncio.sleep(0.05)
        assert [c for c in calls if c[1] is False] == [(cs, False) for cs in room.edges]
        await room.stop()

    asyncio.run(go())
