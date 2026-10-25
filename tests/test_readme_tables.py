"""The README's three sponsor tables: the slide format, every cell filled, and every number read from docs/evidence/."""

import json
import re

from scripts import readme_tables as rt

HEADER = "| Feature | What it does in Unstep | Measured |"


def section(text: str, start: str, end: str) -> str:
    return text[text.index(start): text.index(end)]


def rows(block: str) -> list[list[str]]:
    lines = [l for l in block.splitlines() if l.startswith("|")]
    assert lines[0] == HEADER, "the three columns of the demo film: Feature, What it does in Unstep, Measured"
    return [[c.strip() for c in re.split(r"(?<!\\)\|", l.strip().strip("|"))] for l in lines[2:]]


def test_each_sponsor_table_has_six_filled_rows_in_the_slide_format():
    readme = rt.README.read_text(encoding="utf-8")
    blocks = {"Cartesia": section(readme, "## 5. Cartesia", "## 6. Moss"), "Moss": section(readme, "## 6. Moss", "## 7. Elastic"),
              "Elastic": section(readme, "## 7. Elastic", "## 8. The two screens")}
    for name, block in blocks.items():
        table = rows(block)
        assert len(table) == 6, f"{name} has {len(table)} rows"
        for feature, does, measured in table:
            assert feature and does and measured, f"{name}: an empty cell"
            assert "not re-measured" not in measured and "?" not in measured, f"{name}: {feature} has no measured value"


def test_the_evidence_files_the_tables_read_exist_and_hold_sample_counts():
    for pattern in ("cartesia-*.json", "moss-*.json", "elastic-*.json", "moss-live-check-*.txt", "elastic-percolator-*.txt"):
        assert rt.latest(pattern) is not None, f"docs/evidence/{pattern} is missing"
    moss = rt.load("moss-*.json")
    assert moss["sessions"] == 6 and moss["fetch_last_tower_call_filter_and_sort"]["moss_reported_ms"]["n"] >= 100
    elastic = rt.load("elastic-*.json")
    assert elastic["objects"]["agents"]["ours"] == 8 and elastic["objects"]["workflows"]["ours"] == 7
    bench = json.loads(rt.latest("cartesia-bench-*.json").read_text(encoding="utf-8"))
    assert bench["mode"] == "live" and bench["n"] == 200  # never a fake run


def test_no_em_dashes_and_no_leftover_old_measured_table():
    readme = rt.README.read_text(encoding="utf-8")
    assert "—" not in readme
    assert "## 9. Evidence and how to re-run it" in readme and "## 9. Measured results" not in readme
