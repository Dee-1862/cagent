"""Mock cockpit for M2 (Dev A). Sends the demo AnomalyEvent and prints the advisory
when the directive comes back. Real audio, Moss and Cartesia replace the fake
parts in tasks A1 to A7.

Run: python -m unstep.cockpit.mock_cockpit [--runs 10]
"""

import argparse
import asyncio
import time

import websockets

from unstep import scenario
from unstep.clock import now_ms
from unstep.config import gateway_url, ws_url
from unstep.contracts import ApprovedDirective, RejectedDirective, unwrap, wrap


async def one_run(ws, run: int, timeout_s: float) -> bool:
    event = scenario.anomaly_event(event_id=f"evt-{now_ms()}-{run}", t0=now_ms())
    print(f"[{run}] Advisory. Transmission blocked. Likely {event.local_hint.text}. Awaiting controller.")
    started = time.perf_counter()
    await ws.send(wrap(event))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
        env, msg = unwrap(raw)
        if msg is None:
            print(f"[{run}] gateway error: {env.data.get('message')}")
            continue
        if getattr(msg, "event_id", None) != event.event_id:
            continue
        ms = (time.perf_counter() - started) * 1000
        if isinstance(msg, ApprovedDirective):
            print(f"[{run}] Advisory. {msg.instruction_text}. Read back. ({msg.approved_via}, {ms:.0f} ms)")
            return True
        if isinstance(msg, RejectedDirective):
            print(f"[{run}] Advisory. Request say again. ({msg.rejected_via}, {ms:.0f} ms)")
            return True


async def main(url: str, runs: int, timeout_s: float) -> int:
    ok = 0
    async with websockets.connect(ws_url("cockpit", url)) as ws:
        for run in range(1, runs + 1):
            try:
                ok += await one_run(ws, run, timeout_s)
            except asyncio.TimeoutError:
                print(f"[{run}] no decision within {timeout_s:.0f} s")
    print(f"{ok}/{runs} runs completed")
    return 0 if ok == runs else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=None, help="gateway URL (default: UNSTEP_GATEWAY_URL)")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--timeout", type=float, default=60.0, help="seconds to wait for a decision (gateway TTL)")
    a = p.parse_args()
    raise SystemExit(asyncio.run(main(a.url or gateway_url(), a.runs, a.timeout)))
