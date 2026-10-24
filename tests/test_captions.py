"""Caption keyword tags (live captions): callsign, action, runway, taxiway."""

from unstep.live.captions import keywords, tag


def kinds(text):
    return [(k["text"], k["kind"]) for k in keywords(text)]


def test_spoken_and_written_forms():
    assert kinds("Cessna one two three, hold short runway three three left.") == [
        ("Cessna one two three", "callsign"), ("hold short", "action"), ("runway three three left", "runway")]
    assert kinds("Piper 7-8-9 Runway 28L cleared for takeoff") == [
        ("Piper 7-8-9", "callsign"), ("Runway 28L", "runway"), ("cleared for takeoff", "action")]
    assert kinds("N123AB line up and wait") == [("N123AB", "callsign"), ("line up and wait", "action")]


def test_taxiway_cross_and_niner():
    assert ("Bravo", "taxiway") in kinds("Cessna 1-2-3 taxi via Bravo")
    assert kinds("Helicopter four five six, cross runway two niner") == [
        ("Helicopter four five six", "callsign"), ("cross", "action"), ("runway two niner", "runway")]
    assert ("taxiway Alpha", "taxiway") in kinds("hold short of taxiway Alpha")


def test_every_token_comes_back_once_in_order():
    text = "Tower, Cessna 1-2-3, request taxi to runway three three."
    assert [w["text"] for w in tag(text)] == text.split()
    assert kinds("going to the ramp for fuel") == [] and tag("") == []
    assert tag("Cessna")[0]["kind"] is None  # a type word alone is not a callsign
