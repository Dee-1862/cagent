"""Cockpit memory (tasks A4, A5, A10): Moss when keys exist, a local fallback otherwise.

Indexes follow PRD 6.4:
- `airport-<ICAO>`: long-term, written once by pre-flight setup.
- `flight-<callsign>`: cockpit session, cockpit is the only writer.

Every index has one owner. `add_docs` from anyone else raises PermissionError,
because a Moss `push_index()` replaces the whole cloud index and a second writer
would silently overwrite the first (M-011).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

log = logging.getLogger("unstep.memory")


@dataclass
class Doc:
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


@dataclass
class QueryResult:
    docs: list[Doc]
    time_taken_ms: float
    backend: str


def airport_index(icao: str) -> str:
    return f"airport-{icao}"


def flight_index(callsign: str) -> str:
    return f"flight-{callsign}"


class Memory(Protocol):
    backend: str

    def register_index(self, index: str, owner: str) -> None: ...

    async def add_docs(self, index: str, docs: list[Doc], writer: str) -> int: ...

    async def query(
        self,
        index: str,
        text: str,
        top_k: int = 3,
        alpha: float = 0.8,
        filter: Optional[dict] = None,
        min_score: Optional[float] = None,
    ) -> QueryResult: ...

    async def fetch(self, index: str, filter: Optional[dict] = None, sort_by: Optional[str] = None,
                    ascending: bool = True, limit: Optional[int] = None,
                    group_by: Optional[tuple[str, str]] = None) -> QueryResult:
        """Docs matching `filter`, unranked (no query text), optionally ordered by a metadata field
        (numbers as numbers), cut to `limit`, or grouped `(parent_field, order_field)` into one doc per
        unit. Ordering and grouping are done here, not trusted to the backend (see `order_docs`)."""
        ...

    async def has_doc(self, index: str, doc_id: str) -> bool: ...


class _OwnedIndexes:
    def __init__(self) -> None:
        self.owners: dict[str, str] = {}

    def register_index(self, index: str, owner: str) -> None:
        current = self.owners.get(index)
        if current is not None and current != owner:
            raise PermissionError(f"{index} is already owned by {current}")
        self.owners[index] = owner

    def _check_writer(self, index: str, writer: str) -> None:
        owner = self.owners.get(index)
        if owner is None:
            raise KeyError(f"{index} is not registered; call register_index first")
        if writer != owner:
            raise PermissionError(f"{writer} may not write {index}; only {owner} writes it")


class _DiskSnapshots:
    """On-board snapshots of a plane's flight session (MM1): no cloud, written in the background.

    Subclasses provide `_write_snapshot(index)` and `_read_snapshot(index)`. A save is scheduled after a
    clearance, readback or advisory is added, at most once per `save_interval_s` per index, as a background
    task, so it is never on the radio path. A failed save only logs. `disk_dir` None turns it all off.
    """

    SAVED_TYPES = {"clearance", "readback", "advisory"}
    save_interval_s = 1.0

    def _init_disk(self, disk_dir: Optional[str | os.PathLike]) -> None:
        self.disk_dir: Optional[Path] = Path(disk_dir) if disk_dir else None
        self.last_load_ms: Optional[float] = None
        self.load_breakdown: dict = {}  # where the restore time went: opening the session and loading the files
        self.saves = 0  # snapshots written, for tests and the live check
        self._dirty: set[str] = set()
        self._save_tasks: dict[str, asyncio.Task] = {}
        self._last_save: dict[str, float] = {}
        self._write_locks: dict[str, asyncio.Lock] = {}  # one snapshot write per index at a time

    @staticmethod
    def _snapshotted(index: str) -> bool:
        """Only a plane's own flight session ("flight-<callsign>") is kept on board. The shared flight log
        ("flightlog-<frequency>") must not be: a local copy would make the session open without downloading the
        cloud index, so after a restart it would come up empty and the next push would replace the cloud flight log
        with only the new flights."""
        return index.startswith("flight-")

    def has_snapshot(self, index: str) -> bool:
        return (getattr(self, "disk_dir", None) is not None and self._snapshotted(index)
                and self._snapshot_exists(index))

    def _note_added(self, index: str, docs: list[Doc]) -> None:
        if getattr(self, "disk_dir", None) is None or not self._snapshotted(index):
            return
        if not any(str(d.metadata.get("type", "")) in self.SAVED_TYPES for d in docs):
            return
        self._dirty.add(index)
        task = self._save_tasks.get(index)
        if task is not None and not task.done():
            return  # the pending save will pick this up
        try:
            self._save_tasks[index] = asyncio.get_running_loop().create_task(self._save_loop(index))
        except RuntimeError:
            pass  # no event loop: nothing to save in the background

    async def _save_loop(self, index: str) -> None:
        while index in self._dirty:
            wait = self.save_interval_s - (time.monotonic() - self._last_save.get(index, float("-inf")))
            if wait > 0:
                await asyncio.sleep(wait)
            await self._save_now(index)

    async def _locked_write(self, index: str) -> None:
        locks = self.__dict__.setdefault("_write_locks", {})
        lock = locks.setdefault(index, asyncio.Lock())
        async with lock:
            await self._write_snapshot(index)

    async def _save_now(self, index: str) -> bool:
        self._dirty.discard(index)
        self._last_save[index] = time.monotonic()
        try:
            # Shielded and serialized: stopping a plane cancels the pending save, and a cancelled write must not
            # race the final one (the older snapshot could land last and the latest clearance would be lost).
            await asyncio.shield(self._locked_write(index))
            self.saves += 1
            return True
        except Exception:
            log.warning("could not save the memory snapshot of %s to disk; the radio is not affected", index,
                        exc_info=True)
            return False

    def forget_snapshot(self, index: str) -> None:
        """The flight is over and its seat goes to someone else: delete the on-board copy, so the next pilot who
        gets this callsign starts clean and never sees a previous pilot's clearances."""
        if getattr(self, "disk_dir", None) is None or not self._snapshotted(index):
            return
        task = self._save_tasks.pop(index, None)
        if task is not None and not task.done():
            task.cancel()
        self._dirty.discard(index)
        try:
            self._snapshot_remove(index)
        except OSError:
            log.warning("could not delete the memory snapshot of %s", index, exc_info=True)

    async def flush_saves(self) -> None:
        """Save anything still waiting, now (used when the plane stops)."""
        if getattr(self, "disk_dir", None) is None:
            return
        for task in list(self._save_tasks.values()):
            if not task.done():
                task.cancel()
        for index in list(self._dirty):
            await self._save_now(index)
        for lock in list(self.__dict__.get("_write_locks", {}).values()):
            async with lock:  # a write that was already running has finished before we return
                pass

    async def load_snapshot(self, index: str) -> Optional[int]:
        """Restore a plane's session from disk. Returns the document count, or None if there was nothing
        to load or the load failed (logged; the plane then starts from its seed as before)."""
        if not self.has_snapshot(index):
            return None
        started = time.perf_counter()
        try:
            count = await self._read_snapshot(index)
        except Exception:
            log.warning("could not load the memory snapshot of %s; starting fresh", index, exc_info=True)
            return None
        self.last_load_ms = round((time.perf_counter() - started) * 1000, 1)
        return count


# ---------------------------------------------------------------------------
# Local fallback


_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower().replace("-", ""))


def _num(v: Any) -> Any:
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def matches(metadata: dict, flt: Optional[dict]) -> bool:
    """Evaluate a Moss-style metadata filter: $eq, $ne, $in, $nin, $gt, $gte, $lt, $lte, $and, $or."""
    if not flt:
        return True
    for key, cond in flt.items():
        if key == "$and":
            if not all(matches(metadata, c) for c in cond):
                return False
            continue
        if key == "$or":
            if not any(matches(metadata, c) for c in cond):
                return False
            continue
        value = metadata.get(key)
        if not isinstance(cond, dict):
            cond = {"$eq": cond}
        for op, target in cond.items():
            if op == "$eq" and str(value) != str(target):
                return False
            if op == "$ne" and str(value) == str(target):
                return False
            if op == "$in" and str(value) not in {str(t) for t in target}:
                return False
            if op == "$nin" and str(value) in {str(t) for t in target}:
                return False
            if op in ("$gt", "$gte", "$lt", "$lte"):
                a, b = _num(value), _num(target)
                if value is None or not isinstance(a, float) or not isinstance(b, float):
                    return False
                if op == "$gt" and not a > b:
                    return False
                if op == "$gte" and not a >= b:
                    return False
                if op == "$lt" and not a < b:
                    return False
                if op == "$lte" and not a <= b:
                    return False
    return True


def order_docs(docs: list[Doc], sort_by: Optional[str], ascending: bool = True,
               limit: Optional[int] = None) -> list[Doc]:
    """Order by a metadata field, numbers before text and numerically (Moss stores metadata as strings, so
    "ts" values must be compared as numbers). Docs without the field go last. Applies `limit` after sorting.
    Moss's own `sort_by` is passed along as a hint but its behaviour on string metadata is unverified, so this
    function is the authority."""
    if sort_by:
        def key(d: Doc):
            v = _num(d.metadata.get(sort_by))
            return (0, v, "") if isinstance(v, float) else (1, 0.0, str(v)) if v is not None else (2, 0.0, "")

        present = [d for d in docs if d.metadata.get(sort_by) is not None]
        absent = [d for d in docs if d.metadata.get(sort_by) is None]
        docs = sorted(present, key=key, reverse=not ascending) + absent
    return docs[:limit] if limit is not None else docs


def group_docs(docs: list[Doc], parent_field: str, order_field: str) -> list[Doc]:
    """One doc per `parent_field` value (a transmission, an exchange): the members' texts in `order_field`
    order, joined with " | ", with the newest member's metadata plus `members`. Docs without the parent field
    stay as they are. Ordered newest unit first by `order_field`."""
    units: dict[str, list[Doc]] = {}
    single: list[Doc] = []
    for d in docs:
        parent = d.metadata.get(parent_field)
        (units.setdefault(str(parent), []) if parent not in (None, "") else single).append(d)
    out = []
    for parent, members in units.items():
        members = order_docs(members, order_field, ascending=True)
        newest = members[-1]
        out.append(Doc(id=f"{parent_field}:{parent}", text=" | ".join(m.text for m in members),
                       metadata={**newest.metadata, "members": [m.id for m in members]}))
    return order_docs(out + single, order_field, ascending=False)


def above_floor(docs: list[Doc], min_score: Optional[float]) -> list[Doc]:
    """Our own score floor. Moss documents `min_score` for loaded indexes, not for session queries, so the
    floor is applied here, to the scores the backend returns, for every backend."""
    return docs if not min_score else [d for d in docs if d.score >= min_score]


class LocalMemory(_OwnedIndexes, _DiskSnapshots):
    """Pure-Python stand-in for Moss, for offline runs and tests.

    Score = alpha * token overlap (stand-in for semantic) + (1 - alpha) * BM25
    (keyword), both scaled to 0..1, mirroring Moss's `alpha` (1.0 semantic, 0.0 keyword).
    """

    backend = "local"

    def __init__(self, disk_dir: Optional[str | os.PathLike] = None) -> None:
        super().__init__()
        self.indexes: dict[str, dict[str, Doc]] = {}
        self._init_disk(disk_dir)  # off unless asked: offline runs and tests stay in memory

    def _snapshot_path(self, index: str) -> Path:
        return self.disk_dir / f"{index}.json"

    def _snapshot_exists(self, index: str) -> bool:
        return self._snapshot_path(index).is_file()

    def _snapshot_remove(self, index: str) -> None:
        self._snapshot_path(index).unlink(missing_ok=True)

    async def _write_snapshot(self, index: str) -> None:
        docs = [{"id": d.id, "text": d.text, "metadata": d.metadata} for d in self.indexes.get(index, {}).values()]
        path = self._snapshot_path(index)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"index": index, "docs": docs}), encoding="utf-8")
            os.replace(tmp, path)  # a failed save leaves the last snapshot loadable

        await asyncio.to_thread(write)

    async def _read_snapshot(self, index: str) -> int:
        raw = json.loads(await asyncio.to_thread(self._snapshot_path(index).read_text, "utf-8"))
        self.indexes[index] = {d["id"]: Doc(id=d["id"], text=d["text"], metadata=dict(d.get("metadata") or {}))
                               for d in raw["docs"]}
        return len(self.indexes[index])

    async def open(self, *indexes: str) -> None:
        """Nothing to open locally; here so callers can treat both backends the same."""

    async def push(self, index: str, writer: str):
        """Offline stand-in for Moss Cloud: remembers what was pushed (tests check nothing else is)."""
        self._check_writer(index, writer)
        self.pushed = [*getattr(self, "pushed", []), index]
        return {"job": f"local-{len(self.pushed)}", "index": index}

    def drop(self, index: str, keep_snapshot: bool = False) -> None:
        self.indexes.pop(index, None)
        self.owners.pop(index, None)
        if not keep_snapshot:
            self.forget_snapshot(index)

    async def has_doc(self, index: str, doc_id: str) -> bool:
        return doc_id in self.indexes.get(index, {})

    async def fetch(self, index, filter=None, sort_by=None, ascending=True, limit=None, group_by=None) -> QueryResult:
        started = time.perf_counter()
        docs = [Doc(id=d.id, text=d.text, metadata=dict(d.metadata))
                for d in self.indexes.get(index, {}).values() if matches(d.metadata, filter)]
        docs = group_docs(docs, *group_by) if group_by else docs
        docs = order_docs(docs, sort_by, ascending, limit)
        return QueryResult(docs=docs, time_taken_ms=(time.perf_counter() - started) * 1000, backend=self.backend)

    async def add_docs(self, index: str, docs: list[Doc], writer: str) -> int:
        self._check_writer(index, writer)
        store = self.indexes.setdefault(index, {})
        for d in docs:
            store[d.id] = Doc(id=d.id, text=d.text, metadata=dict(d.metadata))
        self._note_added(index, docs)
        return len(docs)

    async def query(self, index, text, top_k=3, alpha=0.8, filter=None, min_score=None) -> QueryResult:
        started = time.perf_counter()
        docs = [d for d in self.indexes.get(index, {}).values() if matches(d.metadata, filter)]
        q = tokenize(text)
        scored: list[Doc] = []
        if docs and q:
            tokenized = [tokenize(d.text) for d in docs]
            avg_len = sum(len(t) for t in tokenized) / len(tokenized) or 1.0
            n = len(docs)
            bm25 = []
            for toks in tokenized:
                s = 0.0
                for term in set(q):
                    tf = toks.count(term)
                    if not tf:
                        continue
                    df = sum(1 for t in tokenized if term in t)
                    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                    s += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(toks) / avg_len))
                bm25.append(s)
            top = max(bm25) or 1.0
            qs = set(q)
            for d, toks, b in zip(docs, tokenized, bm25):
                overlap = len(qs & set(toks)) / len(qs | set(toks)) if toks else 0.0
                score = alpha * overlap + (1 - alpha) * (b / top)
                if score > 0:
                    scored.append(Doc(id=d.id, text=d.text, metadata=dict(d.metadata), score=round(score, 4)))
        scored.sort(key=lambda d: d.score, reverse=True)
        ms = (time.perf_counter() - started) * 1000
        return QueryResult(docs=above_floor(scored, min_score)[:top_k], time_taken_ms=ms, backend=self.backend)


# ---------------------------------------------------------------------------
# Moss


def _moss_value(v: Any) -> Any:
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v]
    return str(v)


def to_moss_filter(flt: Optional[dict]) -> Optional[dict]:
    """Translate our internal Mongo-style filter into the Moss SDK format.

    Internal: {"$and": [{"callsign": {"$eq": "N1"}}, {"ts": {"$gte": 5}}]}
    Moss:     {"$and": [{"field": "callsign", "condition": {"$eq": "N1"}},
                        {"field": "ts", "condition": {"$gte": "5"}}]}
    Moss metadata is a string map, so every value is stringified (as in add_docs).
    A bare value means $eq; several keys or several operators mean $and.
    """
    if not flt:
        return None
    clauses: list[dict] = []
    for key, cond in flt.items():
        if key in ("$and", "$or"):
            subs = [t for t in (to_moss_filter(c) for c in cond) if t]
            if subs:
                clauses.append({key: subs})
            continue
        if not isinstance(cond, dict):
            cond = {"$eq": cond}
        for op, target in cond.items():
            clauses.append({"field": key, "condition": {op: _moss_value(target)}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


class MossMemory(_OwnedIndexes, _DiskSnapshots):
    """Loaded airport knowledge and flight/frequency sessions, queried in-process.

    Airport indexes are read-only here. Only the ingestion script writes them.
    Session `push` hands off via Moss Cloud.

    Moss metadata is a string map, so values are stored as strings. Filters are
    translated by `to_moss_filter` into Moss's {"field", "condition"} form with
    string values; numeric filters ($gte on `ts`) compare those strings as numbers.
    """

    backend = "moss"

    def __init__(self, project_id: str, project_key: str, disk_dir: Optional[str | os.PathLike] = None) -> None:
        super().__init__()
        from moss import MossClient  # lazy: tests and offline runs don't need the SDK

        self.client = MossClient(project_id, project_key)
        self.sessions: dict[str, Any] = {}
        if disk_dir is None:  # on board by default; UNSTEP_MOSS_DISK=off turns it off, or names another folder
            env = os.getenv("UNSTEP_MOSS_DISK", "data/moss")
            disk_dir = None if env.strip().lower() in ("off", "0", "false", "") else env
        self._init_disk(disk_dir)

    def _snapshot_exists(self, index: str) -> bool:
        return (self.disk_dir / index).is_dir()

    def _snapshot_remove(self, index: str) -> None:
        import shutil

        shutil.rmtree(self.disk_dir / index, ignore_errors=True)

    async def _write_snapshot(self, index: str) -> None:
        # SessionIndex.save_to_disk(cache_path) writes <cache_path>/<session name>/ and, per the SDK, a failed
        # or interrupted save leaves the last snapshot loadable.
        session = self.sessions.get(index)
        if session is None:
            return
        await session.save_to_disk(str(self.disk_dir))

    async def _read_snapshot(self, index: str) -> int:
        # SessionIndex.load_from_disk(cache_path) replaces the session's documents and model. The session was
        # opened without downloading the cloud index (see _session), so nothing is fetched here.
        started = time.perf_counter()
        session = await self._session(index)  # a no-op if the plane already opened it at start
        opened = time.perf_counter()
        count = await session.load_from_disk(str(self.disk_dir))
        self.load_breakdown = {"open_ms": round((opened - started) * 1000, 2),
                               "load_from_disk_ms": round((time.perf_counter() - opened) * 1000, 2)}
        return count

    async def _session(self, index: str):
        if index.startswith("airport-"):
            raise PermissionError("Airport indexes are read-only; use pre-flight ingestion")
        # Opening a session checks credentials with Moss Cloud, so open before going offline.
        if index not in self.sessions:
            if self.has_snapshot(index):  # restore from disk, not from a cloud index of the same name
                self.sessions[index] = await self.client.session(index, auto_load_on_init=False)
            else:
                self.sessions[index] = await self.client.session(index)
        return self.sessions[index]

    async def open(self, *indexes: str) -> None:
        for index in indexes:
            if index.startswith("airport-"):
                await self.load_airport(index)
            else:
                await self._session(index)

    async def warm(self, index: str) -> float:
        """Run one tiny fetch and one tiny search on a session so the first real lookup in a live room is
        already warm (Rishit measured 783 ms for a first hint against 0.2 to 0.4 ms warm). Returns ms.
        Never raises: a cold session is slower, not broken."""
        started = time.perf_counter()
        try:
            from moss import GetDocumentsOptions, QueryOptions

            session = await self._session(index)
            await session.get_docs(GetDocumentsOptions())
            await session.query("warm up", QueryOptions(top_k=1))
        except Exception:
            log.warning("Moss warm-up for %s failed; the first lookup will be slower", index, exc_info=True)
        return (time.perf_counter() - started) * 1000

    async def load_airport(self, index: str) -> None:
        """Hydrate persistent knowledge without opening a writable session."""
        from unstep.config import moss_load_tries

        if not hasattr(self, "_loaded_airports"):
            self._loaded_airports: set[str] = set()
            self._airport_locks: dict[str, asyncio.Lock] = {}
        # Planes start together on one shared client: one load per airport, the others wait for it.
        async with self._airport_locks.setdefault(index, asyncio.Lock()):
            if index in self._loaded_airports:
                return
            tries = moss_load_tries()
            for attempt in range(1, tries + 1):
                try:
                    await self.client.load_index(index)
                    break
                except Exception as exc:
                    # Moss: "The index changed while the operation ran. Retry the operation."
                    if "changed while the operation ran" not in str(exc) or attempt == tries:
                        raise
                    log.warning("Moss reported %s changed during load; retry %d of %d", index, attempt, tries - 1)
                    await asyncio.sleep(0.3 * attempt)
            self._loaded_airports.add(index)

    async def add_docs(self, index: str, docs: list[Doc], writer: str) -> int:
        from moss import DocumentInfo

        self._check_writer(index, writer)
        session = await self._session(index)
        infos = [
            DocumentInfo(id=d.id, text=d.text, metadata={k: str(v) for k, v in d.metadata.items()})
            for d in docs
        ]
        added, updated = await session.add_docs(infos)
        self._note_added(index, docs)
        return added + updated

    async def has_doc(self, index: str, doc_id: str) -> bool:
        from moss import GetDocumentsOptions

        session = await self._session(index)
        return bool(await session.get_docs(GetDocumentsOptions(doc_ids=[doc_id])))

    async def fetch(self, index, filter=None, sort_by=None, ascending=True, limit=None, group_by=None) -> QueryResult:
        from moss import GetDocumentsOptions

        session = await self._session(index)
        started = time.perf_counter()
        flt = to_moss_filter(filter)
        try:  # ask Moss to sort too (documented in the signature); its result is not trusted, see order_docs
            infos = await session.get_docs(GetDocumentsOptions(filter=flt, sort_by=sort_by, ascending=ascending)
                                           if sort_by else GetDocumentsOptions(filter=flt))
        except Exception:
            log.warning("Moss get_docs with sort_by failed; fetching unsorted", exc_info=True)
            infos = await session.get_docs(GetDocumentsOptions(filter=flt))
        docs = [Doc(id=d.id, text=d.text, metadata=dict(d.metadata or {})) for d in infos]
        # Belt and braces: re-check locally so a filter the SDK ignores can't widen results.
        docs = [d for d in docs if matches(d.metadata, filter)]
        # Grouping is done here too: the shape of Moss's own ParentGrouping result is unverified.
        docs = group_docs(docs, *group_by) if group_by else docs
        docs = order_docs(docs, sort_by, ascending, limit)
        return QueryResult(docs=docs, time_taken_ms=(time.perf_counter() - started) * 1000, backend=self.backend)

    async def query(self, index, text, top_k=3, alpha=0.8, filter=None, min_score=None) -> QueryResult:
        from moss import QueryOptions

        started = time.perf_counter()
        options = QueryOptions(top_k=top_k, alpha=alpha, filter=to_moss_filter(filter))
        if index.startswith("airport-"):
            await self.load_airport(index)
            result = await self.client.query(index, text, options)
        else:
            session = await self._session(index)
            result = await session.query(text, options)
        wall_ms = (time.perf_counter() - started) * 1000
        docs = [Doc(id=d.id, text=d.text, metadata=dict(d.metadata or {}), score=d.score) for d in result.docs]
        docs = above_floor(docs, min_score)  # our floor: session queries don't document min_score
        return QueryResult(
            docs=docs,
            time_taken_ms=result.time_taken_ms if result.time_taken_ms is not None else wall_ms,
            backend=self.backend,
        )

    async def push(self, index: str, writer: str):
        """Hand off a session to Moss Cloud (end of event or flight). Owner only. Returns what the SDK returns
        (the push job, if any), so callers can log it."""
        self._check_writer(index, writer)
        return await (await self._session(index)).push_index()

    def drop(self, index: str, keep_snapshot: bool = False) -> None:
        """Forget a session in this client (its memory is freed); the owner can register it again later. The
        on-board snapshot goes too unless the hub is only stopping (`keep_snapshot`): a seat given to a new pilot
        must not inherit the last pilot's clearances."""
        self.sessions.pop(index, None)
        self.owners.pop(index, None)
        if not keep_snapshot:
            self.forget_snapshot(index)


def create_memory() -> Memory:
    project_id = os.getenv("MOSS_PROJECT_ID")
    project_key = os.getenv("MOSS_PROJECT_KEY")
    if project_id and project_key:
        try:
            mem = MossMemory(project_id, project_key)
            log.info("memory backend: Moss (project %s)", project_id)
            return mem
        except ImportError:
            log.warning("MOSS keys set but the moss package is missing; falling back to local memory")
        except Exception:  # a bad key format or SDK error at construction must not stop the room
            log.exception("Moss client could not be created; falling back to local memory")
    log.info("memory backend: local fallback (no MOSS_PROJECT_ID/MOSS_PROJECT_KEY)")
    return LocalMemory()
