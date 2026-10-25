"""The airport on the map: scene units to real coordinates, and which area a plane is in (unstep/live/geo.py)."""

import asyncio
import math

from unstep.live.geo import ANCHOR, AREAS, Geo, area_polygon, local_areas, to_latlon


def bearing_and_distance(a, b):
    (lat1, lon1), (lat2, lon2) = a, b
    north = (lat2 - lat1) * 111_320
    east = (lon2 - lon1) * 111_320 * math.cos(math.radians(lat1))
    return (math.degrees(math.atan2(east, north)) % 360, math.hypot(north, east))


def test_runway_points_the_way_its_number_says_and_is_about_3_km():
    assert to_latlon(0, 0) == ANCHOR
    b33, length = bearing_and_distance(to_latlon(-38, 22), to_latlon(38, 22))  # take-off on 33 rolls toward +x
    assert abs(b33 - 330) < 0.5 and 3000 < length < 3100
    b15, _ = bearing_and_distance(to_latlon(38, 22), to_latlon(-38, 22))
    assert abs(b15 - 150) < 0.5


def test_areas_match_the_scene():
    assert local_areas(-31, 22) == ["Runway 33/15"]          # lined up at the runway 33 end
    assert local_areas(31, 22) == ["Runway 33/15"]           # lined up at the runway 15 end
    assert local_areas(-33, 17.2) == ["B1 hold short (runway 33)"]  # holding short, behind the line
    assert local_areas(-26, 14) == ["Taxiway B"]             # the queue
    assert local_areas(0, 4.5) == ["Taxiway A"]
    assert local_areas(6, 9.2) == []                         # A3 connector: no marked area
    assert local_areas(10, 22, alt=3) == []                  # airborne over the runway


def test_area_polygons_are_closed_lon_lat_rings():
    for _, _, box in AREAS:
        ring = area_polygon(box)["coordinates"][0]
        assert ring[0] == ring[-1] and len(ring) == 5
        assert all(-123 < lon < -122 and 37 < lat < 38 for lon, lat in ring)


def test_without_elastic_positions_are_located_locally():
    res = asyncio.run(Geo(settings=()).locate([{"id": "N123AB", "x": -31, "z": 22, "alt": 0, "state": "lined_up"}]))
    assert res["backend"] == "local" and res["planes"]["N123AB"]["areas"] == ["Runway 33/15"]
    assert asyncio.run(Geo(settings=()).runway_traffic())["planes"] is None
