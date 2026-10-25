"""scripts/cartesia_live_check.py against fakes: no network, no key."""

import asyncio
import importlib.util
import json
import sys

import pytest

import unstep.cockpit.cartesia_errors as ce
from unstep.config import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("cartesia_live_check", ROOT / "scripts" / "cartesia_live_check.py")
live = importlib.util.module_from_spec(spec)
sys.modules["cartesia_live_check"] = live
spec.loader.exec_module(live)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    ce._open.clear()
    ce.RATE_LIMIT_EVENTS.clear()
    yield
    ce._open.clear()
    ce.RATE_LIMIT_EVENTS.clear()


def run_main(tmp_path, *args, backend=None):
    code = live.main(["--out-dir", str(tmp_path), *args], backend=backend)
    reports = sorted(tmp_path.glob("*.json"))
    return code, json.loads(reports[-1].read_text()) if reports else None


def by_name(report):
    return {c["name"]: c for c in report["checks"]}


def test_dry_run_passes_offline_and_writes_a_report(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    code, report = run_main(tmp_path, "--dry-run")
    out = capsys.readouterr().out
    assert code == 0 and report["mode"] == "dry-run"
    assert [c["name"] for c in report["checks"]] == ["caption", "turns", "tts", "dict", "rate", "sockets"]
    assert all(c["status"] in ("PASS", "INFO") for c in report["checks"])
    assert "FAKE BACKEND" in out and "=== SUMMARY" in out and "PASS" in out and "INFO" in out
    assert report["open_sockets_at_end"] == 0
    assert [p.name.endswith("-dry-run.json") for p in tmp_path.glob("*.json")] == [True]
    assert "sk_" not in json.dumps(report)  # no key material in the report


def test_skips_cleanly_without_the_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    monkeypatch.delenv("cartesia_api_key", raising=False)
    assert live.main(["--out-dir", str(tmp_path)]) == 0
    assert "skipped" in capsys.readouterr().out
    assert list(tmp_path.glob("*.json")) == []


def test_socket_cap_is_six_at_most():
    for bad in ("7", "0", "100"):
        with pytest.raises(SystemExit):
            live.parse(["--max-sockets", bad])
    assert live.parse([]).max_sockets == 4
    assert live.parse(["--max-sockets", "6"]).max_sockets == 6


def test_dictionary_check_lists_the_entries_that_fail(tmp_path):
    backend = live.FakeBackend(heard={("fower", True): "tower flower hold short", ("quebec", True): "tower kebab hold short",
                                      ("NOTAM", True): "tower no tam hold short"})
    code, report = run_main(tmp_path, "--dry-run", "--only", "dict", backend=backend)
    check = by_name(report)["dict"]
    assert code == 1 and check["status"] == "FAIL"
    assert check["data"]["failing_with_dictionary"] == ["fower", "quebec", "NOTAM"]
    texts = " ".join(line["text"] for line in check["lines"] if line["level"] == "FAIL")
    assert "'fower'" in texts and "'quebec'" in texts and "'NOTAM'" in texts and "'juliett'" not in texts
    rows = {r["word"]: r for r in check["data"]["rows"]}
    assert rows["fower"]["dict"]["ok"] == 0 and rows["fower"]["baseline"]["ok"] == rows["fower"]["baseline"]["runs"]
    assert set(check["data"]["respelling_breaks_recognition"]) == {"fower", "quebec", "NOTAM"}  # the niner lesson


def test_dictionary_check_notes_a_missing_dict_id_and_runs_the_baseline(tmp_path):
    backend = live.FakeBackend(dict_id=None)
    _, report = run_main(tmp_path, "--dry-run", "--only", "dict", backend=backend)
    check = by_name(report)["dict"]
    assert check["status"] in ("PASS", "INFO") and check["data"]["dict_id_set"] is False
    assert any("CARTESIA_PRONUNCIATION_DICT_ID" in line["text"] for line in check["lines"])
    assert all("dict" not in r for r in check["data"]["rows"])


def test_heard_matching_accepts_plain_words_but_not_near_misses():
    assert live.heard_ok("fower", "Tower, four, hold short.")
    assert live.heard_ok("fower", "tower fower hold short")
    assert not live.heard_ok("fower", "Tower, flower, hold short.")
    assert live.heard_ok("juliett", "Juliet.") and live.heard_ok("NOTAM", "A NOTAM is out")
    assert not live.heard_ok("quebec", "tower kebab")
    assert live.heard_ok("tree", "tower 3 hold short")


def test_every_dictionary_entry_is_in_the_check(tmp_path):
    entries = json.loads(live.DICT_PATH.read_text())
    assert {"fower", "juliett", "quebec", "NOTAM"} <= {e["text"] for e in entries}
    _, report = run_main(tmp_path, "--dry-run", "--only", "dict")
    assert {e["text"] for e in entries} <= {r["word"] for r in by_name(report)["dict"]["data"]["rows"]}
    assert "niner" in {r["word"] for r in by_name(report)["dict"]["data"]["rows"]}  # control


def test_rate_probe_stops_at_the_first_429_and_reports_the_body(tmp_path):
    backend = live.FakeBackend(rate_limit_at=3)
    code, report = run_main(tmp_path, "--dry-run", "--only", "rate", "--max-sockets", "6", backend=backend)
    check = by_name(report)["rate"]
    assert code == 0  # a 429 is the thing we are looking for, not a failure
    assert [s["k"] for s in check["data"]["steps"]] == [1, 2, 3]
    first = check["data"]["first_429"]
    assert first["k"] == 3 and "FAKE body" in first["detail"]["body"] and first["detail"]["open_sockets"] == 3
    assert any("HTTP 429" in line["text"] and "body=" in line["text"] for line in check["lines"])
    assert report["rate_limit_events"] and report["open_sockets_at_end"] == 0


def test_a_failing_check_is_reported_and_the_rest_still_run(tmp_path):
    backend = live.FakeBackend(errors={"caption-turns", "tts"})
    code, report = run_main(tmp_path, "--dry-run", backend=backend)
    checks = by_name(report)
    assert code == 1
    assert checks["caption"]["status"] == "FAIL" and checks["tts"]["status"] == "FAIL"
    assert checks["turns"]["status"] == "PASS" and checks["rate"]["status"] == "INFO"


def test_leaked_socket_fails_the_run(tmp_path):
    class Leaky(live.FakeBackend):
        async def probe_step(self, k):
            ce.socket_opened("tts")  # opened and never closed
            return await super().probe_step(k)

    code, report = run_main(tmp_path, "--dry-run", "--only", "rate", backend=Leaky())
    assert code == 1 and report["open_sockets_at_end"] == 4
    assert by_name(report)["sockets"]["status"] == "FAIL"


# ---------------------------------------------------------------- the live backend, with fake websockets


class FakeTTS:
    """Stands in for CartesiaTTS: counts its socket like the real one and can answer 429."""
    made: list = []
    fail_from = 3  # the third socket in a step gets a 429

    def __init__(self, *a, **kw):
        self.index = len(FakeTTS.made)
        FakeTTS.made.append(self)
        self.connected = False
        self.closed = False
        self.pronunciation_dict_id = "from-env"
        self.sample_rate = kw.get("sample_rate")

    async def connect(self):
        ce.socket_opened("tts")
        self.connected = True

    async def close(self):
        if self.connected and not self.closed:
            ce.socket_closed("tts")
        self.closed = True

    async def speak(self, text, **kw):
        await asyncio.sleep(0)
        if self.index % 4 == FakeTTS.fail_from - 1 and FakeTTS.fail_from:
            raise ce.rate_limited_from_event({"status_code": 429, "title": "Too many", "message": "FAKE live limit"}, "tts")
        return type("S", (), {"first_audio_ms": 90.0, "pcm": b"\x00\x00" * 160})()


def test_live_probe_closes_every_socket_even_when_a_generation_is_rate_limited(monkeypatch):
    FakeTTS.made = []
    monkeypatch.setattr("unstep.cockpit.tts.CartesiaTTS", FakeTTS)
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    backend = live.LiveBackend()
    step = asyncio.run(backend.probe_step(3))
    assert step["connected"] == 3 and step["open_sockets"] == 3
    limited = [g for g in step["generations"] if g["rate_limited"]]
    assert len(limited) == 1 and limited[0]["status"] == 429 and "FAKE live limit" in limited[0]["body"]
    assert limited[0]["open_sockets"] == 3  # the socket count when the 429 arrived
    assert all(t.closed for t in FakeTTS.made) and ce.open_socket_count() == 0


def test_live_roundtrip_switches_the_dictionary_off_for_the_baseline_and_closes(monkeypatch):
    FakeTTS.made = []
    FakeTTS.fail_from = 0
    seen = {}

    class FakeSTT:
        def __init__(self, keyterms=()):
            seen["terms"] = list(keyterms)

        async def __aenter__(self):
            ce.socket_opened("stt")
            return self

        async def __aexit__(self, *exc):
            ce.socket_closed("stt")

        async def finalize(self):
            return type("T", (), {"text": "Tower, four, hold short."})()

    async def send_fast(stt, pcm):
        return None

    monkeypatch.setattr("unstep.cockpit.tts.CartesiaTTS", FakeTTS)
    monkeypatch.setattr("unstep.cockpit.stt.CartesiaManualSTT", FakeSTT)
    monkeypatch.setattr(live.cartesia_repro, "send_fast", send_fast)
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    backend = live.LiveBackend()

    async def go():
        base = await backend.roundtrip("Tower, fower, hold short.", use_dict=False)
        with_dict = await backend.roundtrip("Tower, fower, hold short.", use_dict=True)
        return base, with_dict

    base, with_dict = asyncio.run(go())
    assert base == with_dict == "Tower, four, hold short."
    assert FakeTTS.made[0].pronunciation_dict_id is None and FakeTTS.made[1].pronunciation_dict_id == "from-env"
    assert FakeTTS.made[0].sample_rate == 16000  # STT takes 16 kHz, so no resampling step is needed
    assert "fower" in seen["terms"] and all(t.closed for t in FakeTTS.made) and ce.open_socket_count() == 0
    FakeTTS.fail_from = 3


def test_live_first_audio_uses_one_socket_and_closes_it(monkeypatch):
    FakeTTS.made = []
    FakeTTS.fail_from = 0
    monkeypatch.setattr("unstep.cockpit.tts.CartesiaTTS", FakeTTS)
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    times = asyncio.run(live.LiveBackend().tts_first_audio("hello", 3))
    assert times == [90.0, 90.0, 90.0] and len(FakeTTS.made) == 1 and FakeTTS.made[0].closed
    FakeTTS.fail_from = 3
