"""One command for everything on the Cartesia checklist that needs live access (docs/24-cartesia-findings.md).

    python scripts/cartesia_live_check.py                  # all five checks against the real Cartesia API
    python scripts/cartesia_live_check.py --dry-run        # fakes, offline, proves the script works
    python scripts/cartesia_live_check.py --only dict rate # some of the checks

The checks run in this order and each prints PASS, FAIL or INFO lines (SKIP when it cannot run):

  1 caption  caption_probe.py for both endpoints: manual (/stt/websocket) and turns (/stt/turns/websocket)
  2 turns    cartesia_repro.py turns_pacing: fast versus paced audio on the turns endpoint, empty transcripts
  3 tts      first audio time of Sonic over the WebSocket (first request on a socket, then warm requests)
  4 dict     every entry of assets/pronunciation/atc.json spoken by Sonic, heard by ink-2, with and without the
             dictionary (needs CARTESIA_PRONUNCIATION_DICT_ID for the "with" half)
  5 rate     opens 1..N TTS sockets (N is --max-sockets, default 4, never above 6) and fires one generation on
             each at the same time; stops at the first HTTP 429 and prints its status and body

Every socket is closed after use, and the script fails if it still holds one at the end. The 429 body is logged
with secrets removed and no headers (unstep/cockpit/cartesia_errors.py).

It writes data/cartesia-live/<time>.json. Paste back the SUMMARY block it prints and that JSON file.
Needs CARTESIA_API_KEY (and CARTESIA_VOICE_ID for checks 3 to 5). Without the key it prints "skipped" and exits 0.
Real runs use a few short generations and some seconds of audio on your key.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import cartesia_repro  # noqa: E402  (scripts/cartesia_repro.py: reused, not copied)
import caption_probe  # noqa: E402  (scripts/caption_probe.py: reused, not copied)
from unstep.cockpit.cartesia_errors import (RATE_LIMIT_EVENTS, CartesiaRateLimited, is_rate_limited,  # noqa: E402
                                            log_rate_limited, open_socket_count, redact, socket_closed,
                                            socket_opened)
from unstep.cockpit.stt import build_keyterms  # noqa: E402
from unstep.config import cartesia_stt_model, cartesia_tts_model, cartesia_version, env  # noqa: E402

OUT = ROOT / "data" / "cartesia-live"
DICT_PATH = ROOT / "assets" / "pronunciation" / "atc.json"
CHECKS = ("caption", "turns", "tts", "dict", "rate")
HARD_MAX_SOCKETS = 6  # never open more than this, whatever the flag says
DEFAULT_SOCKETS = 4
TTS_TEXT = "Advisory. Cessna one two three, hold short runway three three."
PROBE_TEXT = "Advisory. Radio check, one two three, four five six, seven eight niner."

# Words that count as a correct hearing of each dictionary entry. This is our judgement, not Cartesia's:
# STT may write the plain word for a respelled digit word. Anything not listed must come back as itself.
ACCEPT = {
    "fower": ("fower", "four", "4"), "tree": ("tree", "three", "3"), "fife": ("fife", "five", "5"),
    "niner": ("niner", "nine", "9"), "juliett": ("juliett", "juliet"), "quebec": ("quebec",),
    "notam": ("notam", "notams"), "unstep": ("unstep", "un step"),
}
CONTROL_WORDS = ("niner",)  # not in the dictionary on purpose (docs/09 lesson): checked without the entry only


# ---------------------------------------------------------------- results

class Check:
    """Lines of one check. status: FAIL beats PASS beats INFO; SKIP when nothing ran."""

    def __init__(self, name: str, title: str):
        self.name, self.title = name, title
        self.lines: list[tuple[str, str]] = []
        self.data: dict = {}

    def add(self, level: str, text: str) -> None:
        self.lines.append((level, text))
        print(f"  {level:4} {text}", flush=True)

    @property
    def status(self) -> str:
        levels = {lvl for lvl, _ in self.lines}
        for lvl in ("FAIL", "PASS", "INFO"):
            if lvl in levels:
                return lvl
        return "SKIP"

    def as_dict(self) -> dict:
        return {"name": self.name, "title": self.title, "status": self.status,
                "lines": [{"level": lvl, "text": text} for lvl, text in self.lines], "data": self.data}


def p50(values: list[float]) -> float | None:
    return round(sorted(values)[len(values) // 2], 1) if values else None


def words_of(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def heard_ok(word: str, heard: str) -> bool:
    options = ACCEPT.get(word.lower(), (word.lower(),))
    spoken = f" {words_of(heard)} "
    return any(f" {o} " in spoken for o in options)


# ---------------------------------------------------------------- backends

class LiveBackend:
    """The real Cartesia API. Reuses caption_probe and cartesia_repro; every socket is closed in a finally."""

    label = "live"

    def __init__(self):
        self.terms = build_keyterms()
        self.dict_id = env("CARTESIA_PRONUNCIATION_DICT_ID")
        self.has_voice = bool(env("CARTESIA_VOICE_ID"))

    def clip(self, which: str) -> tuple[str, bytes]:
        path = caption_probe.CLIP if which == "caption" else cartesia_repro.CLIP
        return path.name, caption_probe.pcm16(path)

    async def caption(self, endpoint: str, pcm: bytes) -> list[tuple[float, int]]:
        return await caption_probe.PROBES[endpoint](pcm)

    async def turns_pacing(self, pcm: bytes, runs: int) -> dict:
        return await cartesia_repro.turns_pacing(pcm, runs)

    async def tts_first_audio(self, text: str, runs: int) -> list[float | None]:
        from unstep.cockpit.tts import CartesiaTTS

        tts, out = CartesiaTTS(), []
        try:
            for _ in range(runs):
                out.append((await tts.speak(text)).first_audio_ms)
        finally:
            await tts.close()
        return out

    async def roundtrip(self, text: str, use_dict: bool) -> str:
        from unstep.cockpit.stt import CartesiaManualSTT
        from unstep.cockpit.tts import CartesiaTTS

        tts = CartesiaTTS(sample_rate=16000)
        if not use_dict:
            tts.pronunciation_dict_id = None  # the constructor falls back to the env var; switch it off
        try:
            speech = await tts.speak(text)
        finally:
            await tts.close()
        async with CartesiaManualSTT(keyterms=self.terms) as stt:
            await cartesia_repro.send_fast(stt, speech.pcm)
            return (await stt.finalize()).text

    async def probe_step(self, k: int) -> dict:
        """k sockets open together, then k generations at the same moment. Always closes them all."""
        from unstep.cockpit.tts import CartesiaTTS

        sockets = [CartesiaTTS() for _ in range(k)]
        step: dict = {"k": k, "connected": 0, "connect_429": [], "generations": []}
        try:
            opened = await asyncio.gather(*(s.connect() for s in sockets), return_exceptions=True)
            live = [s for s, r in zip(sockets, opened) if not isinstance(r, BaseException)]
            for r in opened:
                if isinstance(r, BaseException):
                    key = "connect_429" if is_rate_limited(r) else "connect_errors"
                    step.setdefault(key, []).append(describe(r))
            step["connected"], step["open_sockets"] = len(live), open_socket_count()
            results = await asyncio.gather(*(s.speak(PROBE_TEXT) for s in live), return_exceptions=True)
            for r in results:
                if isinstance(r, BaseException):
                    step["generations"].append({"ok": False, "rate_limited": is_rate_limited(r), **describe(r)})
                else:
                    step["generations"].append({"ok": True, "rate_limited": False, "first_audio_ms": r.first_audio_ms})
        finally:
            await asyncio.gather(*(s.close() for s in sockets), return_exceptions=True)
        return step


def describe(exc: BaseException) -> dict:
    out = {"error": redact(f"{type(exc).__name__}: {exc}")[:300]}
    if isinstance(exc, CartesiaRateLimited):
        out |= {"status": exc.status, "body": exc.body, "open_sockets": exc.open_sockets}
    return out


class FakeBackend:
    """Offline stand-in, labelled FAKE on screen. Uses the real socket counter so leaks would show.

    `heard` maps (word, use_dict) to what the pretend STT heard; `rate_limit_at` is the k at which the
    pretend server answers 429."""

    label = "FAKE (dry run)"

    def __init__(self, heard: dict | None = None, rate_limit_at: int | None = None,
                 dict_id: str | None = "fake-dict", errors: set | None = None):
        self.heard = heard or {}
        self.rate_limit_at = rate_limit_at
        self.dict_id = dict_id
        self.errors = errors or set()
        self.has_voice = True

    def clip(self, which: str) -> tuple[str, bytes]:
        return f"fake-{which}.wav", b"\x00\x00" * 16000 * 4

    def _maybe_fail(self, name: str) -> None:
        if name in self.errors:
            raise RuntimeError(f"fake {name} failure")

    async def caption(self, endpoint: str, pcm: bytes) -> list[tuple[float, int]]:
        self._maybe_fail("caption-" + endpoint)
        step = 0.6 if endpoint == "manual" else 0.3
        return [(step * (i + 1), 2 * (i + 1)) for i in range(6)]

    async def turns_pacing(self, pcm: bytes, runs: int) -> dict:
        self._maybe_fail("turns")
        return {"fast": {"runs": runs, "empty": 0, "correct": runs, "examples": ["hold short runway 33"]},
                "paced": {"runs": runs, "empty": 0, "correct": runs, "examples": ["hold short runway 33"]}}

    async def tts_first_audio(self, text: str, runs: int) -> list[float | None]:
        self._maybe_fail("tts")
        socket_opened("tts")
        try:
            return [160.0] + [95.0] * (runs - 1)
        finally:
            socket_closed("tts")

    async def roundtrip(self, text: str, use_dict: bool) -> str:
        self._maybe_fail("roundtrip")
        word = text.split(",")[1].strip()
        return self.heard.get((word, use_dict), f"Tower, {word}, hold short.")

    async def probe_step(self, k: int) -> dict:
        step: dict = {"k": k, "connected": k, "connect_429": [], "generations": []}
        for _ in range(k):
            socket_opened("tts")
        try:
            step["open_sockets"] = open_socket_count()
            for i in range(k):
                if self.rate_limit_at is not None and k >= self.rate_limit_at and i == k - 1:
                    event = {"type": "error", "status_code": 429, "title": "FAKE too many requests",
                             "message": "FAKE body for the dry run"}
                    detail = log_rate_limited(event, "fake tts")
                    step["generations"].append({"ok": False, "rate_limited": True, "status": 429,
                                               "body": detail["body"], "open_sockets": detail["open_sockets"],
                                               "error": "CartesiaRateLimited"})
                else:
                    step["generations"].append({"ok": True, "rate_limited": False, "first_audio_ms": 100.0})
        finally:
            for _ in range(k):
                socket_closed("tts")
        return step


# ---------------------------------------------------------------- the checks

async def check_caption(b, args) -> Check:
    c = Check("caption", "Caption probe: manual versus turns endpoint")
    _, pcm = b.clip("caption")
    audio_s = len(pcm) / 32000
    c.data["clip_s"] = round(audio_s, 2)
    medians = {}
    for endpoint in ("manual", "turns"):
        runs, errors = [], []
        for _ in range(args.runs):
            try:
                runs.append(caption_probe.summarize(await b.caption(endpoint, pcm), audio_s))
            except Exception as exc:  # a failing endpoint is itself a finding
                errors.append(redact(f"{type(exc).__name__}: {exc}")[:200])
        c.data[endpoint] = {"runs": runs, "errors": errors}
        got = [r for r in runs if r.get("updates")]
        if errors:
            c.add("FAIL", f"{endpoint}: {len(errors)} of {args.runs} runs raised: {errors[0]}")
        if got:
            c.add("PASS", f"{endpoint}: text arrived in {len(got)} of {args.runs} runs")
            gaps = [r["gap_median_ms"] for r in got if r.get("gap_median_ms") is not None]
            worst = [r["gap_worst_ms"] for r in got if r.get("gap_worst_ms") is not None]
            medians[endpoint] = p50(gaps)
            c.add("INFO", f"{endpoint}: updates while speaking {p50([r['updates_while_speaking'] for r in got])}, "
                          f"first text {p50([r['first_text_ms'] for r in got])} ms, median gap {medians[endpoint]} ms, "
                          f"worst gap {max(worst) if worst else None} ms, "
                          f"last update {p50([r['last_update_after_end_ms'] for r in got])} ms after the clip ended")
        elif not errors:
            c.add("FAIL", f"{endpoint}: no text in any of {args.runs} runs")
    if len(medians) == 2 and None not in medians.values():
        c.add("INFO", f"median gap between updates: manual {medians['manual']} ms, turns {medians['turns']} ms "
                      "(smaller means smoother captions; settles UNSTEP_CAPTION_SOURCE)")
    return c


async def check_turns(b, args) -> Check:
    c = Check("turns", "Turns endpoint: fast versus paced audio")
    _, pcm = b.clip("turns")
    result = await b.turns_pacing(pcm, args.turns_runs)
    c.data.update(result)
    for mode in ("fast", "paced"):
        r = result[mode]
        n = r["runs"]
        text = f"{mode}: {r['correct']}/{n} correct, {r['empty']} empty"
        c.add("PASS" if r["empty"] == 0 and r["correct"] == n else "INFO", text)
    c.add("INFO", "docs/09 and docs/24: fast sends were empty once (night of 2026-10-23) and 15/15 fine on 2026-10-24; "
                  "paced runs were empty about 2 in 25. Empties here reproduce that; zero empties do not disprove it")
    return c


async def check_tts(b, args) -> Check:
    c = Check("tts", "TTS first audio time")
    if not b.has_voice:
        c.add("SKIP", "CARTESIA_VOICE_ID not set")
        return c
    times = await b.tts_first_audio(TTS_TEXT, args.tts_runs)
    c.data["first_audio_ms"] = times
    got = [t for t in times if t is not None]
    if len(got) < len(times):
        c.add("FAIL", f"{len(times) - len(got)} of {len(times)} requests returned no audio")
    if got:
        warm = got[1:]
        c.add("INFO", f"first request on the socket {got[0]:.0f} ms; warm requests "
                      f"{', '.join(f'{t:.0f}' for t in warm) or 'none'} ms (docs/09 REPORTED 88 to 115 ms, one cold 214 ms)")
        mid = p50(warm or got)
        c.data["p50_ms"] = mid
        ok = mid <= args.first_audio_budget_ms
        c.add("PASS" if ok else "FAIL", f"p50 {mid} ms against our own demo budget of {args.first_audio_budget_ms:.0f} ms "
                                        "(the budget is ours, not a Cartesia figure)")
    return c


async def check_dict(b, args) -> Check:
    c = Check("dict", "Pronunciation dictionary round trip (TTS then STT)")
    if not b.has_voice:
        c.add("SKIP", "CARTESIA_VOICE_ID not set")
        return c
    entries = json.loads(DICT_PATH.read_text(encoding="utf-8"))
    words = [(e["text"], e["pronunciation"], True) for e in entries]
    words += [(w, None, False) for w in CONTROL_WORDS if w.lower() not in {e["text"].lower() for e in entries}]
    variants = [("baseline", False)] + ([("dict", True)] if b.dict_id else [])
    if not b.dict_id:
        c.add("INFO", "CARTESIA_PRONUNCIATION_DICT_ID not set: only the no-dictionary baseline runs. Set it to the "
                      "unstep-atc-v2 id to test the respellings themselves")
    c.data["dict_id_set"] = bool(b.dict_id)
    rows, failing, breaks, fixes = [], [], [], []
    for word, respelling, in_dict in words:
        row = {"word": word, "respelling": respelling, "in_dictionary": in_dict}
        for name, use_dict in variants:
            heard = []
            for _ in range(args.dict_runs):
                try:
                    heard.append(await b.roundtrip(f"Tower, {word}, hold short.", use_dict))
                except Exception as exc:
                    heard.append("ERROR " + redact(f"{type(exc).__name__}: {exc}")[:120])
            row[name] = {"ok": sum(heard_ok(word, h) for h in heard), "runs": len(heard), "heard": heard}
        rows.append(row)
        base, withd = row["baseline"], row.get("dict")
        shown = f"{word!r}" + (f" ({respelling})" if respelling else " (control, no entry)")
        if withd is not None and in_dict:
            full = withd["ok"] == withd["runs"]
            c.add("PASS" if full else "FAIL", f"{shown}: with dictionary heard right {withd['ok']}/{withd['runs']}; "
                                              f"without {base['ok']}/{base['runs']}; first heard {withd['heard'][0]!r}")
            if not full:
                failing.append(word)
                if base["ok"] == base["runs"]:
                    breaks.append(word)
            elif base["ok"] < base["runs"]:
                fixes.append(word)
        else:
            full = base["ok"] == base["runs"]
            c.add("PASS" if full else "INFO", f"{shown}: without dictionary heard right {base['ok']}/{base['runs']}; "
                                              f"first heard {base['heard'][0]!r}")
    c.data["rows"] = rows
    c.data["failing_with_dictionary"] = failing
    c.data["respelling_breaks_recognition"] = breaks
    c.data["respelling_fixes_recognition"] = fixes
    if b.dict_id:
        c.add("INFO" if not failing else "FAIL",
              "entries that fail the round trip: " + (", ".join(failing) if failing else "none") +
              ("; the respelling made it worse than no entry for: " + ", ".join(breaks) if breaks else ""))
    c.add("INFO", "a pass means ink-2 wrote the word (or its plain digit word, see ACCEPT in the script); "
                  f"{args.dict_runs} runs on one voice with production key terms, so it is a screen, not a proof")
    return c


async def check_rate(b, args) -> Check:
    c = Check("rate", f"429 probe: up to {args.max_sockets} sockets and concurrent generations")
    if not b.has_voice:
        c.add("SKIP", "CARTESIA_VOICE_ID not set")
        return c
    steps = []
    c.data["steps"] = steps
    first_429 = None
    for k in range(1, args.max_sockets + 1):
        before = len(RATE_LIMIT_EVENTS)
        step = await b.probe_step(k)
        steps.append(step)
        limited = [g for g in step["generations"] if g.get("rate_limited")] + step["connect_429"]
        ok = sum(g["ok"] for g in step["generations"])
        c.add("INFO", f"{k} socket(s): connected {step['connected']}, open count {step.get('open_sockets')}, "
                      f"generations ok {ok}/{len(step['generations'])}, 429s {len(limited)}")
        if limited:
            first_429 = {"k": k, "detail": limited[0], "events_logged": len(RATE_LIMIT_EVENTS) - before}
            break
        failed = [g for g in step["generations"] if not g["ok"]]
        if failed:
            c.add("FAIL", f"{k} socket(s): generation failed without a 429: {failed[0]['error']}")
            break
    c.data["first_429"] = first_429
    if first_429:
        d = first_429["detail"]
        c.add("INFO", f"first HTTP 429 at {first_429['k']} concurrent generations. status={d.get('status')} "
                      f"body={d.get('body')!r} open sockets then={d.get('open_sockets')}")
        c.add("INFO", "every socket in this probe is closed after each step, so the open count equals the sockets used "
                      "on purpose. A 429 here is consistent with a plan concurrency limit and not with our leak. "
                      "Check the body text and the plan limit on your Cartesia dashboard (unverified)")
    else:
        c.add("INFO", f"no 429 up to {args.max_sockets} concurrent generations. That does not rule out a plan limit "
                      "above that, and says nothing about what a leak does after many idle sockets")
    return c


RUNNERS = {"caption": check_caption, "turns": check_turns, "tts": check_tts, "dict": check_dict, "rate": check_rate}
TITLES = {"caption": "Caption probe: manual versus turns endpoint", "turns": "Turns endpoint: fast versus paced audio",
          "tts": "TTS first audio time", "dict": "Pronunciation dictionary round trip (TTS then STT)",
          "rate": "429 probe"}


# ---------------------------------------------------------------- run

async def run(backend, args) -> dict:
    report = {"mode": "dry-run" if isinstance(backend, FakeBackend) else "live", "backend": backend.label,
              "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "cartesia_version": cartesia_version(),
              "models": {"stt": cartesia_stt_model(), "tts": cartesia_tts_model()},
              "args": {k: v for k, v in vars(args).items() if k not in ("out_dir",)}, "checks": []}
    if report["mode"] == "dry-run":
        print("FAKE BACKEND: dry run, nothing here touched Cartesia\n")
    names = args.only or list(CHECKS)
    for i, name in enumerate(names, 1):
        print(f"[{i}/{len(names)}] {TITLES[name]}", flush=True)
        try:
            check = await asyncio.wait_for(RUNNERS[name](backend, args), args.check_timeout)
        except Exception as exc:
            check = Check(name, TITLES[name])
            check.add("FAIL", redact(f"{type(exc).__name__}: {exc}")[:300] or "timed out")
        report["checks"].append(check.as_dict())
    leaked = open_socket_count()
    end = Check("sockets", "Sockets left open")
    print("[end] sockets")
    end.add("PASS" if leaked == 0 else "FAIL", f"{leaked} socket(s) still open after all checks")
    report["checks"].append(end.as_dict())
    report["rate_limit_events"] = list(RATE_LIMIT_EVENTS)
    report["open_sockets_at_end"] = leaked
    return report


def print_summary(report: dict, path: Path | None) -> None:
    print("\n=== SUMMARY (paste this block back) ===")
    print(f"mode={report['mode']} started={report['started']} cartesia_version={report['cartesia_version']} "
          f"stt={report['models']['stt']} tts={report['models']['tts']}")
    for c in report["checks"]:
        print(f"{c['status']:4} {c['name']}")
        for line in c["lines"]:
            if line["level"] in ("FAIL", "PASS", "INFO", "SKIP"):
                print(f"       {line['level']:4} {line['text']}")
    if path:
        print(f"\nJSON report: {path}  (paste its contents too)")
    print("=== END SUMMARY ===")


def parse(argv=None) -> argparse.Namespace:
    def sockets(value: str) -> int:
        n = int(value)
        if not 1 <= n <= HARD_MAX_SOCKETS:
            raise argparse.ArgumentTypeError(f"--max-sockets must be 1 to {HARD_MAX_SOCKETS}")
        return n

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dry-run", action="store_true", help="use fakes: offline, no key needed")
    p.add_argument("--only", nargs="*", choices=CHECKS, help="run only these checks")
    p.add_argument("--runs", type=int, default=3, help="caption probe runs per endpoint")
    p.add_argument("--turns-runs", type=int, default=5, help="runs per mode for the turns pacing repro")
    p.add_argument("--tts-runs", type=int, default=5)
    p.add_argument("--dict-runs", type=int, default=2, help="round trips per word and variant")
    p.add_argument("--max-sockets", type=sockets, default=DEFAULT_SOCKETS, help=f"429 probe cap, at most {HARD_MAX_SOCKETS}")
    p.add_argument("--first-audio-budget-ms", type=float, default=300.0)
    p.add_argument("--check-timeout", type=float, default=240.0, help="seconds before one check is given up")
    p.add_argument("--out-dir", type=Path, default=OUT)
    return p.parse_args(argv)


def main(argv=None, backend=None) -> int:
    args = parse(argv)
    if backend is None:
        if args.dry_run:
            backend = FakeBackend()
        elif not env("CARTESIA_API_KEY"):
            print("skipped: CARTESIA_API_KEY not set (use --dry-run to check the script offline)")
            return 0
        else:
            backend = LiveBackend()
    report = asyncio.run(run(backend, args))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "-dry-run" if report["mode"] == "dry-run" else ""
    path = args.out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}{suffix}.json"
    path.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print_summary(report, path)
    return 1 if any(c["status"] == "FAIL" for c in report["checks"]) else 0


if __name__ == "__main__":
    sys.exit(main())
