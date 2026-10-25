from unstep.ground import geo


def test_nearest_and_distance():
    p, d = geo.nearest(-33.0, geo.HOLD_STOP_Z - 3)
    assert p.name == "hold short runway 33" and d == 3.0


def test_describe_names_the_line_and_labels_the_map():
    s = geo.describe(-20.0, 14.0, "33")
    assert "hold short runway 33 line" in s and s.endswith("(demo map, not surveyed)")
    assert geo.describe(-33.0, geo.HOLD_STOP_Z, "33").startswith("0 m from hold short runway 33")


def test_unknown_runway_adds_no_line():
    assert "line" not in geo.describe(0, 14, "99")


def test_lat_lon_are_near_the_origin_and_ordered():
    a, b = geo.PLACES[0], geo.PLACES[1]
    assert abs(a.lat - geo.ORIGIN_LAT) < 0.001 and a.lon < b.lon
