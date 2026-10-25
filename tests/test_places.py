from unstep.ground import places


def test_nearest_and_distance_use_the_shared_scale():
    p, d = places.nearest(-33.0, places.HOLD_STOP_Z - 0.1)
    assert p.name == "hold short runway 33" and d == 4.0  # 0.1 unit at 40 m per unit


def test_describe_names_the_line_and_labels_the_map():
    s = places.describe(-20.0, 14.0, "33")
    assert "hold short runway 33 line" in s and s.endswith("(demo map, not surveyed)")
    assert places.describe(-33.0, places.HOLD_STOP_Z, "33").startswith("0 m from hold short runway 33")


def test_unknown_runway_adds_no_line():
    assert "line" not in places.describe(0, 14, "99")


def test_places_have_real_coordinates():
    lat, lon = places.PLACES[0].latlon
    assert 37.8 < lat < 37.9 and -122.4 < lon < -122.2


def test_to_scene_inverts_to_latlon_and_describes_a_stored_position():
    lat, lon = places.to_latlon(-20.0, 14.0)
    x, z = places.to_scene(lat, lon)
    assert abs(x + 20.0) < 0.01 and abs(z - 14.0) < 0.01
    text = places.describe_position({"lat": lat, "lon": lon, "areas": ["Taxiway B"]}, "33")
    assert text.startswith("In Taxiway B; ") and "hold short runway 33 line" in text and "demo map" in text
    assert places.describe_position({"lat": lat, "lon": lon, "areas": []}).startswith("Off the mapped areas; ")


def test_the_room_words_where_a_plane_is_only_from_a_fresh_position(monkeypatch):
    import time
    from types import SimpleNamespace

    from tests.test_live_join import room as make_room

    r = make_room(monkeypatch)
    s = next(x for x in r.stations.values() if x.kind == "aircraft")
    lat, lon = places.to_latlon(-20.0, 14.0)
    r.geo = SimpleNamespace(latest={s.id: {"lat": lat, "lon": lon, "areas": ["Taxiway B"], "at": time.monotonic()}})
    text = r._where_is({"callsign": s.callsign}, {"slots": {"runway": "33"}})
    assert text.startswith("In Taxiway B; ") and "demo map" in text
    r.geo.latest[s.id]["at"] -= 60
    assert r._where_is({"callsign": s.callsign}, {}) is None  # stale: say nothing
    r.geo = None
    assert r._where_is({"callsign": s.callsign}, {}) is None


def test_console_page_tells_the_page_which_hub_to_open_its_socket_to(monkeypatch):
    from fastapi.testclient import TestClient

    from tests.test_live_join import room as make_room
    from unstep.live.app import create_live_app

    monkeypatch.setenv("UNSTEP_PUBLIC_URL", "https://unstep.onrender.com")
    with TestClient(create_live_app(live=False, room=make_room(monkeypatch))) as client:
        html = client.get("/live/atc/").text
    assert 'window.UNSTEP_HUB_HOST = "unstep.onrender.com"' in html and "__UNSTEP" not in html


def test_every_proposal_trace_gets_where_the_plane_was_without_the_agents(monkeypatch):
    import asyncio
    import time
    from types import SimpleNamespace

    from tests.test_live_join import room as make_room
    from unstep import scenario
    from unstep.contracts import Envelope

    r = make_room(monkeypatch)
    s = next(x for x in r.stations.values() if x.kind == "aircraft")
    proposal = scenario.proposed_directive()
    lat, lon = places.to_latlon(-20.0, 14.0)
    r.geo = SimpleNamespace(latest={s.id: {"lat": lat, "lon": lon, "areas": ["Taxiway B"], "at": time.monotonic()}})
    r.traces[proposal.event_id] = {"event_id": proposal.event_id, "callsign": s.callsign, "status": "detected",
                                   "steps": [], "proposal": None, "timings": []}
    asyncio.run(r._observe(Envelope(type="ProposedDirective", ts=1, data={}), proposal))
    steps = r.traces[proposal.event_id]["steps"]
    assert any("Where the plane was: In Taxiway B" in str(st) for st in steps), steps
