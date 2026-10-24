"""WebSocket gateway (task B1): relays every contract between roles and stores it.

Clients connect to /ws/{role}. Each message type goes to the roles listed in
ROUTES. The gateway also turns approvals into `ApprovedDirective` or
`RejectedDirective`, whether they come from the controller's voice loop or a
dashboard click, so a directive can only be decided once.

Run: uvicorn unstep.gateway.server:app --port 8765
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import ValidationError

from unstep.contracts import (
    ApprovedDirective,
    ProposedDirective,
    RejectedDirective,
    VoiceApproval,
    unwrap,
    wrap,
)
from unstep.gateway.sink import JsonlSink

log = logging.getLogger("unstep.gateway")

ROOT = Path(__file__).resolve().parents[2]

ROLES = {"cockpit", "tower", "agents", "dashboard", "controller_voice", "monitor"}

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


class Gateway:
    def __init__(self, sink):
        self.sink = sink
        self.clients: dict[str, set[WebSocket]] = defaultdict(set)
        # Proposals waiting for a human decision, by event_id.
        self.pending: dict[str, ProposedDirective] = {}

    async def broadcast(self, raw: str, msg_type: str) -> None:
        for role in ROUTES.get(msg_type, set()):
            for ws in list(self.clients[role]):
                try:
                    await ws.send_text(raw)
                except Exception:
                    self.clients[role].discard(ws)

    async def emit(self, msg) -> None:
        raw = wrap(msg)
        self.sink.write({"source": "gateway", **json.loads(raw)})
        await self.broadcast(raw, type(msg).__name__)

    async def handle(self, role: str, raw: str, ws: WebSocket) -> None:
        try:
            env, msg = unwrap(raw)
        except (ValidationError, ValueError) as e:
            await ws.send_json({"type": "Error", "data": {"message": str(e)[:500]}})
            return

        self.sink.write({"source": role, **env.model_dump(mode="json")})

        if isinstance(msg, ProposedDirective):
            self.pending[msg.event_id] = msg
            await self.broadcast(raw, env.type)
        elif isinstance(msg, VoiceApproval):
            await self.broadcast(raw, env.type)
            await self.decide_from_voice(msg)
        elif isinstance(msg, (ApprovedDirective, RejectedDirective)):
            # A dashboard click. Ignore it if the event was already decided.
            if self.pending.pop(msg.event_id, None) is None:
                await ws.send_json(
                    {"type": "Error", "data": {"message": f"{msg.event_id} is not pending"}}
                )
                return
            await self.broadcast(raw, env.type)
        else:
            await self.broadcast(raw, env.type)

    async def decide_from_voice(self, va: VoiceApproval) -> None:
        if va.decision == "unclear":
            return  # The voice loop retries, then times out (PRD voice approval rules).
        proposal = self.pending.pop(va.event_id, None)
        if proposal is None:
            return
        if va.decision == "approve":
            await self.emit(
                ApprovedDirective(
                    event_id=proposal.event_id,
                    instruction_text=proposal.instruction_text,
                    slots=proposal.slots,
                    approved_by="controller",
                    approved_via="voice",
                )
            )
        else:
            await self.emit(
                RejectedDirective(event_id=va.event_id, rejected_by="controller", rejected_via="voice")
            )


def create_app(sink=None) -> FastAPI:
    app = FastAPI(title="Unstep gateway")
    gw = Gateway(sink or JsonlSink(ROOT / "data" / "events.jsonl"))
    app.state.gateway = gw

    @app.get("/health")
    async def health():
        return {"ok": True, "clients": {r: len(c) for r, c in gw.clients.items()}, "pending": list(gw.pending)}

    @app.get("/")
    async def dashboard():
        return FileResponse(ROOT / "web" / "dashboard.html")

    @app.websocket("/ws/{role}")
    async def ws_endpoint(ws: WebSocket, role: str):
        if role not in ROLES:
            await ws.close(code=4004)
            return
        await ws.accept()
        gw.clients[role].add(ws)
        log.info("%s connected", role)
        try:
            while True:
                await gw.handle(role, await ws.receive_text(), ws)
        except WebSocketDisconnect:
            pass
        finally:
            gw.clients[role].discard(ws)
            log.info("%s disconnected", role)

    return app


app = create_app()
