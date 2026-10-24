"""Plays the demo flow against a running gateway with fake clients (M1 for Dev B).

Every role is a mock: tower, cockpit, a stand-in for the Elastic agents, the
controller's voice loop and the dashboard. Dev A replaces the mock cockpit with
the real one for M2.

    python -m ground.gateway            # terminal 1
    python -m ground.mocks.demo_flow    # terminal 2
"""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

import websockets

EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"


def example(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


class Client:
    def __init__(self, url: str, role: str) -> None:
        self.url, self.role = f"{url}/ws/{role}", role

    async def __aenter__(self) -> "Client":
        self.socket = await websockets.connect(self.url)
        welcome = await self.receive()
        assert welcome["type"] == "Welcome", welcome
        return self

    async def __aexit__(self, *exc) -> None:
        await self.socket.close()

    async def send(self, type_name: str, payload: dict | None = None) -> None:
        payload = payload if payload is not None else example(type_name)
        await self.socket.send(json.dumps({"type": type_name, "payload": payload}))
        print(f"  {self.role:>16} -> {type_name}")

    async def receive(self, expected: str | None = None) -> dict:
        message = json.loads(await asyncio.wait_for(self.socket.recv(), timeout=5))
        if message["type"] == "Error":
            raise RuntimeError(f"{self.role} got an error: {message['payload']['reason']}")
        if expected and message["type"] != expected:
            raise RuntimeError(f"{self.role} expected {expected}, got {message['type']}")
        if expected:
            print(f"  {self.role:>16} <- {expected}")
        return message


async def run(url: str) -> None:
    # A fresh event id per run, so the flow can be repeated on one gateway.
    event_id = f"evt-{uuid.uuid4().hex[:8]}"

    def for_event(name: str) -> dict:
        return {**example(name), "event_id": event_id}

    async with (
        Client(url, "tower") as tower,
        Client(url, "cockpit") as cockpit,
        Client(url, "agents") as agents,
        Client(url, "controller_voice") as voice,
        Client(url, "dashboard") as dashboard,
    ):
        print("1. Tower call is transcribed")
        await tower.send("TowerTranscript")
        await agents.receive("TowerTranscript")
        await dashboard.receive("TowerTranscript")

        print("2. Cockpit reports the stepped-on call")
        await cockpit.send("AnomalyEvent", for_event("AnomalyEvent"))
        await agents.receive("AnomalyEvent")
        await dashboard.receive("AnomalyEvent")

        print("3. Agents propose a directive")
        await agents.send("ProposedDirective", for_event("ProposedDirective"))
        await voice.receive("ProposedDirective")
        await dashboard.receive("ProposedDirective")

        print("4. Controller says 'Approve'")
        await voice.send("VoiceApproval", for_event("VoiceApproval"))
        await dashboard.receive("VoiceApproval")
        approved = await cockpit.receive("ApprovedDirective")
        await voice.receive("ApprovedDirective")
        await dashboard.receive("ApprovedDirective")

        print("5. Pilot reads back wrong, then right")
        wrong = for_event("ReadbackResult")
        await cockpit.send("ReadbackResult", wrong)
        await agents.receive("ReadbackResult")
        await dashboard.receive("ReadbackResult")
        right = {**wrong, "readback_text": "Hold short Runway 33, Cessna 1-2-3",
                 "slots": approved["payload"]["slots"], "match": True, "attempt": 2}
        await cockpit.send("ReadbackResult", right)
        await agents.receive("ReadbackResult")
        await dashboard.receive("ReadbackResult")

        print("6. Pilot asks for the last clearance (stored, not relayed)")
        await cockpit.send("PilotQuery")

        print(f"Done: {event_id} '{approved['payload']['instruction_text']}' approved via "
              f"{approved['payload']['approved_via']} and delivered to the cockpit.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="ws://localhost:8765")
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()
    try:
        for _ in range(args.runs):
            asyncio.run(run(args.url))
    except (OSError, RuntimeError, TimeoutError) as e:
        sys.exit(f"demo flow failed: {e}")


if __name__ == "__main__":
    main()
