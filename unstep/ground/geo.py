"""Where a plane is on the airport, in words (D51). A fixed table of named points, not a survey.

The points mirror the console's ground graph (`web/live/atc/taxi.js`: scene units x, z). The metres-per-unit scale
and the origin are our stand-in until Rishit's side gives real ones, so every sentence made here says "demo map".
Pure functions; Elastic gets the same points as `geo_point` in the `unstep-airport` index (scripts/deploy_elastic.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

ORIGIN_LAT, ORIGIN_LON = 37.6188, -122.3750  # the contracts' default GPS (unstep/cockpit/edge.py)
METRES_PER_UNIT = 1.0                          # stand-in scale: one console unit is one metre
LABEL = "demo map, not surveyed"
_M_PER_DEG_LAT = 111_320.0

RWY_Z, TWY_Z, TWYA_Z = 22.0, 14.0, 4.5
HOLD_STOP_Z = RWY_Z - 3.4 - 1.4


@dataclass(frozen=True)
class Place:
    name: str
    x: float
    z: float
    runway: str | None = None  # the runway a hold-short point protects

    @property
    def lat(self) -> float:
        return round(ORIGIN_LAT + self.z * METRES_PER_UNIT / _M_PER_DEG_LAT, 7)

    @property
    def lon(self) -> float:
        return round(ORIGIN_LON + self.x * METRES_PER_UNIT / (_M_PER_DEG_LAT * math.cos(math.radians(ORIGIN_LAT))), 7)


PLACES: tuple[Place, ...] = (
    Place("hold short runway 33", -33.0, HOLD_STOP_Z, "33"),
    Place("hold short runway 15", 33.0, HOLD_STOP_Z, "15"),
    Place("runway 33 end", -33.0, RWY_Z, "33"),
    Place("runway 15 end", 33.0, RWY_Z, "15"),
    *(Place(f"taxiway A at {n}", x, TWYA_Z) for n, x in (("A1", -38.0), ("A2", -17.0), ("A3", 6.0), ("A4", 30.0))),
    Place("taxiway B", 0.0, TWY_Z),
)


def distance_m(a: Place, b: Place) -> float:
    return round(math.hypot(a.x - b.x, a.z - b.z) * METRES_PER_UNIT, 1)


def nearest(x: float, z: float) -> tuple[Place, float]:
    probe = Place("plane", x, z)
    best = min(PLACES, key=lambda p: distance_m(probe, p))
    return best, distance_m(probe, best)


def hold_line(runway: str | None) -> Place | None:
    return next((p for p in PLACES if p.runway == runway and p.name.startswith("hold short")), None)


def describe(x: float, z: float, runway: str | None = None) -> str:
    """One plain sentence: nearest named point and, when a runway is named, the distance to its hold-short line."""
    near, d = nearest(x, z)
    text = f"{d:g} m from {near.name}"
    line = hold_line(runway)
    if line is not None and line is not near:
        text += f", {distance_m(Place('plane', x, z), line):g} m from the {line.name} line"
    return f"{text} ({LABEL})"
