"""The evaluation script (R19): synthetic set, scoring, fake live run, session summary."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

from unstep.cockpit.stt import FakeManualSTT
from unstep.cockpit.tts import FakeTTS

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("eval_unstep", ROOT / "scripts" / "eval_unstep.py")
ev = importlib.util.module_from_spec(spec)
sys.modules["eval_unstep"] = ev  # dataclasses need the module registered
spec.loader.exec_module(ev)


def test_synthetic_set_is_deterministic_and_labelled():
    a, b = ev.build_items(100, seed=3), ev.build_items(100, seed=3)
    assert a == b and len(a) == 100
    wrong = [i for i in a if i.readback_wrong]
    assert 15 <= len(wrong) <= 45 and all(i.error in ev.ERRORS for i in wrong)
    assert all(i.error is None for i in a if not i.readback_wrong)
    runway = next(i for i in a if i.error == "runway_digit")
    assert runway.readback != runway.instruction


def test_text_only_is_a_perfect_baseline_and_mishearing_costs_accuracy():
    items = ev.build_items(60, seed=1)
    perfect = ev.score(items, [i.instruction for i in items], [i.readback for i in items])
    assert perfect["callsign_accuracy"] == 1.0 and perfect["readback_error_recall"] == 1.0
    garbled = ev.score(items, ["static" for _ in items], [i.instruction for i in items])
    assert garbled["callsign_accuracy"] == 0 and garbled["readback_error_recall"] == 0.0


def test_live_path_with_fake_speech():
    items = ev.build_items(3, seed=2)
    heard = [t for i in items for t in (i.instruction, i.readback)]
    queue = list(heard)
    hi, hr, ms = asyncio.run(ev.transcribe_live(items, tts_factory=FakeTTS,
                                                stt_factory=lambda: FakeManualSTT([queue.pop(0)])))
    assert hi == [i.instruction for i in items] and hr == [i.readback for i in items] and len(ms) == 6


def test_sessions_summary(tmp_path):
    log = tmp_path / "events.jsonl"
    rows = [{"type": "AnomalyEvent", "data": {}},
            {"type": "ReadbackResult", "data": {"match": False}},
            {"type": "ReadbackResult", "data": {"match": True}},
            {"type": "AuditRecord", "data": {"stage": "cockpit_stt", "latency_ms": 100}},
            {"type": "AuditRecord", "data": {"stage": "cockpit_stt", "latency_ms": 300}}]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    s = ev.sessions_summary(log)
    assert s["blocked_calls"] == 1 and s["readbacks"] == {"match": 1, "wrong": 1}
    assert s["latency_ms"]["cockpit_stt"]["n"] == 2 and s["latency_ms"]["cockpit_stt"]["p95"] == 300


def test_dry_run_writes_nothing(tmp_path, capsys):
    assert ev.main(["--dry-run", "--n", "10", "--out", str(tmp_path)]) == 0
    assert "text_only" in capsys.readouterr().out and not list(tmp_path.iterdir())
