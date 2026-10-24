"""Simulated traffic: real room, synthetic calls, every record labelled; and the benchmark report."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import httpx

from unstep.gateway.sink import to_document
from unstep.ground import stats

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim, report = load("simulate_traffic"), load("benchmark_report")


def test_a_small_run_labels_everything_simulated(tmp_path, monkeypatch):
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    args = type("A", (), {"sessions": 1, "calls": 8, "seed": 3, "p_step": 0.5, "p_wrong": 0.5, "p_permissive": 0.2,
                          "elastic": False, "out": tmp_path})()
    summary = asyncio.run(sim.main_async(args))
    assert summary["simulated"] is True and summary["calls"] == 8
    assert summary["status_quo_automatic_detection"]["value"] in (0.0, None)
    run = tmp_path / summary["run_id"]
    calls = [json.loads(x) for x in (run / "calls.jsonl").read_text().splitlines()]
    envelopes = [json.loads(x) for x in (run / "envelopes.jsonl").read_text().splitlines()]
    assert calls and all(c["simulated"] and c["run_id"] == summary["run_id"] for c in calls)
    assert envelopes and all(e["simulated"] and e["run_id"] == summary["run_id"] for e in envelopes)
    assert any(c["stepped_on"] for c in calls)
    doc = report.build(run / "summary.json", None, None)
    assert f"## Simulated traffic (n=8 calls" in doc and "Not run yet" in doc and "Recorded sessions" in doc
    assert "say again" in doc and "assumption" in doc


def test_elastic_documents_carry_the_simulated_label():
    real = to_document({"type": "AnomalyEvent", "ts": 1, "source": "cockpit", "data": {"callsign": "N1"}})
    fake = to_document({"type": "AnomalyEvent", "ts": 1, "source": "cockpit", "data": {}, "simulated": True, "run_id": "sim-1"})
    assert "simulated" not in real and fake["simulated"] is True and fake["run_id"] == "sim-1"


def test_stats_lists_simulated_runs_only_when_asked():
    seen = []

    def handler(request):
        q = json.loads(request.content)["query"]
        seen.append(q)
        if "BY run_id" in q:
            return httpx.Response(200, json={"columns": [{"name": "n"}, {"name": "run_id"}], "values": [[5, "sim-1"]]})
        return httpx.Response(200, json={"columns": [], "values": []})

    t = httpx.MockTransport(handler)
    real = asyncio.run(stats.frequency_stats("118.7", 0, {}, settings=("https://es", "k"), transport=t))
    assert real["simulated_runs"] == [] and all("unstep-sim-events" not in q for q in seen)
    seen.clear()
    both = asyncio.run(stats.frequency_stats("118.7", 0, {}, settings=("https://es", "k"), transport=t, include_simulated=True))
    assert both["simulated_runs"] == ["sim-1"] and "unstep-sim-events" in seen[0]


def test_report_says_what_is_missing():
    doc = report.build(None, None, None)
    for heading in ("Status quo", "Simulated traffic", "Speech under radio conditions", "Recorded sessions"):
        assert heading in doc
    assert "0%" in doc and "1.16%" in doc and "There's nothing" in doc
    assert report.say_again_ms("Cessna one two three, hold short runway three three.") == 1500 + 6 * 250 + 300 + 9 * 250 + 300
