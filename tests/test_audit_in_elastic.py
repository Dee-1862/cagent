"""E-3: the audit trail and the benchmark in Elastic, with simulated runs labelled. Mocks only; the live
cluster has not seen any of this."""

import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import httpx

from unstep.evaluation import EVAL_INDEX, EVAL_MAPPINGS, eval_document, store_eval
from unstep.gateway.sink import MAPPINGS, to_document
from unstep.ground import stats
from unstep.live.app import create_live_app

from tests.test_live_join import room as make_join_room

ROOT = Path(__file__).resolve().parent.parent

BENCH = {"mode": "live", "run_id": "eval-1", "n": 200, "seed": 7,
         "conditions": {"radio-10": {"callsign": {"value": 0.95, "ci95": [0.9, 0.97], "n": 200},
                                     "runway": {"value": 0.9}, "wer": {"value": 0.08}}},
         "readbacks": {"recall": {"value": 1.0}, "false_alarm_rate": {"value": 0.04}},
         "detection_audio_only": {"recall_iou_0_5": {"value": 0.92}}}
SIM = {"simulated": True, "run_id": "sim-1", "calls": 500, "params": {"seed": 7},
       "detected_stepped_on": {"value": 0.917}, "false_events_on_clean_calls": {"value": 0.0},
       "readback_error_recall": {"value": 1.0}}


def test_eval_documents_fit_the_mapping_and_label_simulated_runs():
    bench, sim = eval_document(BENCH), eval_document(SIM)
    assert bench["kind"] == "benchmark" and bench["simulated"] is False and bench["headline"]["callsign_radio_10"] == 0.95
    assert bench["headline"]["readback_recall"] == 1.0 and bench["headline"]["overlap_detector_recall"] == 0.92
    assert sim["kind"] == "simulation" and sim["simulated"] is True and sim["n"] == 500 and sim["seed"] == 7
    assert sim["headline"]["detected_stepped_on"] == 0.917
    for doc in (bench, sim):  # strict mapping: no field outside the mapping
        assert set(doc) <= set(EVAL_MAPPINGS["properties"])


def test_store_posts_live_runs_only():
    seen = []
    t = httpx.MockTransport(lambda r: (seen.append((r.method, r.url.path, json.loads(r.content))) or httpx.Response(201, json={"_id": "x"})))
    import unstep.config as config

    orig = config.elastic_settings
    config.elastic_settings = lambda: ("https://es.example", "k")
    try:
        assert store_eval({"mode": "fake"}, transport=t) is None
        assert store_eval(BENCH, transport=t) == "x"
        assert store_eval({**SIM, "mode": "simulated"}, transport=t) == "x"
    finally:
        config.elastic_settings = orig
    assert [p for _, p, _ in seen] == [f"/{EVAL_INDEX}/_doc"] * 2
    assert seen[1][2]["simulated"] is True and seen[0][2]["simulated"] is False


def test_deploy_creates_the_audit_indexes_and_soft_data_views():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "deploy_elastic.py"), "--dry-run"],
                         capture_output=True, text=True, check=True).stdout
    for name in ("es/unstep-events", "es/unstep-sim-events", "es/unstep-eval", "data view unstep-eval"):
        assert name in out
    assert "simulated" in MAPPINGS["properties"] and "run_id" in MAPPINGS["properties"]
    spec = importlib.util.spec_from_file_location("deploy_elastic", ROOT / "scripts" / "deploy_elastic.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["deploy_elastic"] = mod
    spec.loader.exec_module(mod)
    labels = [s[0] for s in mod.plan(False)]
    assert len(labels) == len(set(labels))  # the events index is not listed twice


def test_simulated_records_keep_their_label_in_the_document():
    doc = to_document({"type": "AnomalyEvent", "ts": 1, "source": "cockpit", "data": {}, "simulated": True, "run_id": "sim-1"})
    assert doc["simulated"] is True and doc["run_id"] == "sim-1"


def test_real_stats_exclude_simulated_runs_and_the_hub_can_default_them_on(monkeypatch):
    queries = []

    def handler(request):
        q = json.loads(request.content)["query"]
        queries.append(q)
        if "BY run_id" in q:
            return httpx.Response(200, json={"columns": [{"name": "n"}, {"name": "run_id"}], "values": [[5, "sim-1"]]})
        return httpx.Response(200, json={"columns": [], "values": []})

    t = httpx.MockTransport(handler)
    real = asyncio.run(stats.frequency_stats("118.7", 0, {}, settings=("https://es", "k"), transport=t))
    assert real["simulated_runs"] == [] and all("unstep-sim-events" not in q for q in queries)  # real stats exclude them

    monkeypatch.setattr(stats, "elastic_settings", lambda: ("https://es", "k"))
    monkeypatch.setenv("UNSTEP_STATS_INCLUDE_SIMULATED", "1")
    seen = {}

    async def fake(frequency, since, traces, **kw):
        seen.update(kw)
        return {"simulated_runs": ["sim-1"]}

    monkeypatch.setattr("unstep.ground.stats.frequency_stats", fake)
    from fastapi.testclient import TestClient

    with TestClient(create_live_app(live=False, room=make_join_room(monkeypatch))) as client:
        client.get("/live/stats?since_ms=0")
    assert seen["include_simulated"] is True
