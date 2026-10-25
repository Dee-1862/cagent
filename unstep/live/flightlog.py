"""Save each plane's memory to Moss Cloud when its flight ends, without pushing per-aircraft sessions.

The agreed rule (R3/R4) is that per-aircraft sessions are never pushed: the plan's cloud index limit,
and `push_index()` replaces an index rather than merging. So there is one shared flight log session,
`flightlog-<frequency>`, written only by "archive" and the only cloud index we push besides the airport
index. When a flight ends (a walk-up seat is freed, the presenter resets the room, or the hub stops),
the plane's session docs are copied into the flight log with {callsign, flight_id, ended_at, kind},
the flight log is pushed once in the background (never on the radio path; a failed push stays local
and is retried at the next end), and the plane's session is dropped from the shared client.

Note: a push replaces the cloud index with this session's contents. The session holds every flight
archived since the hub started, so a hub restart starts a new log (earlier runs' flights are then
replaced on the next push). Loading the old index back first depends on the Moss SDK (check).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from unstep.cockpit.memory import Doc

log = logging.getLogger("unstep.flightlog")
WRITER = "archive"


def flight_log_index(frequency: str) -> str:
    return f"flightlog-{frequency}"


class FlightLog:
    def __init__(self, memory, frequency: str):
        self.memory, self.index = memory, flight_log_index(frequency)
        self.memory.register_index(self.index, WRITER)
        self.flights: list[dict] = []
        self.docs = 0
        self.push_pending = False
        self.pushes: list[dict] = []
        self._lock = asyncio.Lock()
        self.frequency = frequency
        self.summaries = None  # unstep.ground.flights.FlightSummaries: a one-line record per flight in Elastic

    async def archive(self, callsign: str, source_memory, flight_index: str, reason: str) -> dict | None:
        """Copy one plane's session into the flight log. Returns the flight record, or None if it was empty."""
        if not flight_index:
            return None
        try:
            res = await source_memory.fetch(flight_index)
        except Exception:
            log.exception("could not read %s to archive it", flight_index)
            return None
        flight_id = f"{callsign}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:4]}"
        ended = int(time.time() * 1000)
        docs = [Doc(id=f"{flight_id}/{d.id}", text=d.text,
                    metadata={**{k: v for k, v in d.metadata.items() if k not in ("callsign",)}, "callsign": callsign,
                              "flight_id": flight_id, "ended_at": ended, "kind": d.metadata.get("type", "record"),
                              "reason": reason})
                for d in res.docs]
        if docs:
            try:
                await self.memory.add_docs(self.index, docs, writer=WRITER)
            except Exception:
                # Moss unreachable: keep the log locally from now on rather than lose the flight
                log.exception("flight log write failed; keeping the flight log in local memory")
                from unstep.cockpit.memory import LocalMemory

                self.memory = LocalMemory()
                self.memory.register_index(self.index, WRITER)
                await self.memory.add_docs(self.index, docs, writer=WRITER)
        record = {"callsign": callsign, "flight_id": flight_id, "ended_at": ended, "docs": len(docs), "reason": reason}
        if self.summaries is not None:  # counts only, off the landing path: a slow Elastic never holds a seat
            from unstep.ground.flights import summarize

            summary = summarize(callsign, self.frequency, flight_id, reason, ended, res.docs)
            task = asyncio.get_running_loop().create_task(self.summaries.record(summary))
            self._summary_tasks = getattr(self, "_summary_tasks", set())
            self._summary_tasks.add(task)
            task.add_done_callback(self._summary_tasks.discard)
        self.flights.append(record)
        self.docs += len(docs)
        self.push_pending = True
        drop = getattr(source_memory, "drop", None)
        if drop is not None:  # free the plane's session in the shared client
            if reason == "hub stopped":  # the plane is still flying: keep its on-board copy for the restart
                drop(flight_index, keep_snapshot=True)
            else:  # the seat is going to someone else: its on-board copy goes too
                drop(flight_index)
        return record

    async def push(self) -> dict | None:
        """Push the flight log once (the only per-session push we ever make). Failure keeps it for next time."""
        async with self._lock:
            if not self.push_pending:
                return None
            started = time.perf_counter()
            try:
                job = await self.memory.push(self.index, WRITER)
            except Exception as exc:
                reason = " ".join(str(exc).split())[:160]
                log.warning("flight log push failed (%s: %s); kept local, retried at the next flight end",
                            type(exc).__name__, reason)
                self.pushes.append({"ok": False, "error": type(exc).__name__, "reason": reason,
                                    "at": int(time.time() * 1000)})
                return None
            self.push_pending = False
            entry = {"ok": True, "job": str(job) if job is not None else None,
                     "job_id": getattr(job, "job_id", None), "flights": len(self.flights),
                     "ms": round((time.perf_counter() - started) * 1000, 1), "at": int(time.time() * 1000)}
            self.pushes.append(entry)
            log.info("flight log %s pushed: %s", self.index, entry)
            return entry

    async def search(self, text: str, callsign: str | None = None, since_ms: int | None = None, top_k: int = 5):
        clauses = []
        if callsign:
            clauses.append({"callsign": {"$eq": callsign}})
        if since_ms:
            clauses.append({"ended_at": {"$gte": since_ms}})
        flt = {"$and": clauses} if len(clauses) > 1 else (clauses[0] if clauses else None)
        res = await self.memory.query(self.index, text or "clearance", top_k=top_k, filter=flt)
        return {"ms": round(res.time_taken_ms, 3), "backend": getattr(self.memory, "backend", "?"),
                "docs": [{"id": d.id, "text": d.text, "callsign": d.metadata.get("callsign"),
                          "flight_id": d.metadata.get("flight_id"), "score": d.score} for d in res.docs]}

    def status(self) -> dict:
        last = next((p for p in reversed(self.pushes) if p["ok"]), None)
        backend = getattr(self.memory, "backend", "local")
        where = "Moss Cloud" if backend == "moss" else "the local flight log (offline)"
        failed = self.pushes[-1] if self.pushes and not self.pushes[-1]["ok"] else None
        text = f"Flight log: {len(self.flights) if last else 0} flights saved to {where}"
        if failed:  # say why the cloud copy is behind, e.g. a project usage limit, instead of looking healthy
            text += f" (last push failed: {failed.get('reason') or failed['error']})"
        return {"type": "flightlog", "index": self.index, "backend": backend, "flights": len(self.flights),
                "docs": self.docs, "pushed": bool(last), "push_pending": self.push_pending,
                "last_push": last, "last_error": failed, "text": text}
