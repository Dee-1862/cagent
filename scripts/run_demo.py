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

import uvicorn  # noqa: E402
import websockets  # noqa: E402

from unstep.cockpit.audio import WavFileSource  # noqa: E402
from unstep.cockpit.edge import AudioOut, CockpitEdge, GatewayLink, Line  # noqa: E402
from unstep.cockpit.memory import LocalMemory  # noqa: E402
from unstep.cockpit.stt import FakeManualSTT, FakeTurnSTT  # noqa: E402
from unstep.cockpit.tts import FakeTTS  # noqa: E402
from unstep.clock import now_ms  # noqa: E402
from unstep.contracts import ProposedDirective, ReadbackResult, VoiceApproval, unwrap  # noqa: E402
from unstep.gateway.server import create_app  # noqa: E402
from unstep.gateway.sink import MemorySink  # noqa: E402
from unstep.ground import auto_approver, mock_agents  # noqa: E402

CLIPS = ROOT / "assets" / "clips"
QUESTION = "Unstep, what was my last clearance?"
READBACKS = ["Hold short runway two three, Cessna 1-2-3", "Hold short runway three three, Cessna 1-2-3"]


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
    async with websockets.connect(f"{url}/ws/dashboard") as ws:
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


async def demo(clean: bool, play: bool) -> int:
    sink = MemorySink()
    server, server_task, url, gw = await start_gateway(sink)
    print(f"gateway on {url}; starting mock agents, auto approver, cockpit edge")
    helpers = [asyncio.create_task(mock_agents.run(url)), asyncio.create_task(auto_approver.run(url))]
    edge = CockpitEdge(
        link=GatewayLink(url),
        memory=LocalMemory(),
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
        clip = CLIPS / ("clean_call.wav" if clean else "stepped_on_call.wav")
        edge._note("RADIO", f"playing {clip.name}")
        events = await edge.run_audio(WavFileSource(clip))

        if clean:
            ok = not events and not any(r.get("type") == "AnomalyEvent" for r in sink.records)
        else:
            ok = len(events) == 1
            if ok:
                outcome = await edge.wait_resolved(events[0].event_id, 15)
                edge._note("SYSTEM", f"event {events[0].event_id}: {outcome}")
                q = await edge.ask(QUESTION)
                results = [m for m in edge.sent if isinstance(m, ReadbackResult)]
                ok = (outcome == "confirmed" and [r.match for r in results] == [False, True]
                      and "hold short" in q.answer.lower() and q.source_doc_id is not None
                      and events[0].local_hint.kind == "restrictive"
                      and not edge.outbox)
        await asyncio.sleep(0.1)
    finally:
        await edge.stop()
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
    print(f"\nAudio (left ear only): {edge.out.path}")
    print(("PASS" if ok else "FAIL") + (" (clean call, no event fired)" if clean and ok else ""))
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--clean", action="store_true", help="use clean_call.wav and prove no event fires")
    p.add_argument("--play", action="store_true", help="also play the advisory audio through sounddevice")
    p.add_argument("-v", action="store_true", help="verbose logging")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO if a.v else logging.WARNING, format="%(name)s %(message)s")
    return asyncio.run(demo(a.clean, a.play))


if __name__ == "__main__":
    raise SystemExit(main())
