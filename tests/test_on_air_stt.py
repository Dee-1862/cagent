"""R27 3a: speech-to-text runs while the call is on air, so transcripts are final at release.

Cartesia is modelled offline: it works through audio at SPEED times real time from when the audio
reaches it, and finalize answers 100 ms after it has caught up. Sending a whole clip after release
therefore waits about clip/SPEED; streaming during the call doesn't. The live number needs a run
with keys; this checks the mechanism and the order of magnitude.
"""

import asyncio
import time

import numpy as np

from unstep.clock import now_ms
from unstep.cockpit.stt import Transcript
from unstep.contracts import Word
from unstep.ground import tower
from unstep.live import room as room_mod
from unstep.live.radio import LiveMix, Transmission, mix

from tests.test_live_room import TOWER_TEXT, make_room, only_trace, wait_for  # noqa: F401 (fixture)

SPEED = 1.5


class ModelSTT:
    """Cartesia-like timing: processing at SPEED x real time, finalize 100 ms after catching up."""

    def __init__(self, text="", **kw):
        self.text, self.ready = text, 0.0
        self.on_text = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def send_audio(self, pcm):
        self.ready = max(self.ready, time.perf_counter()) + len(pcm) / 2 / 16000 / SPEED

    async def finalize(self, timeout_s=10.0):
        await asyncio.sleep(max(0.0, self.ready - time.perf_counter()) + 0.1)
        return Transcript(self.text, [Word(word=w, start=i * 0.3, end=i * 0.3 + 0.25)
                                      for i, w in enumerate(self.text.split())])


def test_live_mix_matches_the_cluster_mix_outside_the_overlap():
    a = np.full(16000, 0.1, np.float32)
    b = np.full(8000, 0.2, np.float32)
    m = LiveMix(1000)
    m.add("a", "atc", 1000, a)
    m.add("b", "H456", 1500, b[:4000])
    first = m.pull()
    assert len(first) == 12000  # only as far as the open push-to-talk has delivered
    m.add("b", "H456", 1500, b[4000:])
    m.close("a"), m.close("b")
    got = np.concatenate([first, m.pull()])
    ref = mix([Transmission("atc", 1000, a), Transmission("H456", 1500, b)]).pcm
    assert np.allclose(got[:8000], ref[:8000])  # before the overlap: the same audio


def run_call(make_room, monkeypatch, streamed: bool) -> dict:
    async def go():
        room, atc, pilot = await make_room()
        room.live = True  # take the live speech paths, with the model instead of Cartesia
        monkeypatch.setenv("CARTESIA_API_KEY", "model")
        heard = "Cessna one two three, hold short runway three three."
        monkeypatch.setattr(room_mod, "CartesiaManualSTT", lambda **kw: ModelSTT(heard))
        if streamed:
            room.stream_stt_factory = lambda s: tower.TowerStream(stt_factory=lambda **kw: ModelSTT(TOWER_TEXT))
            room.mix_stt_factory = lambda cs: ModelSTT(heard)
        else:
            room.stream_stt_factory = lambda s: None
            monkeypatch.setattr(room, "_mix_enabled", lambda: False)
            room.tower_transcriber = tower.TowerTranscriber(stt_factory=lambda **kw: ModelSTT(TOWER_TEXT), realtime=False)
        await asyncio.gather(room.say("atc", TOWER_TEXT), room.say("H456", "Helicopter four five six, request transition"))
        await wait_for(lambda: only_trace(room) and {"tower_stt_final", "cockpit_stt_final", "proposed"}
                       <= {t["stage"] for t in only_trace(room)["timings"]}, timeout=30)
        timings = {t["stage"]: t for t in only_trace(room)["timings"]}
        await room.stop()
        return timings

    return asyncio.run(go())


def test_streaming_while_on_air_cuts_the_wait_after_release(make_room, monkeypatch):
    before = run_call(make_room, monkeypatch, streamed=False)
    after = run_call(make_room, monkeypatch, streamed=True)
    tb, ta = before["tower_stt_final"]["ms"], after["tower_stt_final"]["ms"]
    cb, ca = before["cockpit_stt_final"]["ms"], after["cockpit_stt_final"]["ms"]
    print(f"\ntower STT final after release: {tb} ms -> {ta} ms; cockpit: {cb} ms -> {ca} ms (offline model)")
    assert ta < 400 < tb  # streamed: final about 100 ms after release; clip: about clip / SPEED later
    assert ca < 400 < cb and "streamed on air" in after["cockpit_stt_final"]["by"]
    pb = before["proposed"]["at_ms"] - before["call_end"]["at_ms"]
    pa = after["proposed"]["at_ms"] - after["call_end"]["at_ms"]
    print(f"call end -> proposal: {pb} ms -> {pa} ms (offline model)")
    assert pa < pb


def test_a_mix_holding_a_newer_call_is_not_trusted(make_room):
    async def go():
        room, atc, pilot = await make_room()
        room.mix_stt_factory = lambda cs: ModelSTT("heard")
        t0 = now_ms()
        old = Transmission("atc", t0, np.zeros(1600, np.float32), text="a")
        room._mix_add(old.tx_id, "atc", t0, old.pcm)
        room._mix_add("H456-999", "H456", t0 + 50, np.zeros(1600, np.float32))  # a later call, not in this cluster
        assert await room._mix_finish([old]) == {} and room.live_mix is None and not room.mix_streams
        room._mix_add(old.tx_id, "atc", t0, old.pcm)
        assert set(await room._mix_finish([old])) == set(room.edges)  # every cockpit got a final text
        await room.stop()

    asyncio.run(go())
