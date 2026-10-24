"""Export recorded sessions as a datasets-style folder with a dataset card.

    python scripts/export_recordings.py data/recordings/<session> [more sessions] --out data/dataset/unstep-radio
    python scripts/export_recordings.py --all --licence "CC BY 4.0"

Writes train/ and test/ (split by speaker, so no voice is in both), each with audio/ and a
metadata.jsonl whose `file_name` points at the clip (the Hugging Face "audiofolder" layout), plus
mixes/ with the stepped-on mixes and their key-timing overlap windows, and DATASET_CARD.md that
credits the people who recorded it by name. The licence is the humans' decision; the default is
"for evaluation only, not for redistribution".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep.live.recording import RECORDINGS  # noqa: E402

DEFAULT_LICENCE = "For evaluation only, not for redistribution (to be confirmed by the recorders)"


def read_sessions(dirs: list[Path]) -> tuple[list[dict], list[dict]]:
    clips, mixes = [], []
    for d in dirs:
        manifest = d / "manifest.jsonl"
        if not manifest.is_file():
            continue
        for line in manifest.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            row["_dir"] = str(d)
            (mixes if row.get("kind") == "mix" else clips).append(row)
    return clips, mixes


def split_speakers(speakers: list[str], test_share: float) -> set[str]:
    """Test speakers, chosen by a stable hash; at least one when there are two or more speakers."""
    ordered = sorted(set(speakers), key=lambda s: hashlib.sha1(s.encode()).hexdigest())
    if len(ordered) < 2:
        return set()
    k = max(1, round(len(ordered) * test_share))
    return set(ordered[:k])


def export(dirs: list[Path], out: Path, licence: str, test_share: float = 0.2, name: str = "Unstep radio recordings") -> dict:
    clips, mixes = read_sessions(dirs)
    test = split_speakers([c["speaker_name"] for c in clips], test_share)
    out.mkdir(parents=True, exist_ok=True)
    counts = {"train": 0, "test": 0}
    for split in ("train", "test"):
        (out / split / "audio").mkdir(parents=True, exist_ok=True)
        (out / split / "metadata.jsonl").write_text("", encoding="utf-8")
    for c in clips:
        split = "test" if c["speaker_name"] in test else "train"
        shutil.copy2(Path(c["_dir"]) / c["clip"], out / split / "audio" / c["clip"])
        row = {k: v for k, v in c.items() if not k.startswith("_") and k != "kind"}
        row = {"file_name": f"audio/{c['clip']}", "text": c.get("script_line"), **row}
        with (out / split / "metadata.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        counts[split] += 1
    (out / "mixes").mkdir(exist_ok=True)
    with (out / "mixes" / "metadata.jsonl").open("w", encoding="utf-8") as f:
        for m in mixes:
            shutil.copy2(Path(m["_dir"]) / m["clip"], out / "mixes" / m["clip"])
            f.write(json.dumps({"file_name": m["clip"], **{k: v for k, v in m.items() if not k.startswith("_")}}) + "\n")
    stats = card_stats(clips, mixes)
    (out / "DATASET_CARD.md").write_text(card(name, licence, stats, counts, test), encoding="utf-8")
    return {"counts": counts, **stats}


def card_stats(clips: list[dict], mixes: list[dict]) -> dict:
    by_speaker: dict[str, dict] = {}
    for c in clips:
        s = by_speaker.setdefault(c["speaker_name"], {"clips": 0, "seconds": 0.0})
        s["clips"] += 1
        s["seconds"] += c.get("duration_s") or 0.0
    overlap_ms = [o["end_ms"] - o["start_ms"] for m in mixes for o in m.get("overlaps", [])]
    return {"clips": len(clips), "seconds": round(sum(c.get("duration_s") or 0 for c in clips), 1),
            "stepped_on_clips": sum(bool(c.get("stepped_on")) for c in clips), "mixes": len(mixes),
            "overlap_windows": len(overlap_ms), "overlap_ms_median": sorted(overlap_ms)[len(overlap_ms) // 2] if overlap_ms else None,
            "flagged": sum(bool((c.get("qc") or {}).get("clipping") or (c.get("qc") or {}).get("silence")) for c in clips),
            "sessions": sorted({c.get("session") for c in clips if c.get("session")}),
            "by_speaker": {k: {"clips": v["clips"], "seconds": round(v["seconds"], 1)} for k, v in sorted(by_speaker.items())}}


def card(name: str, licence: str, s: dict, counts: dict, test: set[str]) -> str:
    people = ", ".join(s["by_speaker"]) or "nobody yet"
    rows = "\n".join(f"| {k} | {v['clips']} | {v['seconds']} | {'test' if k in test else 'train'} |" for k, v in s["by_speaker"].items())
    return f"""# {name}

Recorded by: {people}.

Real people talking on a shared practice radio frequency in the Unstep live room, reading lines from a
prompter (tower instructions, pilot requests and readbacks, some readbacks wrong on purpose) and
sometimes talking over each other on cue. Everyone recorded ticked "My voice is recorded for the
Unstep dataset" before joining.

## Licence

{licence}

## Contents

| | Value |
| --- | --- |
| Clips (one person's own microphone, 16 kHz mono) | {s['clips']} ({counts['train']} train, {counts['test']} test) |
| Total speech | {s['seconds']} s |
| Clips that were stepped on (from key timing) | {s['stepped_on_clips']} |
| Stepped-on mixes (what a cockpit heard) | {s['mixes']}, {s['overlap_windows']} overlap windows, median {s['overlap_ms_median']} ms |
| Clips flagged by QC (clipping or near silence) | {s['flagged']} |
| Sessions | {", ".join(s['sessions']) or "-"} |

| Speaker | Clips | Seconds | Split |
| --- | --- | --- | --- |
{rows}

## Fields

- `file_name`, `text` (the prompted line), `transcript` (Cartesia's live transcript when the room ran live), `speaker_name`, `station`
- `start_ms`, `end_ms`, `duration_s` on the room's clock; `overlaps` [{{with, start_ms, end_ms}}] and `stepped_on` from key presses (ground truth)
- `script_kind` (instruction, readback, wrong_readback, request), `readback_of` and `readback_directive` for readbacks
- `qc` {{rms, clipping, silence}}
- `mixes/metadata.jsonl`: each stepped-on mix with its overlap windows

Train and test are split by speaker, so no voice appears in both.
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("sessions", nargs="*", type=Path)
    p.add_argument("--all", action="store_true", help="every session under data/recordings/")
    p.add_argument("--out", type=Path, default=ROOT / "data" / "dataset" / "unstep-radio")
    p.add_argument("--licence", default=DEFAULT_LICENCE)
    p.add_argument("--test-share", type=float, default=0.2)
    args = p.parse_args(argv)
    dirs = sorted(d for d in RECORDINGS.iterdir() if d.is_dir()) if args.all and RECORDINGS.is_dir() else args.sessions
    if not dirs:
        print("No sessions given (or --all found none).", file=sys.stderr)
        return 1
    result = export(dirs, args.out, args.licence, args.test_share)
    print(json.dumps(result, indent=1))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
