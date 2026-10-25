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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from unstep.clock import now_ms
from unstep.config import ROOT, allowed_origins, env, gateway_token
from unstep.gateway.server import create_app, origin_listed, origin_ok
from unstep.cockpit.translate import LANGUAGES
from unstep.live.addresses import lan_addresses, own_hostnames, reachable_from_lan
from unstep.live.flightplans import FlightPlans, last_tower_call
from unstep.ground.reports import reports_from_env
from unstep.live.geo import AREAS, Geo, area_polygon
from unstep.live.room import LiveRoom

log = logging.getLogger("unstep.live")
WEB = ROOT / "web" / "live"
PILOT_APP = ROOT / "app" / "dist"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
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
    async def live_page(request: Request):
        # The old "Pick your seat" page is gone: the console's QR is the one way in. Old links land on the console.
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"/live/atc/{query}", status_code=307)

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
        # When the console page is served through Vercel (a proxy that cannot carry WebSockets), the page opens its
        # socket straight to this hub: UNSTEP_PUBLIC_URL's host, filled in here.
        hub_host = urlsplit(env("UNSTEP_PUBLIC_URL") or "").netloc
        return HTMLResponse(html.replace("__UNSTEP_TOKEN_QUERY__", query).replace("__UNSTEP_HUB_HOST__", hub_host))

    origins = allowed_origins()
    if origins:  # the hosted pilot app reads /live/stations and calls /live/join cross-origin
        app.add_middleware(CORSMiddleware, allow_origin_regex="|".join(fnmatch.translate(o) for o in origins),
                           allow_methods=["GET", "POST"], allow_headers=["content-type"])

    def usable_link(link: str, request: Request) -> bool:
        """A join link this hub may hand out: plain http(s), no credentials, and a host that is this hub's own
        (as the request saw it, a LAN address of this computer, or UNSTEP_PUBLIC_URL) or a listed pilot app."""
        try:
            url = urlsplit(link)
            return (url.scheme in {"http", "https"} and url.username is None and url.password is None
                    and bool(url.hostname)
                    and (url.hostname == request.url.hostname
                         or url.hostname in own_hostnames(env("UNSTEP_PUBLIC_URL"))
                         or origin_listed(f"{url.scheme}://{url.netloc}")))
        except ValueError:
            return False

    def is_local_viewer(request: Request) -> bool:
        """The console is open on this computer (localhost or one of its own addresses), not through a public link."""
        host = request.url.hostname or ""
        return host in LOOPBACK_HOSTS or host in set(lan_addresses())

    @app.get("/live/qr.svg")
    async def live_qr(request: Request, u: str):
        if not usable_link(u, request):
            raise HTTPException(status_code=400, detail="QR URL must use this server's host")
        qr = qrcode.make(u, image_factory=SvgPathImage)
        return Response(qr.to_string(), media_type="image/svg+xml")

    @app.get("/live/pilot-link")
    async def pilot_link(request: Request):
        """The link pilots scan: the hosted pilot app (UNSTEP_PILOT_APP_URL) pointed at this
        hub's public address (UNSTEP_PUBLIC_URL, e.g. the tunnel), or the copy this hub serves."""
        base = request.query_params.get("base")  # the console's "change link": one of /live/addresses
        if base and not usable_link(base, request):
            raise HTTPException(status_code=400, detail="That address is not one this hub can hand out")
        hub = (base or env("UNSTEP_PUBLIC_URL") or str(request.base_url)).rstrip("/")
        if (not base and not env("UNSTEP_PUBLIC_URL") and request.url.hostname in LOOPBACK_HOSTS
                and reachable_from_lan(getattr(app.state, "bind_host", None)) and lan_addresses()):
            # The console is open on this computer, but a QR for localhost only works here: use the wifi address.
            port = getattr(app.state, "bind_port", None) or request.url.port or (443 if request.url.scheme == "https" else 80)
            hub = f"{getattr(app.state, 'scheme', None) or request.url.scheme}://{lan_addresses()[0]}:{port}"
        token = gateway_token()
        app_url = env("UNSTEP_PILOT_APP_URL")
        if app_url:
            query = {"hub": hub, **({"token": token} if token else {})}
            return {"url": f"{app_url.rstrip('/')}/?{urlencode(query)}", "hosted": True}
        query = f"?token={quote(token, safe='')}" if token else ""
        return {"url": f"{hub}/pilot/{query}", "hosted": False}

    @app.get("/live/addresses")
    async def live_addresses(request: Request):
        """What people could open instead of `localhost`: this computer only, the same wifi, a public link."""
        scheme = getattr(app.state, "scheme", None) or request.url.scheme
        port = getattr(app.state, "bind_port", None) or request.url.port or (443 if scheme == "https" else 80)
        on_lan = reachable_from_lan(getattr(app.state, "bind_host", None))
        public = (env("UNSTEP_PUBLIC_URL") or "").rstrip("/")
        options = []
        if not public or is_local_viewer(request):  # seen through the public link, local addresses mean nothing
            options.append({"id": "this", "label": "This computer only", "url": f"{scheme}://localhost:{port}",
                            "shareable": False, "note": "Only you can open this."})
            for n, ip in enumerate(lan_addresses()):
                options.append({"id": "lan", "label": "Same wifi" if n == 0 else f"Other network ({ip})",
                                "url": f"{scheme}://{ip}:{port}", "shareable": on_lan,
                                "note": None if on_lan else "Start the hub with --host 0.0.0.0 so phones can reach it."})
        if public:
            options.insert(0, {"id": "public", "label": "Public link (works on any network, https)", "url": public,
                               "shareable": True, "note": None})
        return {"current": f"{request.url.scheme}://{request.url.netloc}", "options": options, "has_public": bool(public)}

    @app.get("/live/pi-join")
    async def pi_join(request: Request):
        """What the console's "Add Raspberry Pi" button shows: the address the Pi should use and the command
        to run on it. The room code, when there is one, is named but never sent."""
        base = request.query_params.get("base")
        if base and not usable_link(base, request):
            raise HTTPException(status_code=400, detail="That address is not one this hub can hand out")
        hub = base
        if not hub:
            options = (await live_addresses(request))["options"]
            best = next((o for o in options if o["shareable"] and o["id"] == "public"), None)                 or next((o for o in options if o["shareable"] and o["id"] == "lan"), None)
            hub = best["url"] if best else str(request.base_url).rstrip("/")
        needs_token = bool(gateway_token())
        return {"hub": hub.rstrip("/"), "needs_token": needs_token,
                "command": f"python scripts/pi_plane.py --hub {hub.rstrip('/')}" + (" --token <room code>" if needs_token else ""),
                "shareable": not urlsplit(hub).hostname in {"localhost", "127.0.0.1", "::1"}}

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

    from unstep.ground.audit_chat import AGENTS, audit_chat_from_env

    app.state.audit_chat = audit_chat_from_env() if live else None  # tests may set their own

    @app.get("/live/ask-audit")
    async def ask_audit_available():
        """Whether "ask the audit trail" can run here (Elastic and Kibana configured and the room is live)."""
        return {"available": app.state.audit_chat is not None, "agent": "unstep-audit", "agents": sorted(AGENTS)}

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
            body = await request.json()
            question, which = str(body.get("question", "")), str(body.get("agent", "audit"))
        except ValueError:
            question, which = "", "audit"
        return {"available": True, **(await chat.ask(question, which if which in AGENTS else "audit"))}

    app.state.reports = reports_from_env() if live else None  # tests may set their own

    @app.get("/live/reports")
    async def reports_latest():
        """The newest shift briefing and nightly review saved by the Elastic workflows, read from their indexes."""
        if app.state.reports is None:
            return {"available": False}
        return {"available": True, **(await app.state.reports.latest())}

    @app.post("/live/reports/run")
    async def reports_run(request: Request):
        """Start the briefing or the nightly review now (they also run on a schedule). One at a time; read-only."""
        if gateway_token() and request.query_params.get("token") != gateway_token():
            return JSONResponse({"error": "wrong room token"}, status_code=403)
        if app.state.reports is None:
            return {"ok": False, "available": False, "error": "Elastic isn't connected here."}
        return await app.state.reports.run(request.query_params.get("which", "briefing"))

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
    room.geo = geo

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
