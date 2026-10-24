"""Cockpit memory (tasks A4, A5, A10): Moss when keys exist, a local fallback otherwise.

Indexes follow PRD 6.4:
- `airport-<ICAO>`: long-term, written once by pre-flight setup.
- `flight-<callsign>`: cockpit session, cockpit is the only writer.

Every index has one owner. `add_docs` from anyone else raises PermissionError,
because a Moss `push_index()` replaces the whole cloud index and a second writer
would silently overwrite the first (M-011).
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
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


class LocalMemory(_OwnedIndexes):
    """Pure-Python stand-in for Moss, for offline runs and tests.

    Score = alpha * token overlap (stand-in for semantic) + (1 - alpha) * BM25
    (keyword), both scaled to 0..1, mirroring Moss's `alpha` (1.0 semantic, 0.0 keyword).
    """

    backend = "local"

    def __init__(self) -> None:
        super().__init__()
        self.indexes: dict[str, dict[str, Doc]] = {}

    async def open(self, *indexes: str) -> None:
        """Nothing to open locally; here so callers can treat both backends the same."""

    async def push(self, index: str, writer: str):
        """Offline stand-in for Moss Cloud: remembers what was pushed (tests check nothing else is)."""
        self._check_writer(index, writer)
        self.pushed = [*getattr(self, "pushed", []), index]
        return {"job": f"local-{len(self.pushed)}", "index": index}

    def drop(self, index: str) -> None:
        self.indexes.pop(index, None)
        self.owners.pop(index, None)

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


class MossMemory(_OwnedIndexes):
    """Loaded airport knowledge and flight/frequency sessions, queried in-process.

    Airport indexes are read-only here. Only the ingestion script writes them.
    Session `push` hands off via Moss Cloud.

    Moss metadata is a string map, so values are stored as strings. Filters are
    translated by `to_moss_filter` into Moss's {"field", "condition"} form with
    string values; numeric filters ($gte on `ts`) compare those strings as numbers.
    """

    backend = "moss"

    def __init__(self, project_id: str, project_key: str) -> None:
        super().__init__()
        from moss import MossClient  # lazy: tests and offline runs don't need the SDK

        self.client = MossClient(project_id, project_key)
        self.sessions: dict[str, Any] = {}

    async def _session(self, index: str):
        if index.startswith("airport-"):
            raise PermissionError("Airport indexes are read-only; use pre-flight ingestion")
        # Opening a session checks credentials with Moss Cloud, so open before going offline.
        if index not in self.sessions:
            self.sessions[index] = await self.client.session(index)
        return self.sessions[index]

    async def open(self, *indexes: str) -> None:
        for index in indexes:
            if index.startswith("airport-"):
                await self.load_airport(index)
            else:
                await self._session(index)

    async def load_airport(self, index: str) -> None:
        """Hydrate persistent knowledge without opening a writable session."""
        if not hasattr(self, "_loaded_airports"):
            self._loaded_airports: set[str] = set()
        if index not in self._loaded_airports:
            await self.client.load_index(index)
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

    def drop(self, index: str) -> None:
        """Forget a session in this client (its memory is freed); the owner can register it again later."""
        self.sessions.pop(index, None)
        self.owners.pop(index, None)


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
    log.info("memory backend: local fallback (no MOSS_PROJECT_ID/MOSS_PROJECT_KEY)")
    return LocalMemory()
