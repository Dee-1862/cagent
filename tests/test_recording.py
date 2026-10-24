"""Recording-session mode: consented push-to-talk clips with key-timing overlaps, prompts, export, eval."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from unstep.clock import now_ms
from unstep.live import recording as rec_mod
from unstep.live.recording import Recorder

from tests.test_live_room import FakeBrowser, make_room, wait_for  # noqa: F401 (fixture)
from tests.test_stream_mic import frames

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_recorder_prompts_qc_and_manifest(tmp_path):
    r = Recorder("test session!", root=tmp_path)
    assert r.session == "test-session" and r.dir.is_dir()
    first = r.prompt("N123AB", "Cessna 1-2-3")
    r.advance("N123AB")
    assert r.prompt("N123AB", "Cessna 1-2-3")["index"] == 1 and first["line"]
    assert "Cessna one two three" in first["line"] or "Cessna" in first["line"]
    assert [r.talk_over_target(["H456"]) for _ in range(6)] == [None, None, "H456", None, None, "H456"]
    assert r.save_clip(station="N123AB", speaker="Dee", pcm=np.zeros(1000), start_ms=0, end_ms=60,
                       script_line="x", transcript=None, overlaps=[]) is None  # under 0.3 s
    loud = np.ones(16000, np.float32)  # clipped
    row = r.save_clip(station="N123AB", speaker="Dee", pcm=loud, start_ms=1000, end_ms=2000, script_line="Hold short",
                      transcript="hold short", overlaps=[{"with": "atc", "start_ms": 1200, "end_ms": 1500}])
    assert row["stepped_on"] and row["qc"]["clipping"] and (r.dir / row["clip"]).is_file()
    r.save_mix(pcm=np.zeros(16000), stations=["atc", "N123AB"], start_ms=1000, end_ms=2000,
               overlaps=[{"stations": ["atc", "N123AB"], "start_ms": 1200, "end_ms": 1500}])
    rows = [json.loads(line) for line in r.manifest.read_text().splitlines()]
    assert [x["kind"] for x in rows] == ["clip", "mix"] and rows[0]["speaker_name"] == "Dee"
    assert r.status()["clips"] == 1 and r.status()["dropped"] == 1 and r.status()["flagged"] == 1


def test_room_records_consented_speakers_with_overlaps_and_cues(make_room, monkeypatch, tmp_path):
    monkeypatch.setattr(rec_mod, "RECORDINGS", tmp_path)
    monkeypatch.setattr(rec_mod, "TALK_OVER_EVERY", 1)

    async def go():
        room, atc, pilot = await make_room()
        heli = FakeBrowser()
        await room.join("H456", heli)
        await room.handle("atc", {"type": "recording", "on": True, "session": "s1", "name": "Rishit", "consent": False})
        assert room.recorder is None  # no consent, no recording
        await room.handle("atc", {"type": "recording", "on": True, "session": "s1", "name": "Rishit", "consent": True})
        await room.handle("N123AB", {"type": "speaker", "name": "Deekshith", "consent": True})
        await room.handle("H456", {"type": "speaker", "name": "Friend", "consent": False})
        await asyncio.sleep(0.05)
        prompt = next(m for m in pilot.messages if m["type"] == "prompt" and m["station"] == "N123AB")
        assert not any(m["type"] == "prompt" for m in heli.messages)  # not recorded, no prompts
        start = now_ms()
        room._key("atc", True)  # the tower keys: the consenting, connected plane is cued to talk over it
        await asyncio.sleep(0.05)
        assert any(m["type"] == "prompt" and m.get("cue") == "talk_now" for m in pilot.messages)
        for f in frames(1.0, start):
            await room.handle("N123AB", f)
        room._key("atc", False)
        await room.handle("N123AB", {"type": "mic_end"})
        for f in frames(0.6, now_ms()):
            await room.handle("H456", f)
        await room.handle("H456", {"type": "mic_end"})
        manifest = tmp_path / "s1" / "manifest.jsonl"
        await wait_for(lambda: manifest.is_file() and manifest.read_text().strip())
        await asyncio.sleep(0.2)
        rows = [json.loads(x) for x in manifest.read_text().splitlines() if '"clip"' in x]
        clips = [x for x in rows if x["kind"] == "clip"]
        assert [c["speaker_name"] for c in clips] == ["Deekshith"]  # the friend didn't consent
        c = clips[0]
        assert c["script_line"] == prompt["line"] and c["stepped_on"] and c["overlaps"][0]["with"] == "atc"
        assert any(m["type"] == "recording" and m["clips"] == 1 for m in atc.messages)
        await room.handle("atc", {"type": "recording", "on": False})
        assert room.recorder is None
        await room.stop()

    asyncio.run(go())


def test_export_splits_by_speaker_credits_people_and_eval_reads_it(tmp_path):
    exp, ev = load("export_recordings"), load("eval_unstep")
    r = Recorder("s2", root=tmp_path / "rec")
    t = np.arange(16000) / 16000
    voice = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    for k, (who, line, heard) in enumerate([
        ("Ana", "Cessna one two three, hold short runway three three.", "Cessna 123, hold short runway 33."),
        ("Ana", "Hold short runway three three, Cessna one two three.", "Hold short runway 33, Cessna 123."),
        ("Ben", "Hold short runway two three, Piper seven eight niner.", "Hold short runway 23, Piper 789."),
    ]):
        r.save_clip(station="N123AB", speaker=who, pcm=voice, start_ms=k * 2000, end_ms=k * 2000 + 1000,
                    script_line=line, transcript=heard, overlaps=[],
                    readback_directive="Piper 7-8-9, hold short Runway 33" if who == "Ben" else None)
    out = tmp_path / "ds"
    result = exp.export([r.dir], out, licence="test licence")
    assert result["counts"]["train"] + result["counts"]["test"] == 3 and result["counts"]["test"] >= 1
    card = (out / "DATASET_CARD.md").read_text()
    assert "Recorded by: Ana, Ben." in card and "test licence" in card
    assert "Claude" not in card and "AI" not in card
    meta = [json.loads(x) for x in (out / "train" / "metadata.jsonl").read_text().splitlines()] + \
           [json.loads(x) for x in (out / "test" / "metadata.jsonl").read_text().splitlines()]
    assert all((out / ("train" if (out / "train" / m["file_name"]).exists() else "test") / m["file_name"]).exists() for m in meta)
    clips, mixes = ev.load_recordings(out)
    scored = ev.score_recordings(clips, mixes, {})
    assert scored["n_clips"] == 3 and scored["wer"]["value"] == 0.0 and scored["callsign"]["value"] == 1.0
    assert scored["readback"]["confusion"]["tp"] == 1  # Ben read back 23 instead of 33, and it was caught
