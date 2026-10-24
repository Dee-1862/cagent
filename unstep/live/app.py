"""Live room web app: the gateway plus /live pages and the /live/ws/{station} socket."""

from __future__ import annotations

import asyncio
import hmac
import logging
from pathlib import Path
from urllib.parse import quote

import fnmatch

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from unstep.clock import now_ms
from unstep.config import ROOT, allowed_origins, env, gateway_token
from unstep.gateway.server import create_app, origin_ok
from unstep.live.room import LiveRoom

log = logging.getLogger("unstep.live")
WEB = ROOT / "web" / "live"


def create_live_app(live: bool, sink=None, room: LiveRoom | None = None) -> FastAPI:
    app = create_app(sink)
    room = room or LiveRoom(app.state.gateway, live=live)
    app.state.room = room

    @app.get("/live")
    @app.get("/live/")
    async def live_page():
        # Served by this gateway, so it may carry the token like the dashboard (FR-13).
        token = gateway_token()
        query = f"?token={quote(token, safe='')}" if token else ""
        html = (WEB / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("__UNSTEP_TOKEN_QUERY__", query))

    @app.get("/live/atc/")
    @app.get("/live/atc")
    async def atc_page():
        token = gateway_token()
        query = f"?token={quote(token, safe='')}" if token else ""
        html = (WEB / "atc" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("__UNSTEP_TOKEN_QUERY__", query))

    origins = allowed_origins()
    if origins:  # the hosted pilot app reads /live/stations and calls /live/join cross-origin
        app.add_middleware(CORSMiddleware, allow_origin_regex="|".join(fnmatch.translate(o) for o in origins),
                           allow_methods=["GET", "POST"], allow_headers=["content-type"])

    @app.get("/live/stations")
    async def live_stations():
        return {"live": room.live, "frequency": room.frequency, "now_ms": now_ms(),
                "stations": [{"id": st.id, "kind": st.kind, "label": st.label, "callsign": st.callsign,
                              "spoken": st.spoken, "name": st.name} for st in room.stations.values()],
                "connected": {sid: len(c) for sid, c in room.clients.items()}}

    @app.post("/live/join")
    async def live_join(request: Request):
        """"Join as a pilot": hands out a free aircraft, adding one from the fleet if needed."""
        if gateway_token() and request.query_params.get("token") != gateway_token():
            return JSONResponse({"error": "wrong room token"}, status_code=403)
        seat = await room.claim_aircraft()
        if seat is None:
            return JSONResponse({"error": "every aircraft is taken"}, status_code=409)
        return {"station": seat.id, "callsign": seat.callsign, "spoken": seat.spoken, "name": seat.name,
                "frequency": room.frequency, "live": room.live}

    app.mount("/live/static", StaticFiles(directory=WEB), name="live-static")

    @app.websocket("/live/ws/{station}")
    async def live_socket(ws: WebSocket, station: str):
        token_ok = not gateway_token() or ws.query_params.get("token") == gateway_token()
        if station not in room.stations or not origin_ok(ws) or not token_ok:
            await ws.close(code=4003)
            return
        await ws.accept()
        # Authenticate before starting the room or exposing its snapshot. The
        # password travels in a frame, never a URL (including access logs).
        if station == "atc":
            password = env("UNSTEP_ATC_PASSWORD")
            if password:
                await ws.send_json({"type": "auth_required"})
                try:
                    auth = await asyncio.wait_for(ws.receive_json(), timeout=30)
                    supplied = auth.get("password") if isinstance(auth, dict) else None
                    valid = (
                        isinstance(auth, dict) and auth.get("type") == "auth"
                        and isinstance(supplied, str)
                        and hmac.compare_digest(supplied.encode("utf-8"), password.encode("utf-8"))
                    )
                except (asyncio.TimeoutError, ValueError, WebSocketDisconnect):
                    valid = False
                if not valid:
                    await ws.close(code=4003, reason="Incorrect or missing ATC password. Return to the seat picker.")
                    return
            await ws.send_json({"type": "auth_status", "password_set": bool(password)})
        await room.start()
        await room.join(station, ws)
        try:
            while True:
                data = await ws.receive_json()
                if isinstance(data, dict) and data.get("type") == "ping":
                    # Clock sync: the phone takes the reply with the shortest round trip and
                    # sets offset = t1 - (t0 + t3) / 2, so its key and mic times are hub times.
                    await ws.send_json({"type": "pong", "t0": data.get("t0"), "t1": now_ms()})
                    continue
                try:
                    await room.handle(station, data)
                except Exception as e:  # one bad input must not drop the seat
                    log.exception("live input failed")
                    await ws.send_json({"type": "status", "text": f"input failed: {type(e).__name__}"})
        except WebSocketDisconnect:
            pass
        finally:
            room.leave(station, ws)

    return app
