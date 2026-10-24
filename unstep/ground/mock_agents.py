"""Mock ground agents for M2. Dev B replaces this with the Elastic Workflow (task B5).

Turns each AnomalyEvent into a ProposedDirective. Until tower STT exists, the
instruction comes from the cockpit's local hint, marked low confidence.

Run: python -m unstep.ground.mock_agents
"""

import argparse
import asyncio

import websockets

from unstep.contracts import AnomalyEvent, ProposedDirective, Slots, unwrap, wrap


def propose(event: AnomalyEvent) -> ProposedDirective:
    hint = event.local_hint
    if hint.kind == "restrictive" and hint.text:
        text = f"{event.callsign}, {hint.text}"
        runway = hint.text.split()[-1] if hint.text.split()[-1].isdigit() else None
        action = "hold short" if "hold short" in hint.text else hint.text
        confidence = "low"
        method = "mock: cockpit local hint only, no tower transcript"
    else:
        text = f"{event.callsign}, say again"
        runway, action, confidence = None, "say again", "low"
        method = "mock: no hint"
    return ProposedDirective(
        event_id=event.event_id,
        instruction_text=text,
        slots=Slots(callsign=event.callsign, action=action, runway=runway),
        confidence=confidence,
        confidence_method=method,
        rule_citation=None,
    )


async def run(url: str) -> None:
    async with websockets.connect(f"{url}/ws/agents") as ws:
        print("mock agents connected")
        async for raw in ws:
            env, msg = unwrap(raw)
            if msg is None:
                print(f"gateway error: {env.data.get('message')}")
            elif isinstance(msg, AnomalyEvent):
                await ws.send(wrap(propose(msg)))
                print(f"proposed directive for {msg.event_id}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://127.0.0.1:8765")
    asyncio.run(run(p.parse_args().url))
