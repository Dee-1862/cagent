"""P7c: the Cartesia repro script's logic, run against fakes (the real run needs network and a key)."""

import asyncio
import importlib.util

from unstep.cockpit.stt import Transcript, TurnEvent
from unstep.config import ROOT

spec = importlib.util.spec_from_file_location("cartesia_repro", ROOT / "scripts" / "cartesia_repro.py")
repro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repro)

GOOD = "Hold short runway three three, Cessna one two three."


class FakeManual:
    """Empty when sent faster than real time; slow finalize every third connection."""

    opened = 0

    def __init__(self, model=None, keyterms=(), timestamp_granularities=()):
        self.model, self.bytes, self.started = model, 0, None
        FakeManual.opened += 1
        self.slow = FakeManual.opened % 3 == 0

    async def __aenter__(self):
        self.started = asyncio.get_running_loop().time()
        return self

    async def __aexit__(self, *exc):
        pass

    async def send_audio(self, pcm):
        self.bytes += len(pcm)

    async def finalize(self):
        if self.slow:
            await asyncio.sleep(0.3)
        elapsed = asyncio.get_running_loop().time() - self.started
        fast = elapsed < self.bytes / 32000 * 0.5
        words = [1, 2] if self.model == "ink-whisper" else []
        return Transcript("" if fast and self.model != "ink-whisper" else GOOD, words)


class FakeTurns(FakeManual):
    def __init__(self, keyterms=()):
        super().__init__(keyterms=keyterms)

    async def events(self):
        await asyncio.sleep(0.05)
        yield TurnEvent("turn.end", GOOD if self.bytes else "")


def test_repro_experiments_run_and_summarize(monkeypatch):
    monkeypatch.setattr(repro, "CartesiaManualSTT", FakeManual)
    monkeypatch.setattr(repro, "CartesiaTurnSTT", FakeTurns)

    async def instant(stt, pcm, **kw):  # pacing without the wait, so the fake sees "real time"
        await stt.send_audio(pcm)
        stt.started -= len(pcm) / 32000

    monkeypatch.setattr(repro, "send_paced", instant)
    pcm = b"\x00\x00" * 16000  # 1 s

    async def go():
        pacing = await repro.manual_pacing(pcm, 3)
        assert pacing["fast"]["empty"] == 3 and pacing["paced"]["correct"] == 3
        words = await repro.words_by_model(pcm, 1)
        assert words["ink-2"]["words"] == 0 and words["ink-whisper"]["words"] == 2
        hedge = await repro.hedged(pcm, 3, hedge_after_ms=100)
        assert hedge["runs"] == 3 and hedge["finalize_ms"]["n"] == 3
        assert (await repro.handshake(pcm, 2))["failures"] == 0

    asyncio.run(go())


def test_summary_and_check():
    assert repro.summary([5, 1, 3])["p50"] == 3
    assert repro.correct(GOOD) and not repro.correct("hold short runway two three")
