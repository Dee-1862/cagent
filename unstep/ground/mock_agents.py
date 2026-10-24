"""Mock ground agents for M2. Dev B replaces this with the Elastic Workflow (task B5).

Turns each AnomalyEvent into a ProposedDirective from the latest overlapping
tower transcript, falling back to the local hint with low confidence.

Run: python -m unstep.ground.mock_agents
"""

import argparse
import asyncio

import websockets

from unstep.config import gateway_url, ws_url
from unstep.contracts import AnomalyEvent, ProposedDirective, Slots, TowerTranscript, unwrap, wrap

from unstep.cockpit.phraseology import parse_instruction
from unstep.ground.blocked import blocked_words


def propose(event: AnomalyEvent, transcript: TowerTranscript | None = None) -> ProposedDirective:
    hint = event.local_hint
    if (transcript is not None and transcript.frequency == event.frequency
            and transcript.ptt_start < event.squelch_close and transcript.ptt_end > event.squelch_open):
        slots = parse_instruction(transcript.text) or Slots(callsign=event.callsign, action=transcript.text)
        slots = slots.model_copy(update={"callsign": event.callsign})
        hint_slots = parse_instruction(hint.text or "")
        agrees = (hint.kind == "restrictive" and hint_slots is not None
                  and (hint_slots.action, hint_slots.runway) == (slots.action, slots.runway))
        return ProposedDirective(
            event_id=event.event_id, transcript_id=transcript.transcript_id,
            instruction_text=transcript.text, slots=slots,
            blocked_words=blocked_words(transcript, event.overlap_start, event.overlap_end),
            confidence="high" if agrees else "medium",
            confidence_method="tower transcript match + local hint agrees" if agrees else "tower transcript match",
        )
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
    transcripts: dict[str, TowerTranscript] = {}
    async with websockets.connect(ws_url("agents", url)) as ws:
        print("mock agents connected")
        async for raw in ws:
            env, msg = unwrap(raw)
            if msg is None:
                print(f"gateway error: {env.data.get('message')}")
            elif isinstance(msg, TowerTranscript):
                transcripts[msg.frequency] = msg
            elif isinstance(msg, AnomalyEvent):
                await ws.send(wrap(propose(msg, transcripts.get(msg.frequency))))
                print(f"proposed directive for {msg.event_id}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=None, help="gateway URL (default: UNSTEP_GATEWAY_URL)")
    asyncio.run(run(p.parse_args().url or gateway_url()))
