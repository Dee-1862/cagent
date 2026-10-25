"""The console's instruction parser, readback check and taxi routing (web/live/atc/instructions.js, taxi.js).

Edge cases come from real demo use: natural phrasing ("clear for takeoff"), a wrong runway in a readback,
"line up and wait" going to the runway end, "taxi to A3" from any state, both runway ends, via Alpha.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ATC = (ROOT / "web/live/atc").as_uri()

SCRIPT = r"""
import assert from "node:assert/strict";
const I = await import("%(atc)s/instructions.js");
const T = await import("%(atc)s/taxi.js");
const p = I.parseInstruction;

// ---- parsing: how people actually say it
assert.deepEqual(p("Cessna 1, 2, 3, clear for takeoff"), {action: "takeoff", runway: null, dest: null, via: []});
assert.equal(p("Cessna one two three, cleared for takeoff runway three three").runway, "33");
assert.equal(p("cessna 123 cleared to take off").action, "takeoff");
assert.deepEqual(p("cessna 1-2-3 clear for departure, line up and wait runway 33"), {action: "line_up", runway: "33", dest: null, via: []});
assert.equal(p("Cessna 123 lineup runway 15").action, "line_up");
assert.deepEqual(p("Helicopter 4 5 6 taxi to A3"), {action: "taxi", runway: null, dest: "A3", via: []});
assert.equal(p("Plane A, taxi to alpha three").dest, "A3");
assert.deepEqual(p("taxi to runway 15 via alpha"), {action: "taxi", runway: "15", dest: null, via: ["A"]});
assert.deepEqual(p("taxi via alpha bravo to a 3").via, ["A", "B"]);
assert.equal(p("taxi via alpha bravo to a 3").dest, "A3");
assert.deepEqual(p("hold short of runway 15"), {action: "hold_short", runway: "15", dest: null, via: []});
assert.equal(p("hold position").action, "stop");
assert.equal(p("Ready for departure runway 33").action, null);

// ---- addressee
const stations = [{id: "N123AB", spoken: "Cessna 1-2-3", name: "Plane A"}, {id: "H456", spoken: "Helicopter 4-5-6", name: "Plane B"}];
assert.equal(I.addressee("Cessna one two three, hold short runway 33", stations).id, "N123AB");
assert.equal(I.addressee("helicopter 456 taxi to a3", stations).id, "H456");
assert.equal(I.addressee("Plane B, line up and wait", stations).id, "H456");
assert.equal(I.addressee("all stations, runway 33 closed", stations), null);

// ---- readbacks
const lineUp = p("Cessna 1-2-3 clear for departure, line up and wait runway 33");
let r = I.checkReadback(lineUp, "line up and wait here for departure runway 13");  // the user's real wrong readback
assert.equal(r.ok, false); assert.deepEqual(r.problems.map((x) => x.field), ["runway"]);
assert.equal(r.problems[0].said, "runway 13"); assert.equal(r.problems[0].expected, "runway 33");
assert.equal(I.checkReadback(lineUp, "Line up and wait runway 33, Cessna 1-2-3").ok, true);
r = I.checkReadback(p("Cessna 123 hold short runway 33"), "runway 33, Cessna 123");
assert.deepEqual(r.problems.map((x) => x.field), ["instruction"]);  // "hold short" must be read back
r = I.checkReadback(p("Cessna 123 taxi to A3"), "taxi to A4, Cessna 123");
assert.deepEqual(r.problems.map((x) => x.field), ["taxiway"]);
assert.equal(I.checkReadback(p("Cessna 123 cleared for takeoff runway 33"), "cleared for takeoff runway three three cessna one two three").ok, true);
r = I.checkReadback(p("Cessna 123 cleared for takeoff runway 33"), "cleared for takeoff runway 15");
assert.equal(r.ok, false);

// ---- routing on the taxiway network
const q0 = T.queueSpot(0), q2 = T.queueSpot(2);
const last = (pts) => pts.at(-1);
const toHold = T.route(q0, T.holdNode("33"));
assert.deepEqual(last(toHold), {x: -33, z: T.HOLD_STOP_Z});
assert.ok(toHold.every((pt) => pt.z >= T.TWY_Z), "plain taxi stays off taxiway A");
// line up and wait goes to the runway END, facing the take-off direction
let lu = T.lineUpRoute(q0, "33");
assert.deepEqual(lu.at(-2), {x: -33, z: T.RWY_Z}); assert.deepEqual(last(lu), {x: -31, z: T.RWY_Z});
lu = T.lineUpRoute(q2, "15");
assert.deepEqual(lu.at(-2), {x: 33, z: T.RWY_Z}); assert.deepEqual(last(lu), {x: 31, z: T.RWY_Z});
assert.ok(lu.some((pt) => pt.x === 33 && pt.z === T.HOLD_STOP_Z), "runway 15 goes through its own hold short (B2)");
// taxi to A3 works from the queue, from a hold short and from a plane lined up on the runway
for (const from of [q0, {x: -33, z: T.HOLD_STOP_Z}, {x: -31, z: T.RWY_Z}]) {
  const pts = T.route(from, T.placeNode("A3"));
  assert.ok(pts.length > 0, JSON.stringify(from));
  assert.deepEqual(last(pts), {x: 6, z: (T.TWY_Z + T.TWYA_Z) / 2});
}
// via Alpha really uses taxiway A, then ends at the hold short
const via = T.route(q0, T.holdNode("33"), {via: ["A"]});
assert.ok(via.some((pt) => pt.z === T.TWYA_Z), "via Alpha runs along A");
assert.deepEqual(last(via), {x: -33, z: T.HOLD_STOP_Z});
// named runway connectors resolve to their hold shorts
assert.equal(T.placeNode("B1"), "HOLD33"); assert.equal(T.placeNode("B2"), "HOLD15"); assert.equal(T.placeNode("C9"), null);

// ---- the Clearance agent's rules
const C = await import("%(atc)s/clearance.js");
assert.equal(C.parseRequest("Tower, Cessna one two three, request taxi"), "taxi");
assert.equal(C.parseRequest("Tower, Cessna 1-2-3, ready for departure runway 33"), "departure");
assert.equal(C.parseRequest("cessna 123 requesting takeoff"), "departure");
assert.equal(C.parseRequest("line up and wait runway 33, Cessna 123"), null);  // a readback is not a request
const plan = {runway: "33", route: "Bravo"}, call = "Cessna 1-2-3";
let pr = C.proposeClearance({callsign: call, request: "taxi", plan, plane: {state: "queue"}});
assert.equal(pr.text, "Cessna 1-2-3, taxi to runway 33 via Bravo, hold short of runway 33");
pr = C.proposeClearance({callsign: call, request: "departure", plan, plane: {state: "queue"}});
assert.match(pr.text, /taxi to runway 33/); assert.match(pr.reason, /isn't at the runway/);
pr = C.proposeClearance({callsign: call, request: "departure", plan, plane: {state: "holding"}, others: [{id: "H456", name: "Plane B", state: "lined_up"}]});
assert.equal(pr.text, "Cessna 1-2-3, hold short of runway 33, traffic on the runway"); assert.match(pr.reason, /Plane B/);
pr = C.proposeClearance({callsign: call, request: "departure", plan, plane: {state: "holding"}, others: [{id: "H456", state: "queue"}]});
assert.equal(pr.text, "Cessna 1-2-3, runway 33, cleared for takeoff");
// the proposals are instructions the console's own parser understands
assert.equal(p("Cessna 1-2-3, runway 33, cleared for takeoff").action, "takeoff");
assert.deepEqual(p("Cessna 1-2-3, taxi to runway 33 via Bravo, hold short of runway 33").via, ["B"]);
console.log("ok");
"""


def test_instruction_parsing_readbacks_and_taxi_routes():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    result = subprocess.run([node, "--input-type=module", "-"], input=SCRIPT % {"atc": ATC},
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
