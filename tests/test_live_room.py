"""Live room: real overlaps on the shared frequency, agents in the middle, the human for edge cases."""

import asyncio

import numpy as np
import pytest

from unstep.clock import now_ms
from unstep.cockpit.audio import SAMPLE_RATE, read_wav
from unstep.cockpit.memory import LocalMemory
from unstep.cockpit.tts import FakeTTS, SpeechResult
from unstep.config import ROOT
from unstep.gateway.server import create_app
from unstep.gateway.sink import MemorySink
from unstep.live import room as room_mod
from unstep.live.radio import KeyedSquelch, Transmission, clusters, heard_text, mix
from unstep.live.room import LiveRoom

CLIPS = ROOT / "assets" / "clips" / "real"
TOWER_TEXT = "Cessna one two three, hold short runway three three."
TOWER_WORDS = [("Cessna", 0.1, 0.5), ("one", 0.5, 0.75), ("two", 0.75, 0.95), ("three,", 0.95, 1.25),
               ("hold", 1.4, 1.6), ("short", 1.6, 1.9), ("runway", 1.9, 2.3), ("three", 2.3, 2.6),
               ("three.", 2.6, 3.0)]


def clip(name):
    return read_wav(CLIPS / name)


def tx(station, name, start, text=None, words=()):
    return Transmission(station, start, clip(name), text=text, words=list(words))


# ---------------------------------------------------------------- radio


def test_clusters_group_only_overlapping_transmissions():
    a = Transmission("atc", 0, np.zeros(SAMPLE_RATE * 2, np.float32))  # 0 to 2000 ms
    b = Transmission("H456", 1500, np.zeros(SAMPLE_RATE, np.float32))  # 1500 to 2500 ms
    c = Transmission("N123AB", 5000, np.zeros(SAMPLE_RATE, np.float32))
    assert [[t.station for t in g] for g in clusters([c, b, a])] == [["atc", "H456"], ["N123AB"]]


def test_mix_knows_exactly_who_was_keyed():
    a = Transmission("atc", 1000, np.full(SAMPLE_RATE * 2, 0.1, np.float32))
    b = Transmission("H456", 2500, np.full(SAMPLE_RATE, 0.1, np.float32))
    m = mix([a, b])
    assert [(o.start_ms, o.end_ms, o.stations) for o in m.overlaps] == [(2500, 3000, ["H456", "atc"])]
    assert m.heard_by("N123AB") and not m.heard_by("H456")
    squelch = KeyedSquelch(m.any_keyed)
    opened = [squelch.update(None) for _ in m.keyed]
    assert opened[0] and not opened[-1]  # opens on the carrier, closes in the tail


def test_heard_text_keeps_words_before_the_overlap():
    tower = Transmission("atc", 0, np.zeros(SAMPLE_RATE * 3, np.float32), text=TOWER_TEXT, words=TOWER_WORDS)
    other = Transmission("H456", 1300, np.zeros(SAMPLE_RATE, np.float32))
    assert heard_text(tower, mix([tower, other]).overlaps) == "Cessna one two three, [static]"
    assert heard_text(tower, []) == TOWER_TEXT


# ---------------------------------------------------------------- room


class FakeBrowser:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


class ClipTTS:
    """Speaks known lines with the real recorded clips, so the overlap detector hears real speech."""

    LINES = {TOWER_TEXT: ("clean_call.wav", TOWER_WORDS)}

    async def speak(self, text, context_id=None, on_chunk=None):
        name, words = self.LINES.get(text, ("helicopter_call.wav", []))
        pcm = (clip(name) * 32767).astype("<i2").tobytes()
        return SpeechResult(pcm, SAMPLE_RATE, 0.0, list(words))


@pytest.fixture
def make_room(monkeypatch):
    monkeypatch.setattr(room_mod, "create_memory", LocalMemory)
    monkeypatch.setattr(room_mod, "READBACK_WAIT_S", 5.0)

    async def build(autonomy=True):
        app = create_app(MemorySink())
        room = LiveRoom(app.state.gateway, live=False, tts_factory=lambda voice: ClipTTS(),
                        advisory_tts=FakeTTS())
        await room.start()
        room.policy.enabled = autonomy
        atc, pilot = FakeBrowser(), FakeBrowser()
        await room.join("atc", atc)
        await room.join("N123AB", pilot)
        return room, atc, pilot

    return build


async def wait_for(predicate, timeout=20.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out")
        await asyncio.sleep(0.05)


async def stepped_on(room):
    start = now_ms() - 10_000  # in the past, so the room processes it at once
    await room.transmit(tx("atc", "clean_call.wav", start, TOWER_TEXT, TOWER_WORDS))
    await room.transmit(tx("H456", "helicopter_call.wav", start + 1300, "Helicopter four five six, request transition"))


def only_trace(room):
    return next(iter(room.traces.values())) if room.traces else None


def test_stepped_on_call_runs_end_to_end(make_room):
    async def go():
        room, atc, pilot = await make_room()
        await stepped_on(room)
        await wait_for(lambda: only_trace(room) and only_trace(room)["status"] in ("needs_you", "auto_relayed",
                                                                                   "delivered"))
        trace = only_trace(room)
        assert trace["callsign"] == "N123AB"
        if trace["status"] == "needs_you":
            assert trace["policy"]["reasons"]  # the controller is told why
            await room.decide(trace["event_id"], approve=True)
        await wait_for(lambda: only_trace(room)["status"] == "delivered")
        # Pilot reads back on the radio, clean this time.
        await room.transmit(Transmission("N123AB", now_ms() - 8000, clip("correct_readback.wav"),
                                         text="Hold short runway three three, Cessna one two three"))
        await wait_for(lambda: only_trace(room)["status"] in ("confirmed", "readback_wrong"))
        trace = only_trace(room)
        kinds = [s["kind"] for s in trace["steps"]]
        assert kinds[:3] == ["detected", "hint", "proposed"] or kinds[:2] == ["detected", "proposed"]
        assert {"approved", "delivered", "readback"} <= set(kinds)
        assert trace["tower"]["text"] == TOWER_TEXT
        flows = {(m["from"], m["to"]) for m in atc.messages if m["type"] == "flow"}
        assert {("radio", "cockpit:N123AB"), ("cockpit:N123AB", "gateway"), ("ground", "gateway"),
                ("gateway", "cockpit:N123AB"), ("gateway", "elastic")} <= flows
        assert any(m["type"] == "advisory_audio" for m in pilot.messages)
        assert not any(m["type"] == "advisory_audio" for m in atc.messages)
        await room.stop()

    asyncio.run(go())


def test_autonomy_off_sends_every_event_to_the_controller(make_room):
    async def go():
        room, atc, _ = await make_room(autonomy=False)
        await stepped_on(room)
        await wait_for(lambda: only_trace(room) and only_trace(room)["status"] == "needs_you")
        trace = only_trace(room)
        assert "controller switched auto-relay off" in trace["policy"]["reasons"]
        assert trace["deadline_ms"] > now_ms()
        await room.decide(trace["event_id"], approve=False)
        await wait_for(lambda: only_trace(room)["status"] == "rejected")
        await room.stop()

    asyncio.run(go())


def test_clean_call_creates_no_event(make_room):
    async def go():
        room, atc, _ = await make_room()
        await room.transmit(tx("atc", "clean_call.wav", now_ms() - 10_000, TOWER_TEXT, TOWER_WORDS))
        await wait_for(lambda: any(m["type"] == "transcript" for m in atc.messages))
        await asyncio.sleep(0.5)
        assert room.traces == {}
        radio = [m for m in atc.messages if m["type"] == "radio"]
        assert radio and radio[0]["overlaps"] == []
        await room.stop()

    asyncio.run(go())


# ---------------------------------------------------------------- web app


def test_app_serves_seats_and_joins(monkeypatch):
    from fastapi.testclient import TestClient
    from unstep.live.app import create_live_app

    monkeypatch.setattr(room_mod, "create_memory", LocalMemory)
    monkeypatch.delenv("UNSTEP_GATEWAY_TOKEN", raising=False)
    app = create_live_app(live=False, sink=MemorySink())
    client = TestClient(app)
    assert "Pick your seat" in client.get("/live/").text
    assert client.get("/live/static/live.js").status_code == 200
    seats = client.get("/live/stations").json()
    assert [s["id"] for s in seats["stations"]] == ["atc", "N123AB", "H456", "observer"]
    with client.websocket_connect("/live/ws/atc") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["you"] == "atc" and hello["autonomy"] is True
        assert {n["id"] for n in hello["graph"]} >= {"radio", "gateway", "policy", "controller", "elastic"}
        ws.send_json({"type": "autonomy", "on": False})
        while (m := ws.receive_json())["type"] != "autonomy":
            pass
        assert m["on"] is False
    import pytest as _pytest
    from starlette.websockets import WebSocketDisconnect
    with _pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/live/ws/nobody") as ws:
            ws.receive_json()


def test_speech_is_queued_one_line_at_a_time():
    from unstep.live.room import SerialTTS

    class OneAtATime(FakeTTS):
        busy = False

        async def speak(self, text, context_id=None, on_chunk=None):
            assert not self.busy, "two lines spoken at once"
            self.busy = True
            await asyncio.sleep(0.05)
            self.busy = False
            return await super().speak(text, context_id, on_chunk)

    async def go():
        tts = SerialTTS(OneAtATime())
        await asyncio.gather(tts.speak("hint"), tts.speak("directive"))
        assert tts.spoken == ["hint", "directive"]

    asyncio.run(go())
