"""The caption probe's summary maths, and the probe against fake Cartesia streams (no network)."""

import asyncio
import importlib.util

from unstep.cockpit.stt import TurnEvent
from unstep.config import ROOT

spec = importlib.util.spec_from_file_location("caption_probe", ROOT / "scripts" / "caption_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_summary_counts_updates_gaps_and_words():
    s = probe.summarize([(0.6, 2), (1.2, 4), (1.8, 5), (4.5, 8)], audio_end_s=4.0)
    assert s["updates"] == 4 and s["updates_while_speaking"] == 3
    assert s["first_text_ms"] == 600 and s["gap_median_ms"] == 600 and s["gap_worst_ms"] == 2700
    assert s["words_per_update_median"] == 2 and s["last_update_after_end_ms"] == 500


def test_no_updates_is_a_clear_finding():
    assert probe.summarize([], 4.0) == {"updates": 0}


def test_turns_probe_collects_updates_across_turns(monkeypatch):
    class FakeTurns:
        def __init__(self, keyterms=()):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        async def send_audio(self, pcm):
            pass

        async def events(self):
            await asyncio.sleep(0.01)
            yield TurnEvent("turn.start")
            yield TurnEvent("turn.update", "Tower")
            yield TurnEvent("turn.update", "Tower hold short")
            yield TurnEvent("turn.end", "Tower hold short runway")

    async def instant(stt, pcm, **kw):
        return 0.0

    monkeypatch.setattr(probe, "CartesiaTurnSTT", FakeTurns)
    monkeypatch.setattr(probe, "send_paced", instant)
    updates = asyncio.run(probe.probe_turns(b"\x00\x00" * 1600))
    assert [w for _, w in updates] == [1, 3, 4]
