"""Where a plane is on the airport, in words (D51). Named points on the console's ground graph.

Positions are the console's scene units (web/live/atc/taxi.js). The scale and the real coordinates come from
`unstep.live.geo` (one source of truth, Rishit's side): one unit is `METERS_PER_UNIT` metres. Distances here are in
metres on that map, which is a demo map and not a survey, and every sentence says so. Pure functions; the same
shapes live in Elastic (`unstep-airport`), this module only names points and measures to them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from unstep.live.geo import ANCHOR, HEADING_X, METERS_PER_UNIT, to_latlon

LABEL = "demo map, not surveyed"
RWY_Z, TWY_Z, TWYA_Z = 22.0, 14.0, 4.5
HOLD_STOP_Z = RWY_Z - 3.4 - 1.4  # where a plane stops, nose behind the painted line (taxi.js)


@dataclass(frozen=True)
class Place:
    name: str
    x: float
    z: float
    runway: str | None = None  # the runway a hold-short point protects

    @property
    def latlon(self) -> tuple[float, float]:
        return to_latlon(self.x, self.z)


PLACES: tuple[Place, ...] = (
    Place("hold short runway 33", -33.0, HOLD_STOP_Z, "33"),
    Place("hold short runway 15", 33.0, HOLD_STOP_Z, "15"),
    Place("runway 33 end", -33.0, RWY_Z, "33"),
    Place("runway 15 end", 33.0, RWY_Z, "15"),
    *(Place(f"taxiway A at {n}", x, TWYA_Z) for n, x in (("A1", -38.0), ("A2", -17.0), ("A3", 6.0), ("A4", 30.0))),
    Place("taxiway B", 0.0, TWY_Z),
)


def distance_m(ax: float, az: float, bx: float, bz: float) -> float:
    return round(math.hypot(ax - bx, az - bz) * METERS_PER_UNIT, 1)


def nearest(x: float, z: float) -> tuple[Place, float]:
    best = min(PLACES, key=lambda p: distance_m(x, z, p.x, p.z))
    return best, distance_m(x, z, best.x, best.z)


def hold_line(runway: str | None) -> Place | None:
    return next((p for p in PLACES if p.runway == runway and p.name.startswith("hold short")), None)


def describe(x: float, z: float, runway: str | None = None) -> str:
    """One plain sentence: nearest named point and, when a runway is named, the distance to its hold-short line."""
    near, d = nearest(x, z)
    text = f"{d:g} m from {near.name}"
    line = hold_line(runway)
    if line is not None and line is not near:
        text += f", {distance_m(x, z, line.x, line.z):g} m from the {line.name} line"
    return f"{text} ({LABEL})"


def to_scene(lat: float, lon: float) -> tuple[float, float]:
    """The inverse of `to_latlon`: a stored position back to the console's scene units."""
    lat0, lon0 = ANCHOR
    north, east = (lat - lat0) * 111_320, (lon - lon0) * 111_320 * math.cos(math.radians(lat0))
    bx, bz = math.radians(HEADING_X), math.radians(HEADING_X + 90)
    return ((north * math.cos(bx) + east * math.sin(bx)) / METERS_PER_UNIT,
            (north * math.cos(bz) + east * math.sin(bz)) / METERS_PER_UNIT)


def describe_position(position: dict, runway: str | None = None) -> str:
    """A stored position ({lat, lon, areas}, as `Geo.latest` keeps it) in one plain sentence."""
    x, z = to_scene(position["lat"], position["lon"])
    where = ", ".join(position.get("areas") or []) or "off the mapped areas"
    return f"In {where}; {describe(x, z, runway)}" if position.get("areas") else f"{where.capitalize()}; {describe(x, z, runway)}"
