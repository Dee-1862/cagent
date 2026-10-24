"""WebSocket gateway (task B1): relays every contract between roles and stores it.

Clients connect to /ws/{role}. Each role may only send the message types in
ALLOWED_SENDERS, and each type goes to the roles in ROUTES. The gateway owns
directive decisions: a proposal is decided once, by the controller's voice loop
or a dashboard click, and the gateway builds the ApprovedDirective from the
stored proposal, never from client text. Undecided proposals expire after
PENDING_TTL_S and are then refused (PRD voice approval rules: nothing is sent).

Run: uvicorn unstep.gateway.server:app --port 8765
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from unstep.clock import now_ms
from unstep.config import gateway_token, pending_ttl_s
from unstep.contracts import (
    ApprovedDirective,
    ProposedDirective,
    RejectedDirective,
    VoiceApproval,
    unwrap,
    wrap,
)
from unstep.gateway.sink import sink_from_env

log = logging.getLogger("unstep.gateway")

ROOT = Path(__file__).resolve().parents[2]

ROUTES: dict[str, set[str]] = {
    "TowerTranscript": {"agents", "monitor", "dashboard"},
    "AnomalyEvent": {"agents", "monitor", "dashboard"},
    "ProposedDirective": {"dashboard", "controller_voice"},
    "VoiceApproval": {"dashboard"},
    "ApprovedDirective": {"cockpit", "dashboard", "controller_voice", "agents"},
    "RejectedDirective": {"cockpit", "dashboard", "controller_voice", "agents"},
    "ReadbackResult": {"agents", "monitor", "dashboard"},
    "PilotQuery": {"dashboard"},
    "Insight": {"dashboard"},
    "AuditRecord": set(),
}

ALLOWED_SENDERS: dict[str, set[str]] = {
    "observer": set(),
    "cockpit": {"AnomalyEvent", "ReadbackResult", "PilotQuery", "AuditRecord"},
    "tower": {"TowerTranscript", "AuditRecord"},
    "agents": {"ProposedDirective", "AuditRecord"},
    # Click decisions. The gateway rebuilds them from the stored proposal.
    "dashboard": {"ApprovedDirective", "RejectedDirective", "AuditRecord"},
    # The voice loop repeats back "Approved, sending to ..." before it sends "approve" (task B10).
    "controller_voice": {"VoiceApproval", "AuditRecord"},
    "monitor": {"Insight", "AuditRecord"},
}
ROLES = set(ALLOWED_SENDERS)
# "testclient" is the host Starlette's TestClient reports; no real peer can have it.
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}

PENDING_TTL_S = pending_ttl_s()


class Gateway:
    def __init__(self, sink, pending_ttl_s: float = PENDING_TTL_S):
        self.sink = sink
        self.pending_ttl_ms = pending_ttl_s * 1000
        self.clients: dict[str, set[WebSocket]] = defaultdict(set)
        # Proposals waiting for a human decision: event_id -> (proposal, received_ms).
        self.pending: dict[str, tuple[ProposedDirective, int]] = {}
        self.decided: set[str] = set()
        self.history: deque[str] = deque(maxlen=200)
        self.observer_lock = asyncio.Lock()

    def store(self, record: dict) -> None:
        try:
            self.sink.write(record)
        except Exception:
            log.exception("sink write failed")

    async def broadcast(self, raw: str, msg_type: str) -> None:
        async with self.observer_lock:
            self.history.append(raw)
            for ws in list(self.clients["observer"]):
                try:
                    await ws.send_text(raw)
                except Exception:
                    self.clients["observer"].discard(ws)
        for role in ROUTES.get(msg_type, set()):
            for ws in list(self.clients[role]):
                try:
                    await ws.send_text(raw)
                except Exception:
                    self.clients[role].discard(ws)

    async def emit(self, msg) -> None:
        raw = wrap(msg)
        self.store({"source": "gateway", **json.loads(raw)})
        await self.broadcast(raw, type(msg).__name__)

    async def error(self, ws: WebSocket, message: str) -> None:
        await ws.send_json({"type": "Error", "ts": now_ms(), "data": {"message": message}})

    def take_pending(self, event_id: str) -> ProposedDirective | None:
        """Remove and return a live proposal. Expired proposals are dropped, never sent."""
        entry = self.pending.pop(event_id, None)
        if entry is None:
            return None
        proposal, received = entry
        self.decided.add(event_id)
        if now_ms() - received > self.pending_ttl_ms:
            log.warning("%s expired before a decision, nothing sent", event_id)
            return None
        return proposal

    async def handle(self, role: str, raw: str, ws: WebSocket) -> None:
        try:
            env, msg = unwrap(raw)
        except (ValidationError, ValueError) as e:
            await self.error(ws, str(e)[:500])
            return
        if env.type not in ALLOWED_SENDERS[role]:
            await self.error(ws, f"role {role} may not send {env.type}")
            return

        # One clock: the gateway stamps every envelope (FR-17).
        env.ts = now_ms()
        self.store({"source": role, **env.model_dump(mode="json")})

        if isinstance(msg, ProposedDirective):
            if msg.event_id in self.decided or msg.event_id in self.pending:
                await self.error(ws, f"{msg.event_id} already proposed")
                return
            self.pending[msg.event_id] = (msg, env.ts)
            await self.broadcast(env.model_dump_json(), env.type)
        elif isinstance(msg, VoiceApproval):
            await self.broadcast(env.model_dump_json(), env.type)
            if msg.decision != "unclear":  # the voice loop retries, then times out
                await self.decide(msg.event_id, msg.decision == "approve", "voice", ws)
        elif isinstance(msg, (ApprovedDirective, RejectedDirective)):
            await self.decide(msg.event_id, isinstance(msg, ApprovedDirective), "click", ws)
        else:
            await self.broadcast(env.model_dump_json(), env.type)

    async def decide(self, event_id: str, approve: bool, via: str, ws: WebSocket) -> None:
        proposal = self.take_pending(event_id)
        if proposal is None:
            await self.error(ws, f"{event_id} is not pending")
            return
        if approve:
            await self.emit(
                ApprovedDirective(
                    event_id=event_id,
                    instruction_text=proposal.instruction_text,
                    slots=proposal.slots,
                    approved_by="controller",
                    approved_via=via,
                )
            )
        else:
            await self.emit(RejectedDirective(event_id=event_id, rejected_by="controller", rejected_via=via))

    def live_pending(self) -> list[ProposedDirective]:
        cutoff = now_ms() - self.pending_ttl_ms
        return [p for p, received in self.pending.values() if received >= cutoff]


def origin_ok(ws: WebSocket) -> bool:
    """Browsers send Origin. Only accept pages served by this gateway (or local tools)."""
    origin = ws.headers.get("origin")
    if origin is None:
        return True
    return urlparse(origin).netloc == ws.headers.get("host")


def create_app(sink=None, pending_ttl_s: float = PENDING_TTL_S,
               demo_audio_dir: Path | None = None) -> FastAPI:
    sink = sink or sink_from_env(ROOT / "data" / "events.jsonl")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if hasattr(sink, "aclose"):
            await sink.aclose()  # send what is still queued

    app = FastAPI(title="Unstep gateway", lifespan=lifespan)
    gw = Gateway(sink, pending_ttl_s)
    app.state.gateway = gw

    @app.get("/demo/index.html")
    @app.get("/demo/")
    async def demo():
        # The demo screen is read-only, so it never carries the token: a visitor to
        # this page must not gain a role that can approve directives.
        html = (ROOT / "web" / "demo" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("__UNSTEP_TOKEN_QUERY__", ""))

    audio_dir = Path(demo_audio_dir) if demo_audio_dir is not None else ROOT / "data" / "demo" / "audio"

    @app.get("/demo/audio/{filename}")
    async def demo_audio(filename: str):
        from fastapi import HTTPException
        from fastapi.responses import FileResponse

        if Path(filename).name != filename or not filename.endswith(".wav"):
            raise HTTPException(404)
        path = audio_dir / filename
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="audio/wav")

    app.mount("/demo", StaticFiles(directory=ROOT / "web" / "demo", html=True), name="demo")

    @app.get("/health")
    async def health():
        stored = {k: getattr(gw.sink, k) for k in ("sent", "failed", "dropped") if hasattr(gw.sink, k)}
        return {
            "ok": True,
            "clients": {r: len(c) for r, c in gw.clients.items()},
            "pending": len(gw.pending),
            "sink": {"kind": type(gw.sink).__name__, **stored},
        }

    @app.get("/")
    async def dashboard():
        # The page is only served by this gateway, so it may carry the token (FR-13).
        token = gateway_token()
        query = f"?token={quote(token, safe='')}" if token else ""
        html = (ROOT / "web" / "dashboard.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("__UNSTEP_TOKEN_QUERY__", query))

    @app.websocket("/ws/{role}")
    async def ws_endpoint(ws: WebSocket, role: str):
        token_ok = not gateway_token() or ws.query_params.get("token") == gateway_token()
        # The read-only observer may skip the token, but only from this machine.
        local_observer = role == "observer" and ws.client is not None and ws.client.host in LOOPBACK
        if role not in ROLES or not origin_ok(ws) or not (token_ok or local_observer):
            await ws.close(code=4003)
            return
        await ws.accept()
        if role == "observer":
            async with gw.observer_lock:
                for raw in gw.history:
                    await ws.send_text(raw)
                gw.clients[role].add(ws)
        else:
            gw.clients[role].add(ws)
        log.info("%s connected", role)
        if role in ("dashboard", "controller_voice"):
            # Replay undecided proposals so a reconnect doesn't lose cards.
            for proposal in gw.live_pending():
                await ws.send_text(wrap(proposal))
        try:
            while True:
                if role == "observer":
                    incoming = await ws.receive()
                    if incoming["type"] == "websocket.disconnect":
                        break
                    await gw.error(ws, "role observer may not send messages")
                else:
                    await gw.handle(role, await ws.receive_text(), ws)
        except WebSocketDisconnect:
            pass
        finally:
            gw.clients[role].discard(ws)
            log.info("%s disconnected", role)

    return app


app = create_app()
