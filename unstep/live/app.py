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
from unstep.live.flightplans import FlightPlans, last_tower_call
from unstep.live.geo import AREAS, Geo, area_polygon
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
    stats_cache: dict[tuple, tuple[int, dict]] = {}

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

    @app.get("/live/record/")
    @app.get("/live/record")
    async def record_page():
        """Recording-session mode: the presenter's start/stop page, with the tower's line prompter."""
        token = gateway_token()
        query = f"?token={quote(token, safe='')}" if token else ""
        html = (WEB / "record" / "index.html").read_text(encoding="utf-8")
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
    async def live_stats(since_ms: int = 0, include_simulated: bool | None = None):
        """Per-frequency counts for the console (W4): Elastic ES|QL when configured, else the room's traces."""
        from unstep.ground.stats import frequency_stats

        now = now_ms()
        if include_simulated is None:  # a screen that shows benchmark history sets this on the hub, not per request
            include_simulated = env("UNSTEP_STATS_INCLUDE_SIMULATED", default="0").lower() in ("1", "true", "yes", "on")
        key = (since_ms, include_simulated)
        if (cached := stats_cache.get(key)) and now - cached[0] < STATS_CACHE_MS:
            return cached[1]
        result = await frequency_stats(room.frequency, max(since_ms, room.reset_at), room.traces,
                                       include_simulated=include_simulated)
        stats_cache.clear()  # one console polls one window; keep the cache tiny
        stats_cache[key] = (now, result)
        return result

    from unstep.ground.audit_chat import audit_chat_from_env

    app.state.audit_chat = audit_chat_from_env() if live else None  # tests may set their own

    @app.get("/live/ask-audit")
    async def ask_audit_available():
        """Whether "ask the audit trail" can run here (Elastic and Kibana configured and the room is live)."""
        return {"available": app.state.audit_chat is not None, "agent": "unstep-audit"}

    @app.post("/live/ask-audit")
    async def ask_audit(request: Request):
        """A controller's question about the last hour, answered from the audit trail by an Elastic agent.
        Never on the radio path; one question at a time; read-only."""
        if gateway_token() and request.query_params.get("token") != gateway_token():
            return JSONResponse({"error": "wrong room token"}, status_code=403)
        chat = app.state.audit_chat
        if chat is None:
            return {"ok": False, "available": False, "error": "Elastic isn't connected here, so there is no audit trail to ask."}
        try:
            question = str((await request.json()).get("question", ""))
        except ValueError:
            question = ""
        return {"available": True, **(await chat.ask(question))}

    flight_plans = FlightPlans()

    @app.get("/live/clearance-context/{station}")
    async def clearance_context(station: str):
        """Facts for the console's Clearance agent: the plane's flight plan (Elastic) and the last tower
        call it heard (its own Moss session). The console's fixed rules make the proposal."""
        s = room.stations.get(station)
        if s is None or s.kind != "aircraft":
            return JSONResponse({"error": "unknown plane"}, status_code=404)
        order = [x.id for x in room.stations.values() if x.kind == "aircraft"].index(station)
        edge = room.edges.get(s.callsign)
        return {"station": station, "callsign": s.callsign, "flight_plan": await flight_plans.get(s.callsign, order),
                "last_tower_call": await last_tower_call(edge, s.spoken or s.callsign) if edge else None,
                "runway_traffic": await geo.runway_traffic(exclude=station)}

    geo = Geo()

    @app.post("/live/geo/positions")
    async def geo_positions(request: Request):
        """The console's plane positions, once a second: stored in Elastic as geo points, with the airport
        areas (Elastic geo shapes) each plane is in."""
        body = await request.json()
        planes = [p for p in body.get("planes", []) if isinstance(p, dict) and {"id", "x", "z"} <= p.keys()][:20]
        return await geo.locate(planes)

    @app.get("/live/geo/airport")
    async def geo_airport():
        """The airport's areas as GeoJSON, for a map."""
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": n, "kind": k}, "geometry": area_polygon(b)} for n, k, b in AREAS]}

    @app.get("/live/flightlog")
    async def flightlog(q: str = "", callsign: str = "", since_ms: int = 0):
        """Search past flights saved to the flight log (Moss Cloud when live), with its status."""
        if room.flight_log is None:
            return {"status": None, "results": None}
        results = await room.flight_log.search(q, callsign or None, since_ms or None)
        return {"status": room.flight_log.status(), "results": results}

    @app.post("/live/join")
    async def live_join(request: Request):
        """"Join as a pilot": hands out a free aircraft, adding one from the fleet if needed."""
        if gateway_token() and request.query_params.get("token") != gateway_token():
            return JSONResponse({"error": "wrong room token"}, status_code=403)
        seat = await room.claim_aircraft(language=request.query_params.get("language"))
        if seat is not None and request.query_params.get("name"):  # recording-session mode: who is speaking
            room.set_speaker(seat.id, request.query_params["name"][:60], request.query_params.get("consent") == "1")
        if seat is None:
            n = len(room.fleet_limit())
            return JSONResponse({"error": f"All {n} planes are taken. Watch on the projector.", "full": True},
                                status_code=409)
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
