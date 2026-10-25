"""M-1 script: its own flow runs offline (a dry run proves the script, not Moss)."""

import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("moss_live_check", ROOT / "scripts" / "moss_live_check.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["moss_live_check"] = mod
spec.loader.exec_module(mod)


def test_dry_run_passes_and_pushes_only_the_test_flight_log():
    lines = []
    assert asyncio.run(mod.main_async(True, False, out=lines.append)) == 0
    text = "\n".join(lines)
    assert "DRY RUN" in text and "pushed once" in text and "2 docs back" in text
    assert "BELOW FLOOR" in text or "clears" in text and "whole exchange" in text
    assert "flightlog-check-" in text and "flight-N123AB" not in text.split("pushed once")[1]


def test_without_keys_it_skips_cleanly(monkeypatch):
    monkeypatch.delenv("MOSS_PROJECT_ID", raising=False)
    monkeypatch.delenv("MOSS_PROJECT_KEY", raising=False)
    lines = []
    assert asyncio.run(mod.main_async(False, False, out=lines.append)) == 0
    assert lines[0].startswith("skipped")
