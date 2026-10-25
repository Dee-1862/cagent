"""The airport on the map: real coordinates for the console's 3D airport, its areas as Elastic geo shapes, and
every plane's position as an Elastic geo point.

The scene works in its own units (web/live/atc/taxi.js). Here one unit is 40 m and the runway's +x direction is
the runway 33 take-off heading (330 degrees), anchored on the bay off Berkeley, so the 76-unit runway is about
3 km long and points the way its number says.

What Elastic does with it:
  - `unstep-airport` holds each area (runway 33/15 protected area, the hold-short connectors B1 and B2,
    taxiways A and B) as a geo_shape.
  - Each second the console posts the planes' scene positions; they are converted and stored in
    `unstep-positions` (geo_point), and one _msearch asks, for every plane, which areas contain it
    (a geo_shape query with a point).
  - `runway_traffic` answers the Clearance agent: each plane's newest position on the ground (from the last few
    seconds) asked against the runway's stored shape. The track in `unstep-positions` is for a map.
Without Elastic the same areas are checked in process and labelled "local".
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Optional

import httpx

from unstep.config import elastic_settings

log = logging.getLogger("unstep.geo")

AIRPORT_INDEX = "unstep-airport"
POSITIONS_INDEX = "unstep-positions"
ANCHOR = (37.8650, -122.3300)  # lat, lon of scene (0, 0)
METERS_PER_UNIT = 40.0
HEADING_X = 330.0  # bearing of the scene's +x axis: the runway 33 take-off direction
ON_GROUND_ALT = 0.5  # scene units; above this a plane is airborne and on no ground area
RECENT_S = 4  # a position older than this no longer counts for runway traffic

# name, kind, (x0, z0, x1, z1) in scene units. The runway area runs from hold line to hold line distance.
AREAS = [
    ("Runway 33/15", "runway", (-38.5, 18.6, 38.5, 25.4)),
    ("B1 hold short (runway 33)", "hold", (-34.4, 15.3, -31.6, 18.6)),
    ("B2 hold short (runway 15)", "hold", (31.6, 15.3, 34.4, 18.6)),
    ("Taxiway B", "taxiway", (-44.0, 12.7, 36.0, 15.3)),
    ("Taxiway A", "taxiway", (-40.0, 3.2, 32.0, 5.8)),
]


def to_latlon(x: float, z: float) -> tuple[float, float]:
    """Scene position to (lat, lon). +z is 90 degrees clockwise from +x when seen from above."""
    bx, bz = math.radians(HEADING_X), math.radians(HEADING_X + 90)
    north = METERS_PER_UNIT * (x * math.cos(bx) + z * math.cos(bz))
    east = METERS_PER_UNIT * (x * math.sin(bx) + z * math.sin(bz))
    lat0, lon0 = ANCHOR
    return (round(lat0 + north / 111_320, 7), round(lon0 + east / (111_320 * math.cos(math.radians(lat0))), 7))


def area_polygon(box: tuple[float, float, float, float]) -> dict:
    x0, z0, x1, z1 = box
    ring = [to_latlon(x, z) for x, z in [(x0, z0), (x1, z0), (x1, z1), (x0, z1), (x0, z0)]]
    return {"type": "Polygon", "coordinates": [[[lon, lat] for lat, lon in ring]]}


def local_areas(x: float, z: float, alt: float = 0.0) -> list[str]:
    if alt > ON_GROUND_ALT:
        return []
    return [name for name, _, (x0, z0, x1, z1) in AREAS if x0 <= x <= x1 and z0 <= z <= z1]


def area_id(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


class Geo:
    def __init__(self, settings: Optional[tuple[str, str]] = None, timeout_s: float = 5.0):
        self.settings = settings if settings is not None else elastic_settings()
        self.timeout_s = timeout_s
        self._client: Optional[httpx.AsyncClient] = None
        self._ready = False
        self.latest: dict[str, dict] = {}  # station -> newest position, with when it arrived
        self._writing: Optional[asyncio.Task] = None

    @property
    def base(self) -> str:
        return self.settings[0].rstrip("/")

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(headers={"Authorization": f"ApiKey {self.settings[1]}"}, timeout=self.timeout_s)
        return self._client

    async def setup(self) -> None:
        """Create both indexes and store the airport's areas once per hub run (idempotent)."""
        if self._ready or not self.settings:
            return
        http = self._http()
        for index, props in [
            (AIRPORT_INDEX, {"name": {"type": "keyword"}, "kind": {"type": "keyword"}, "area": {"type": "geo_shape"}}),
            (POSITIONS_INDEX, {"station": {"type": "keyword"}, "state": {"type": "keyword"}, "location": {"type": "geo_point"},
                               "alt_m": {"type": "float"}, "areas": {"type": "keyword"}, "ts": {"type": "date"}}),
        ]:
            r = await http.put(f"{self.base}/{index}", json={"mappings": {"properties": props}})
            if r.status_code >= 400 and "resource_already_exists" not in r.text:
                r.raise_for_status()
        bulk = []
        for name, kind, box in AREAS:
            bulk += [{"index": {"_index": AIRPORT_INDEX, "_id": area_id(name)}}, {"name": name, "kind": kind, "area": area_polygon(box)}]
        r = await http.post(f"{self.base}/_bulk?refresh=wait_for", content=_ndjson(bulk),
                            headers={"Content-Type": "application/x-ndjson"})
        r.raise_for_status()
        self._ready = True

    async def locate(self, planes: list[dict]) -> dict:
        """Convert, store, and ask Elastic which areas hold each plane. Planes: {id, x, z, alt, state}."""
        started = time.perf_counter()
        out = {p["id"]: {"lat": (ll := to_latlon(p["x"], p["z"]))[0], "lon": ll[1], "alt_m": round(p.get("alt", 0) * METERS_PER_UNIT, 1),
                         "state": p.get("state"), "areas": local_areas(p["x"], p["z"], p.get("alt", 0))} for p in planes}
        for pid, v in out.items():
            self.latest[pid] = {**v, "at": time.monotonic()}
        if self.settings and planes:
            try:
                await self.setup()
                searches = []
                for p in planes:
                    searches += [{"index": AIRPORT_INDEX}, {"size": 10, "_source": ["name"], "query": {"geo_shape": {"area": {
                        "shape": {"type": "point", "coordinates": [out[p["id"]]["lon"], out[p["id"]]["lat"]]}, "relation": "intersects"}}}}]
                r = await self._http().post(f"{self.base}/_msearch", content=_ndjson(searches),
                                            headers={"Content-Type": "application/x-ndjson"})
                r.raise_for_status()
                took = 0
                for p, res in zip(planes, r.json()["responses"]):
                    took = max(took, res.get("took", 0))
                    names = [h["_source"]["name"] for h in res["hits"]["hits"]]
                    out[p["id"]]["areas"] = [] if p.get("alt", 0) > ON_GROUND_ALT else sorted(names)
                self._store(out)
                return {"planes": out, "backend": "elastic", "took_ms": took, "ms": _ms(started)}
            except Exception:
                log.warning("Elastic geo lookup failed; using the local copy of the areas", exc_info=True)
        return {"planes": out, "backend": "local", "took_ms": None, "ms": _ms(started)}

    def _store(self, out: dict) -> None:
        """Keep each plane's newest position, and write the track to Elastic in the background (for a map).
        No forced refresh: on our cluster that sometimes took over 5 s. A write still in flight skips this one."""
        now = int(time.time() * 1000)
        if self._writing is not None and not self._writing.done():
            return
        docs = []
        for pid, v in out.items():
            docs += [{"index": {"_index": POSITIONS_INDEX}}, {"station": pid, "state": v["state"], "alt_m": v["alt_m"],
                     "location": {"lat": v["lat"], "lon": v["lon"]}, "areas": v["areas"], "ts": now}]

        async def write():
            try:
                w = await self._http().post(f"{self.base}/_bulk", content=_ndjson(docs), headers={"Content-Type": "application/x-ndjson"})
                w.raise_for_status()
            except Exception as error:
                log.warning("storing plane positions in Elastic failed (%s)", type(error).__name__)

        self._writing = asyncio.create_task(write())

    async def runway_traffic(self, exclude: str = "") -> dict:
        """Planes on the ground inside the runway area now: each plane's newest position (from the last few
        seconds) asked against the runway's stored shape in Elastic, in one _msearch."""
        started = time.perf_counter()
        if not self.settings:
            return {"planes": None, "backend": "local", "ms": _ms(started)}
        now = time.monotonic()
        recent = {pid: v for pid, v in self.latest.items()
                  if pid != exclude and now - v["at"] <= RECENT_S and v["alt_m"] <= ON_GROUND_ALT * METERS_PER_UNIT}
        if not recent:
            return {"planes": [], "area": AREAS[0][0], "backend": "elastic", "took_ms": 0, "ms": _ms(started)}
        try:
            await self.setup()
            searches = []
            for v in recent.values():
                searches += [{"index": AIRPORT_INDEX}, {"size": 0, "query": {"bool": {"filter": [
                    {"ids": {"values": [area_id(AREAS[0][0])]}},
                    {"geo_shape": {"area": {"shape": {"type": "point", "coordinates": [v["lon"], v["lat"]]}, "relation": "intersects"}}}]}}}]
            r = await self._http().post(f"{self.base}/_msearch", content=_ndjson(searches), headers={"Content-Type": "application/x-ndjson"})
            r.raise_for_status()
            responses = r.json()["responses"]
            planes = [pid for pid, res in zip(recent, responses) if res["hits"]["total"]["value"]]
            took = max((res.get("took", 0) for res in responses), default=0)
            return {"planes": planes, "area": AREAS[0][0], "backend": "elastic", "took_ms": took, "ms": _ms(started)}
        except Exception:
            log.warning("Elastic runway traffic query failed", exc_info=True)
            return {"planes": None, "backend": "local", "ms": _ms(started)}


def _ndjson(lines: list[dict]) -> str:
    import json

    return "".join(json.dumps(line) + "\n" for line in lines)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
