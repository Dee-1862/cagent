"""Frequency Monitor (task A5). Runs on the ground, owned by Dev A.

Subscribes to TowerTranscript, AnomalyEvent and ReadbackResult on the gateway
(role `monitor`). It is the only writer of the Moss index `freq-<frequency>`
(PRD 6.4) and raises advisory `Insight`s for the controller dashboard, for
example "N123AB has had 2 blocked calls in 5 minutes." Insights never go to
the cockpit (FR-11); the gateway routes them to the dashboard only.

Rules use the timestamps carried by the messages (one clock, FR-17), never the
wall clock, so they replay deterministically:
- AnomalyEvent: `squelch_open`
- TowerTranscript: `ptt_start`
- ReadbackResult: has no timestamp of its own, so the envelope `ts` the gateway stamped.

Run: python -m unstep.cockpit.monitor --url ws://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel

from unstep.clock import now_ms
from unstep.contracts import AnomalyEvent, Insight, ReadbackResult, TowerTranscript, unwrap, wrap
from unstep.cockpit.memory import Doc, Memory, create_memory

log = logging.getLogger("unstep.monitor")

WRITER = "frequency-monitor"

MIN = 60_000
BLOCKED_WINDOW_MS = 5 * MIN
BLOCKED_PER_CALLSIGN = 2
READBACK_WINDOW_MS = 10 * MIN
READBACK_ERRORS = 2
CONGESTION_WINDOW_MS = 5 * MIN
CONGESTION_BLOCKED = 3


def freq_index(frequency: str) -> str:
    return f"freq-{frequency}"


def _minutes(ms: int) -> str:
    m = ms // MIN
    return f"{m} minute" if m == 1 else f"{m} minutes"


@dataclass
class TranscriptMatch:
    doc: Optional[Doc]
    moss_ms: float
    backend: str


class Rules:
    """Pure insight logic: no IO, timestamps come from the caller."""

    def __init__(self) -> None:
        self.blocked_by_callsign: dict[str, deque[int]] = defaultdict(deque)
        self.blocked_by_freq: dict[str, deque[int]] = defaultdict(deque)
        self.readback_errors_by_freq: dict[str, deque[int]] = defaultdict(deque)
        self.events: dict[str, tuple[str, str]] = {}  # event_id -> (callsign, frequency)
        self.last_fired: dict[tuple[str, str], int] = {}
        self._seq = 0

    @staticmethod
    def _push(window: deque[int], ts: int, span_ms: int) -> int:
        window.append(ts)
        while window and window[0] < ts - span_ms:
            window.popleft()
        return len(window)

    def _fire(self, kind: str, key: str, ts: int, span_ms: int, **fields) -> Optional[Insight]:
        last = self.last_fired.get((kind, key))
        if last is not None and ts - last < span_ms:
            return None  # same insight for the same key already raised inside its window
        self.last_fired[(kind, key)] = ts
        self._seq += 1
        return Insight(insight_id=f"ins-{kind}-{key}-{ts}-{self._seq}", kind=kind, ts=ts, **fields)

    def on_anomaly(self, event: AnomalyEvent) -> list[Insight]:
        if event.event_id in self.events:
            return []  # duplicate delivery; count each blocked call once
        self.events[event.event_id] = (event.callsign, event.frequency)
        ts = event.squelch_open
        out: list[Insight] = []

        n = self._push(self.blocked_by_callsign[event.callsign], ts, BLOCKED_WINDOW_MS)
        if n >= BLOCKED_PER_CALLSIGN:
            ins = self._fire(
                "repeated_blocked_calls", event.callsign, ts, BLOCKED_WINDOW_MS,
                frequency=event.frequency, callsign=event.callsign,
                text=f"{event.callsign} has had {n} blocked calls in {_minutes(BLOCKED_WINDOW_MS)}.",
            )
            if ins:
                out.append(ins)

        n = self._push(self.blocked_by_freq[event.frequency], ts, CONGESTION_WINDOW_MS)
        if n >= CONGESTION_BLOCKED:
            ins = self._fire(
                "frequency_congestion", event.frequency, ts, CONGESTION_WINDOW_MS,
                frequency=event.frequency,
                text=f"{event.frequency} has had {n} blocked calls in {_minutes(CONGESTION_WINDOW_MS)}.",
            )
            if ins:
                out.append(ins)
        return out

    def on_readback(self, result: ReadbackResult, ts: int) -> list[Insight]:
        if result.match:
            return []
        known = self.events.get(result.event_id)
        if known is None:
            log.warning("readback for unknown event %s, frequency unknown", result.event_id)
            return []
        callsign, frequency = known
        n = self._push(self.readback_errors_by_freq[frequency], ts, READBACK_WINDOW_MS)
        if n < READBACK_ERRORS:
            return []
        ins = self._fire(
            "readback_errors_rising", frequency, ts, READBACK_WINDOW_MS,
            frequency=frequency, callsign=callsign,
            text=f"{n} readback errors on {frequency} in {_minutes(READBACK_WINDOW_MS)}.",
        )
        return [ins] if ins else []


class FrequencyMonitor:
    """Rules plus the Moss frequency session. The only writer of `freq-<frequency>`."""

    def __init__(self, memory: Memory, writer: str = WRITER) -> None:
        self.memory = memory
        self.writer = writer
        self.rules = Rules()
        self.registered: set[str] = set()
        self.callsign_freq: dict[str, str] = {}

    def own(self, frequency: str) -> str:
        index = freq_index(frequency)
        if index not in self.registered:
            self.memory.register_index(index, self.writer)
            self.registered.add(index)
        return index

    async def on_transcript(self, tx: TowerTranscript) -> None:
        index = self.own(tx.frequency)
        meta = {"frequency": tx.frequency, "ts": tx.ptt_start}
        if tx.callsign:
            meta["callsign"] = tx.callsign
            self.callsign_freq[tx.callsign] = tx.frequency
        await self.memory.add_docs(index, [Doc(id=tx.transcript_id, text=tx.text, metadata=meta)], self.writer)

    def on_anomaly(self, event: AnomalyEvent) -> list[Insight]:
        self.callsign_freq.setdefault(event.callsign, event.frequency)
        return self.rules.on_anomaly(event)

    def on_readback(self, result: ReadbackResult, ts: int) -> list[Insight]:
        return self.rules.on_readback(result, ts)

    async def handle(self, msg: BaseModel, env_ts: Optional[int] = None) -> list[Insight]:
        if isinstance(msg, TowerTranscript):
            await self.on_transcript(msg)
            return []
        if isinstance(msg, AnomalyEvent):
            return self.on_anomaly(msg)
        if isinstance(msg, ReadbackResult):
            return self.on_readback(msg, env_ts if env_ts is not None else now_ms())
        return []

    async def match_transcript(
        self,
        callsign: str,
        around_ts: int,
        text: Optional[str] = None,
        frequency: Optional[str] = None,
        window_ms: int = 30_000,
    ) -> TranscriptMatch:
        """Find the tower transcript to `callsign` near `around_ts` in `freq-<frequency>`.

        `text` (e.g. the cockpit's heard_text) steers ranking; defaults to the callsign.
        """
        frequency = frequency or self.callsign_freq.get(callsign)
        if frequency is None:
            return TranscriptMatch(doc=None, moss_ms=0.0, backend=self.memory.backend)
        flt = {"$and": [
            {"callsign": {"$eq": callsign}},
            {"ts": {"$gte": around_ts - window_ms}},
            {"ts": {"$lte": around_ts + window_ms}},
        ]}
        res = await self.memory.query(freq_index(frequency), text or callsign, top_k=1, filter=flt)
        return TranscriptMatch(doc=res.docs[0] if res.docs else None, moss_ms=res.time_taken_ms, backend=res.backend)


async def run(url: str) -> None:
    import websockets

    monitor = FrequencyMonitor(create_memory())
    async with websockets.connect(f"{url}/ws/monitor") as ws:
        print("frequency monitor connected")
        async for raw in ws:
            try:
                env, msg = unwrap(raw)
            except ValueError as e:
                print(f"bad message: {e}")
                continue
            if msg is None:
                print(f"gateway error: {env.data.get('message')}")
                continue
            try:
                insights = await monitor.handle(msg, env.ts)
            except Exception:
                log.exception("monitor failed on %s", env.type)
                continue
            for ins in insights:
                await ws.send(wrap(ins))
                print(f"insight: {ins.text}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from unstep.config import load_env

    load_env()  # Moss keys come from .env
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://127.0.0.1:8765")
    asyncio.run(run(p.parse_args().url))
