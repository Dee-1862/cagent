"""Runs the watchers side by side. Each has its own queue and task, so a slow or failing watcher cannot hold up or
stop another. Everything they say goes to one `emit` callback (the room sends it to the console feed)."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from unstep.monitor.watchers import FlowWatcher, ReadbackWatcher, RunwayWatcher, TrackingWatcher, Watcher

log = logging.getLogger("unstep.monitor")

TICK_S = 1.0


class Team:
    def __init__(self, watchers: list[Watcher], emit: Callable[[dict], Awaitable[None]],
                 clock: Callable[[], int], tick_s: float = TICK_S):
        self.watchers, self.emit, self.clock, self.tick_s = watchers, emit, clock, tick_s
        self._queues: dict[str, asyncio.Queue] = {w.name: asyncio.Queue() for w in watchers}
        self._tasks: list[asyncio.Task] = []
        self.errors: dict[str, int] = {}

    def feed(self, msg) -> None:
        """A gateway message. Non-blocking; every watcher gets its own copy of the notice."""
        for q in self._queues.values():
            q.put_nowait(("message", msg, None))

    def note(self, kind: str, **data) -> None:
        """Something that is not a gateway message (a key going down or up)."""
        for q in self._queues.values():
            q.put_nowait(("note", kind, data))

    def open_items(self) -> list[dict]:
        out: list[dict] = []
        for w in self.watchers:
            out += w.open_items()
        return out

    async def _run(self, w: Watcher) -> None:
        q = self._queues[w.name]
        last_tick = self.clock()
        while True:
            try:
                kind, a, b = await asyncio.wait_for(q.get(), self.tick_s)
                rows = w.on_message(a, self.clock()) if kind == "message" else w.on_note(a, b, self.clock())
                if self.clock() - last_tick >= self.tick_s * 1000:  # steady traffic must not starve the timers
                    last_tick = self.clock()
                    rows = rows + w.tick(last_tick)
            except asyncio.TimeoutError:
                last_tick = self.clock()
                rows = w.tick(last_tick)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.errors[w.name] = self.errors.get(w.name, 0) + 1
                log.exception("watcher %s failed; the others carry on", w.name)
                continue
            for row in rows:
                try:
                    await self.emit(row)
                except Exception:
                    log.exception("could not post a row from %s", w.name)

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._run(w)) for w in self.watchers]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []


def default_team(emit, clock) -> Team:
    return Team([ReadbackWatcher(), RunwayWatcher(), TrackingWatcher(), FlowWatcher()], emit, clock)
