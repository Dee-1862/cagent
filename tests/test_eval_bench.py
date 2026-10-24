"""Benchmark harness: statistics, radio channel, the fake-speech run, Elastic storage, ATCO2 loading."""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import httpx
import numpy as np
import pytest

from unstep import evaluation as ev
from unstep.cockpit.audio import SAMPLE_RATE

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("eval_bench", ROOT / "scripts" / "eval_bench.py")
bench = importlib.util.module_from_spec(spec)
sys.modules["eval_bench"] = bench
spec.loader.exec_module(bench)


def test_wilson_and_proportions():
    assert ev.wilson(0, 10) == (0.0, 0.2775)
    lo, hi = ev.wilson(15, 40)
    assert lo < 15 / 40 < hi
    assert ev.proportion(0, 0) == {"k": 0, "n": 0, "value": None, "ci95": [None, None]}


def test_wer_counts_spoken_and_written_digits_alike():
    assert ev.wer("Cessna one two three hold short runway three three", "cessna 123 hold short runway 33") == (0, 9)
    assert ev.wer("hold short runway three three", "hold runway two three") == (2, 5)
    b = ev.bootstrap_wer([(1, 10), (0, 10), (2, 10)])
    assert b["value"] == 0.1 and b["ci95"][0] <= 0.1 <= b["ci95"][1]


def tone(seconds=2.0, hz=200):
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (0.3 * np.sin(2 * np.pi * hz * t) * (np.sin(2 * np.pi * 3 * t) > 0)).astype(np.float32)


def test_radio_channel_and_stepped_on_mix():
    a = tone()
    radio = ev.through_radio(a, 10.0, seed=1)
    assert len(radio) > len(a) and np.max(np.abs(radio)) <= 1.0
    pcm, window = ev.stepped_on(a, a, 0.8, t0=1_000_000)
    assert window == (1_000_800, 1_002_000)
    assert ev.iou(window, (1_000_800, 1_002_020)) > 0.9
    assert ev.detect_overlap(pcm, t0=1_000_000)  # the beat tone in the overlap is found


def test_fake_run_has_every_section_with_intervals():
    result = asyncio.run(bench.run_bench(bench.FakeSpeech(), 12, ["clean", "radio-10"], stepped=4, seed=3, ab=True))
    assert result["mode"] == "fake" and result["n"] == 12
    c = result["conditions"]["radio-10"]
    assert set(c) >= {"callsign", "runway", "action", "wer", "finalize_ms", "by_voice"}
    assert c["callsign"]["ci95"][0] is not None
    assert {"with", "without"} == set(result["keyterms_ab"])
    assert result["readbacks"]["n"] == 12 and "precision" in result["readbacks"]
    assert result["detection_audio_only"]["n"] >= 1
    s = bench.summary(result)
    assert "rows" not in s


def test_store_skips_fake_runs_and_posts_live_summaries(monkeypatch):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(201, json={"_id": "abc"})

    monkeypatch.setattr("unstep.config.elastic_settings", lambda: ("https://es.example", "k"))
    assert bench.store({"mode": "fake"}, transport=httpx.MockTransport(handler)) is None
    assert bench.store({"mode": "live", "n": 1}, transport=httpx.MockTransport(handler)) == "abc"
    assert seen == [("POST", "/unstep-eval/_doc")]


def test_atco2_loader_needs_the_licence_flag_and_finds_fields(monkeypatch):
    class DS(list):
        column_names = ["audio", "text", "id"]
        info = types.SimpleNamespace(license="test-licence")

    rows = DS([{"audio": {"array": tone(1.0), "sampling_rate": 16000}, "text": "Cessna 123 hold short runway 33", "id": 1}])
    fake = types.ModuleType("datasets")
    fake.load_dataset = lambda name, split: rows
    monkeypatch.setitem(sys.modules, "datasets", fake)
    with pytest.raises(SystemExit):
        list(bench.load_atco2("test", 5, licence_ok=False))
    got = list(bench.load_atco2("test", 5, licence_ok=True))
    assert got[0][0].startswith("Cessna") and len(got[0][1]) == 16000
    result = asyncio.run(bench.run_atco2(bench.FakeSpeech(), "test", 5, True))
    assert result["n"] == 1 and result["callsign"]["n"] == 1
