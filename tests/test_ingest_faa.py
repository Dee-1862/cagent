"""W2: splitting FAA JO 7110.65 pages into paragraphs. The text below is a made-up fixture, not the Order."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ingest_faa", ROOT / "scripts" / "ingest_faa.py")
faa = importlib.util.module_from_spec(spec)
sys.modules["ingest_faa"] = faa
spec.loader.exec_module(faa)

FIXTURE = """<html><body><h3>Section 7. Fixture</h3>
<p>3-7-1. FIXTURE GROUND RULES</p><p>Fixture text one &amp; more.</p>
<p>3-7-2. FIXTURE TAXI OPERATIONS</p><p>Fixture: state the hold short point.</p><p>EXAMPLE- "Fixture."</p>
<p>2-4-3. FIXTURE READ BACK</p><p>Fixture readback text.</p></body></html>"""


def test_splits_numbered_paragraphs(tmp_path):
    (tmp_path / "ch3.html").write_text(FIXTURE)
    (tmp_path / "dup.txt").write_text("3-7-2. SECOND COPY\nignored because the first copy wins\n")
    docs = {d["paragraph"]: d for d in faa.load(tmp_path)}
    assert set(docs) == {"3-7-1", "3-7-2", "2-4-3"}
    assert docs["3-7-2"]["title"] == "Fixture Taxi Operations"
    assert "hold short point" in docs["3-7-2"]["text"] and "EXAMPLE" in docs["3-7-2"]["text"]
    assert docs["3-7-1"]["text"] == "Fixture text one & more."
    assert docs["2-4-3"]["chapter"] == "2" and docs["3-7-2"]["source"] == "ch3.html"


def test_mapping_uses_semantic_text_and_optional_inference_id():
    m = faa.mapping(None)["mappings"]["properties"]
    assert m["text"] == {"type": "semantic_text"} and m["body"]["type"] == "text"
    assert faa.mapping("my-elser")["mappings"]["properties"]["text"]["inference_id"] == "my-elser"


def test_dry_run(tmp_path, capsys):
    (tmp_path / "ch3.html").write_text(FIXTURE)
    assert faa.main(["--source", str(tmp_path), "--dry-run"]) == 0
    assert "3 paragraphs" in capsys.readouterr().out
