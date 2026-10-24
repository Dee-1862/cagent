"""Stands in for the controller during automated M2 runs: approves every proposal
by sending a VoiceApproval, like the voice loop (task B10) will.

Run: python -m unstep.ground.auto_approver
"""

import argparse
import asyncio

import websockets

from unstep.contracts import ProposedDirective, VoiceApproval, unwrap, wrap


async def run(url: str) -> None:
    async with websockets.connect(f"{url}/ws/controller_voice") as ws:
        print("auto approver connected")
        async for raw in ws:
            _, msg = unwrap(raw)
            if isinstance(msg, ProposedDirective):
                await ws.send(wrap(VoiceApproval(event_id=msg.event_id, heard_text="Approve", decision="approve")))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://127.0.0.1:8765")
    asyncio.run(run(p.parse_args().url))
