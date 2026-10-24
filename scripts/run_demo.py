"""One-command offline demo of the PRD section 11 flow.

Starts the gateway (uvicorn, in-process, free port), the mock ground agents, the
auto approver (stands in for the controller voice loop) and the real CockpitEdge
on assets/clips/stepped_on_call.wav, all with fakes (no network keys needed):

  stepped-on call -> local hint -> controller approves by voice -> directive in
  the left ear -> wrong readback -> correction -> right readback -> pilot query.

Prints what each party heard with measured latencies, writes data/cockpit_audio.wav,
and exits 0 on success.

Run from the repo root:
  python scripts/run_demo.py           # full flow
  python scripts/run_demo.py --clean   # clean_call.wav: no event may fire
  python scripts/run_demo.py --live    # real Cartesia STT/TTS on assets/clips/real
                                       # (keys from .env), writes data/cockpit_audio_live.wav

Live mode makes about 6 TTS and 4 STT calls. Clips are sent at real time.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import uvicorn  # noqa: E402
import websockets  # noqa: E402

from unstep.cockpit.audio import WavFileSource, read_wav  # noqa: E402
from unstep.config import ws_url  # noqa: E402
from unstep.cockpit.edge import AudioOut, CockpitEdge, GatewayLink, Line  # noqa: E402
from unstep.cockpit.memory import LocalMemory, create_memory  # noqa: E402
from unstep.cockpit.inference import FakeAnswerer  # noqa: E402
from unstep.cockpit.stt import FakeManualSTT, FakeTurnSTT, ReplayTurnSTT  # noqa: E402
from unstep.cockpit.tts import FakeTTS  # noqa: E402
from unstep.clock import now_ms  # noqa: E402
from unstep.contracts import ProposedDirective, ReadbackResult, VoiceApproval, unwrap  # noqa: E402
from unstep.gateway.server import create_app  # noqa: E402
from unstep.gateway.sink import MemorySink  # noqa: E402
from unstep.ground import mock_agents, voice_approval  # noqa: E402

CLIPS = ROOT / "assets" / "clips"
QUESTION = "Unstep, what was my last clearance?"
READBACKS = ["Hold short runway two three, Cessna 1-2-3", "Hold short runway three three, Cessna 1-2-3"]
REAL = CLIPS / "real"
LIVE_WAV_OUT = ROOT / "data" / "cockpit_audio_live.wav"


# ---------------------------------------------------------------- live mode


def clip_pcm(name: str) -> bytes:
    """A 16 kHz clip from assets/clips/real as pcm_s16le bytes."""
    return (np.clip(read_wav(REAL / name), -1, 1) * 32767).astype("<i2").tobytes()


def live_engines():
    """Real Cartesia engines. Keys come from .env and are never printed."""
    import os

    from unstep import scenario
    from unstep.cockpit.stt import CartesiaManualSTT, CartesiaTurnSTT, build_keyterms
    from unstep.cockpit.tts import CartesiaTTS

    missing = [k for k in ("CARTESIA_API_KEY", "CARTESIA_VOICE_ID") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"--live needs {', '.join(missing)} in .env")
    terms = build_keyterms(callsigns=[scenario.SPOKEN_CALLSIGN, scenario.CALLSIGN], runways=["33", "28L"])
    tts = CartesiaTTS()  # voice and pronunciation dict ids from .env
    manual = lambda: CartesiaManualSTT(keyterms=terms)  # noqa: E731
    turns = lambda: CartesiaTurnSTT(keyterms=terms)  # noqa: E731
    readbacks = ReplayTurnSTT(turns, [clip_pcm("wrong_readback.wav"), clip_pcm("correct_readback.wav")])
    question = ReplayTurnSTT(turns, [clip_pcm("pilot_question.wav")])
    print(f"live: Cartesia {tts.model_id}, pronunciation dict {'set' if tts.pronunciation_dict_id else 'none'}, "
          f"STT ink-2 with {len(terms)} key terms")
    return tts, manual, readbacks, question


async def transcribe_turn(stt: ReplayTurnSTT) -> str:
    async for ev in stt.events():
        if ev.type == "turn.end":
            return ev.transcript
    return ""


def print_live_table(edge) -> None:
    rows = [
        ("STT manual finalize -> transcript", "stt_final_ms"),
        ("STT turns end of speech -> turn.end", "stt_turn_end_ms"),
        ("TTS first audio", "tts_first_audio_ms"),
        ("Memory search (Moss or local)", "moss_ms"),
        ("Readback verdict", "readback_verdict_ms"),
        ("Event -> directive round trip", "round_trip_ms"),
    ]
    print("\n=== Live latency (ms) ===")
    for label, key in rows:
        vals = edge.latency.get(key, [])
        shown = ", ".join(f"{v:.0f}" if v >= 10 else f"{v:.2f}" for v in vals) or "n/a"
        print(f"  {label:<38} {shown}")


def play_file(path: Path) -> None:
    try:
        import sounddevice as sd
        import soundfile as sf

        audio, sr = sf.read(str(path), dtype="int16")
        sd.play(audio, sr)
        sd.wait()
    except Exception as e:  # no audio device: the WAV is still there
        print(f"playback failed: {e}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def start_gateway(sink) -> tuple[uvicorn.Server, asyncio.Task, str, object]:
    app = create_app(sink)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    return server, task, f"ws://127.0.0.1:{port}", app.state.gateway


async def controller_view(url: str, lines: list[Line]) -> None:
    """What the controller hears/says, read from the dashboard feed."""
    async with websockets.connect(ws_url("dashboard", url)) as ws:
        async for raw in ws:
            _, msg = unwrap(raw)
            if isinstance(msg, ProposedDirective):
                s = msg.slots
                rwy = f" Runway {s.runway}" if s.runway else ""
                lines.append(Line(now_ms(), "CONTROLLER",
                                  f"hears: [chime] Blocked call to {s.callsign}: {s.action}{rwy}. Approve? "
                                  f"(confidence {msg.confidence})"))
            elif isinstance(msg, VoiceApproval):
                lines.append(Line(now_ms(), "CONTROLLER", f"says on the Unstep key: {msg.heard_text!r} "
                                                          f"-> {msg.decision}"))
            elif isinstance(msg, ReadbackResult) and not msg.match:
                lines.append(Line(now_ms(), "CONTROLLER", f"dashboard: readback attempt {msg.attempt} wrong "
                                                          f"({msg.readback_text!r})"))


def print_transcript(lines: list[Line]) -> None:
    t0 = lines[0].ts if lines else 0
    print("\n=== Transcript (what each party heard) ===")
    for ln in lines:
        lat = "  ".join(f"{k}={v:.1f}" for k, v in ln.latency.items())
        print(f"+{ln.ts - t0:5d} ms  {ln.party:<10} {ln.text}" + (f"   [{lat}]" if lat else ""))


async def demo(clean: bool, play: bool, live: bool = False) -> int:
    sink = MemorySink()
    server, server_task, url, gw = await start_gateway(sink)
    print(f"gateway on {url}; starting mock agents, controller voice approval, cockpit edge")
    # Controller voice approval loop (B10): prompt, "Approve" on the Unstep key, repeat-back, then send.
    controller = voice_approval.run(url, FakeTTS(), lambda: FakeTurnSTT(["Approve"]))
    helpers = [asyncio.create_task(mock_agents.run(url)), asyncio.create_task(controller)]
    if live:
        tts, manual_factory, readbacks, question_stt = live_engines()
        edge = CockpitEdge(link=GatewayLink(url), memory=create_memory(), tts=tts,  # real Moss when keys are set
                           manual_stt_factory=manual_factory, turn_stt_factory=lambda: readbacks,
                           audio_out=AudioOut(LIVE_WAV_OUT))  # played at the end, not mid-flow
    else:
        edge = CockpitEdge(
            link=GatewayLink(url),
            memory=LocalMemory(),
            answerer=FakeAnswerer(),
            tts=FakeTTS(),
            manual_stt_factory=lambda: FakeManualSTT(["Cessna 1-2-3 [static]"]),
            turn_stt_factory=lambda: FakeTurnSTT(READBACKS),
            audio_out=AudioOut(live=play),
        )
    helpers.append(asyncio.create_task(controller_view(url, edge.lines)))
    for _ in range(200):
        if all(gw.clients.get(r) for r in ("agents", "controller_voice", "dashboard")):
            break
        await asyncio.sleep(0.02)

    ok = True
    try:
        if not await edge.start():
            print("FAIL: cockpit could not reach the gateway")
            return 1
        clip = (REAL if live else CLIPS) / ("clean_call.wav" if clean else "stepped_on_call.wav")
        edge._note("RADIO", f"playing {clip.relative_to(CLIPS).as_posix()}" + (" at real time" if live else ""))
        events = await edge.run_audio(WavFileSource(clip), realtime=live)

        if clean:
            ok = not events and not any(r.get("type") == "AnomalyEvent" for r in sink.records)
        else:
            ok = len(events) == 1
            if ok:
                outcome = await edge.wait_resolved(events[0].event_id, 60 if live else 15)
                edge._note("SYSTEM", f"event {events[0].event_id}: {outcome}")
                question = QUESTION
                if live:
                    question = await transcribe_turn(question_stt)
                q = await edge.ask(question)
                freeform = await edge.ask("Unstep, what runway was I told to stop at?")
                results = [m for m in edge.sent if isinstance(m, ReadbackResult)]
                ok = (outcome == "confirmed" and [r.match for r in results] == [False, True]
                      and "hold short" in q.answer.lower() and q.source_doc_id is not None
                      and "hold short" in freeform.answer.lower()
                      and freeform.source_doc_id == q.source_doc_id
                      and events[0].local_hint.kind == "restrictive"
                      and not edge.outbox)
        await asyncio.sleep(0.1)
    finally:
        await edge.stop()
        if live:
            for v in readbacks.turn_end_ms + question_stt.turn_end_ms:
                edge._measure("stt_turn_end_ms", v)
            await tts.close()
        for h in helpers:
            h.cancel()
        server.should_exit = True
        await server_task

    print_transcript(edge.lines)
    print("\n=== Measured latencies (ms) ===")
    for k, v in edge.latency_summary().items():
        print(f"  {k:<22} n={v['n']:<4} mean={v['mean']:<9} max={v['max']}")
    types: dict[str, int] = {}
    for r in sink.records:
        types[r["type"]] = types.get(r["type"], 0) + 1
    print("\n=== Gateway stored ===\n  " + ", ".join(f"{k}: {v}" for k, v in sorted(types.items())))
    if live:
        print_live_table(edge)
    print(f"\nAudio (left ear only): {edge.out.path}")
    if live and play and edge.out.path and edge.out.path.exists():
        play_file(edge.out.path)
    print(("PASS" if ok else "FAIL") + (" (clean call, no event fired)" if clean and ok else ""))
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--clean", action="store_true", help="use clean_call.wav and prove no event fires")
    p.add_argument("--play", action="store_true", help="also play the advisory audio through sounddevice")
    p.add_argument("--live", action="store_true", help="real Cartesia STT and TTS on assets/clips/real (keys in .env)")
    p.add_argument("-v", action="store_true", help="verbose logging")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO if a.v else logging.WARNING, format="%(name)s %(message)s")
    if a.live:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    return asyncio.run(demo(a.clean, a.play, a.live))


if __name__ == "__main__":
    raise SystemExit(main())
