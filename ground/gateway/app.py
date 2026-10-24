"""The Unstep WebSocket gateway (task B1).

Clients connect to /ws/{role} and send envelopes such as
{"type": "AnomalyEvent", "payload": {...}}. For each one the gateway checks the
role may send that type, validates the payload, stamps gateway_ts from the one
clock, stores it, and relays it to the roles in routing.RECIPIENTS.
"""

import logging
import time
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from contracts.models import (
    CONTRACTS,
    AnomalyEvent,
    ClickApproval,
    Contract,
    Envelope,
    ProposedDirective,
    VoiceApproval,
)
from ground.gateway.approvals import ApprovalBook, ApprovalError
from ground.gateway.routing import RECIPIENTS, ROLES, SENDERS
from ground.gateway.sinks import to_document

log = logging.getLogger("unstep.gateway")


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class Rejected(Exception):
    """A message the gateway refuses. The reason goes back to the sender only."""


class Hub:
    def __init__(self) -> None:
        self.connections: dict[str, set[WebSocket]] = {role: set() for role in ROLES}

    async def send(self, roles: Iterable[str], message: dict) -> None:
        for role in roles:
            for websocket in list(self.connections[role]):
                try:
                    await websocket.send_json(message)
                except Exception:
                    self.connections[role].discard(websocket)


def create_app(
    sink,
    trigger,
    voice_controller_id: str = "controller-1",
    clock: Callable[[], int] = now_ms,
) -> FastAPI:
    hub = Hub()
    book = ApprovalBook(voice_controller_id=voice_controller_id)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await sink.start()
        yield
        await trigger.stop()
        await sink.stop()

    app = FastAPI(title="Unstep gateway", lifespan=lifespan)

    async def publish(message: Contract, sender_role: str, sent_at: int | None = None) -> None:
        type_name = type(message).__name__
        envelope = {
            "type": type_name,
            "payload": message.model_dump(mode="json"),
            "sent_at": sent_at,
            "gateway_ts": clock(),
        }
        sink.write(to_document(envelope, sender_role))
        await hub.send(RECIPIENTS[type_name], envelope)

    async def handle(role: str, raw: str) -> None:
        try:
            envelope = Envelope.model_validate_json(raw)
        except ValidationError as e:
            raise Rejected(f"not a valid envelope: {e.errors()[0]['msg']}")

        contract = CONTRACTS.get(envelope.type)
        if contract is None:
            raise Rejected(f"unknown message type {envelope.type}")
        if role not in SENDERS[envelope.type]:
            raise Rejected(f"{role} may not send {envelope.type}")
        try:
            message = contract.model_validate(envelope.payload)
        except ValidationError as e:
            first = e.errors()[0]
            field = ".".join(str(part) for part in first["loc"])
            raise Rejected(f"invalid {envelope.type}: {field}: {first['msg']}")

        outcome = None
        try:
            if isinstance(message, ProposedDirective):
                book.propose(message)
            elif isinstance(message, (VoiceApproval, ClickApproval)):
                outcome = book.decide(message, clock())
        except ApprovalError as e:
            raise Rejected(str(e))

        await publish(message, role, envelope.sent_at)
        if outcome is not None:
            await publish(outcome, "gateway")
        if isinstance(message, AnomalyEvent):
            trigger.fire(message.event_id)

    @app.websocket("/ws/{role}")
    async def gateway_socket(websocket: WebSocket, role: str) -> None:
        if role not in ROLES:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        hub.connections[role].add(websocket)
        await websocket.send_json({"type": "Welcome", "payload": {"role": role, "now_ms": clock()}})
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    await handle(role, raw)
                except Rejected as e:
                    log.info("rejected message from %s: %s", role, e)
                    await websocket.send_json({"type": "Error", "payload": {"reason": str(e)}})
        except WebSocketDisconnect:
            pass
        finally:
            hub.connections[role].discard(websocket)

    @app.get("/time")
    async def gateway_time() -> dict:
        """The one clock. Clients use it to convert their timestamps (PRD: one clock)."""
        return {"now_ms": clock()}

    @app.get("/health")
    async def health() -> dict:
        return {
            "connected": {role: len(sockets) for role, sockets in hub.connections.items()},
            "dropped_documents": sink.dropped,
        }

    return app
