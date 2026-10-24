"""Live room web app: the gateway plus /live pages and the /live/ws/{station} socket."""

from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import fnmatch

import qrcode
from qrcode.image.svg import SvgPathImage

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from unstep.clock import now_ms
from unstep.config import ROOT, allowed_origins, env, gateway_token
from unstep.gateway.server import create_app, origin_listed, origin_ok
from unstep.cockpit.translate import LANGUAGES
from unstep.live.room import LiveRoom

log = logging.getLogger("unstep.live")
WEB = ROOT / "web" / "live"
PILOT_APP = ROOT / "app" / "dist"
WARMING_NOTICE_S = 0.5  # a seat waiting longer than this for the room to start is told so
STATS_CACHE_MS = 2000  # consoles poll /live/stats every 5 s; Elastic is asked at most this often


def create_live_app(live: bool, sink=None, room: LiveRoom | None = None, warm_start: bool = False) -> FastAPI:
    """`warm_start=True` (the real server) starts the room when the server starts, so the
    first call isn't spent starting cockpit agents and Moss sessions (R13 item 2). Tests
    keep the lazy start on the first authenticated socket."""
    app = create_app(sink)
    room = room or LiveRoom(app.state.gateway, live=live)
    app.state.room = room
    stats_cache: dict[int, tuple[int, dict]] = {}

    # Start the room (cockpit agents, Moss sessions, links) when the server starts, not on
    # the first socket, so the first call isn't spent waiting for it (R13 item 2).
    gateway_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a):
        async with gateway_lifespan(a) as state:
            async def warm():
                try:
                    await room.start()
                    log.info("live room ready")
                except Exception:
                    log.exception("live room failed to start; the first socket will retry")

            task = asyncio.create_task(warm())
            try:
                yield state
            finally:
                if not task.done():
                    task.cancel()

    if warm_start:
        app.router.lifespan_context = lifespan

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

    @app.get("/live/qr.svg")
    async def live_qr(request: Request, u: str):
        try:
            url = urlsplit(u)
            # This hub, or the hosted pilot app listed in UNSTEP_ALLOWED_ORIGINS.
            valid = (url.scheme in {"http", "https"} and url.username is None and url.password is None
                     and (url.hostname == request.url.hostname
                          or origin_listed(f"{url.scheme}://{url.netloc}")))
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(status_code=400, detail="QR URL must use this server's host")
        qr = qrcode.make(u, image_factory=SvgPathImage)
        return Response(qr.to_string(), media_type="image/svg+xml")

    @app.get("/live/pilot-link")
    async def pilot_link(request: Request):
        """The link pilots scan: the hosted pilot app (UNSTEP_PILOT_APP_URL) pointed at this
        hub's public address (UNSTEP_PUBLIC_URL, e.g. the tunnel), or the copy this hub serves."""
        hub = (env("UNSTEP_PUBLIC_URL") or str(request.base_url)).rstrip("/")
        token = gateway_token()
        app_url = env("UNSTEP_PILOT_APP_URL")
        if app_url:
            query = {"hub": hub, **({"token": token} if token else {})}
            return {"url": f"{app_url.rstrip('/')}/?{urlencode(query)}", "hosted": True}
        query = f"?token={quote(token, safe='')}" if token else ""
        return {"url": f"{hub}/pilot/{query}", "hosted": False}

    @app.get("/live/stations")
    async def live_stations():
        return {"live": room.live, "frequency": room.frequency, "now_ms": now_ms(),
                "stations": [{"id": st.id, "kind": st.kind, "label": st.label, "callsign": st.callsign,
                              "spoken": st.spoken, "name": st.name} for st in room.stations.values()],
                "connected": {sid: len(c) for sid, c in room.clients.items()},
                "languages": dict(LANGUAGES)}  # offered for the private repeat; English always first

    @app.get("/live/stats")
    async def live_stats(since_ms: int = 0):
        """Per-frequency counts for the console (W4): Elastic ES|QL when configured, else the room's traces."""
        from unstep.ground.stats import frequency_stats

        now = now_ms()
        if (cached := stats_cache.get(since_ms)) and now - cached[0] < STATS_CACHE_MS:
            return cached[1]
        result = await frequency_stats(room.frequency, since_ms, room.traces)
        stats_cache.clear()  # one console polls one since_ms; keep the cache tiny
        stats_cache[since_ms] = (now, result)
        return result

    @app.post("/live/join")
    async def live_join(request: Request):
        """"Join as a pilot": hands out a free aircraft, adding one from the fleet if needed."""
        if gateway_token() and request.query_params.get("token") != gateway_token():
            return JSONResponse({"error": "wrong room token"}, status_code=403)
        seat = await room.claim_aircraft(language=request.query_params.get("language"))
        if seat is None:
            return JSONResponse({"error": "every aircraft is taken"}, status_code=409)
        return {"station": seat.id, "callsign": seat.callsign, "spoken": seat.spoken, "name": seat.name,
                "frequency": room.frequency, "live": room.live, "language": room.languages.get(seat.id)}

    app.mount("/live/static", StaticFiles(directory=WEB), name="live-static")
    if PILOT_APP.is_dir():  # `npm run build` in app/: the pilot app, served here for LAN or offline runs
        app.mount("/pilot", StaticFiles(directory=PILOT_APP, html=True), name="pilot-app")

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
        # Normally already started at server start. If not, say so instead of going quiet:
        # anything the seat sends meanwhile waits in the socket and is handled once ready.
        starting = asyncio.ensure_future(room.start())
        done, _ = await asyncio.wait({starting}, timeout=WARMING_NOTICE_S)
        if not done:
            await ws.send_json({"type": "status", "ts": now_ms(),
                                "text": "Room is warming up. Anything you send now goes out in a few seconds."})
        await starting
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
