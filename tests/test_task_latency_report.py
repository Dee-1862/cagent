"""The agents-versus-humans table must say where each number comes from and never invent a human figure."""

import json
from pathlib import Path

import scripts.task_latency_report as rep  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_every_human_baseline_has_a_kind_and_a_source_and_no_invented_figure():
    items = json.loads((ROOT / "assets" / "human_baselines.json").read_text())["items"]
    assert {i["kind"] for i in items} <= {"SOURCED", "MODELLED", "NOT_MEASURED"}
    for i in items:
        assert i["source"] and i["task"]
        if i["kind"] == "NOT_MEASURED":
            assert i.get("seconds") is None and i.get("seconds_per_word") is None  # no number where none was found
        else:
            assert i.get("seconds") or i.get("seconds_per_word")


def test_the_table_lists_six_jobs_and_does_not_claim_a_win_where_the_human_side_is_unmeasured():
    human = rep.human_baselines()
    rows = rep.table({"rule_lookup_ms": 0.02, "readback_check_ms": 0.007}, None, human)
    assert len(rows) == 6
    lookup = next(r for r in rows if r[0].startswith("Find the governing"))
    assert "no comparison" in lookup[3]
    speech = next(r for r in rows if r[0].startswith("Speak"))
    assert "faster" not in speech[3].lower()  # speaking a clearance is not a win
    explain = next(r for r in rows if r[0].startswith("Explain"))
    assert "slower" in explain[3].lower()


def test_the_offline_measurements_run_without_any_service():
    m = rep.measure_offline()
    assert 0 < m["rule_lookup_ms"] < 5 and 0 <= m["readback_check_ms"] < 5


def test_a_sourced_baseline_says_what_was_read_and_a_modelled_one_admits_it_has_no_citation():
    items = {i["id"]: i for i in json.loads((ROOT / "assets" / "human_baselines.json").read_text())["items"]}
    assert items["pilot_readback_latency"]["verified"].startswith("full text read")
    assert "NTRS 20220007116" in items["pilot_readback_latency"]["source"] and items["pilot_readback_latency"]["seconds"] == 0.639
    assert items["say_again_cycle"]["source"].startswith("none") and items["spoken_clearance"]["source"].startswith("none")
    assert items["hearback_catch"]["verified"] == "not verified" and items["hearback_catch"].get("seconds") is None
