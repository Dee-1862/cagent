"""The Clearance agent's context: flight plans (Elastic, or local) and the plane's last tower call (its memory)."""

import asyncio

from unstep.cockpit.memory import Doc, LocalMemory
from unstep.live.flightplans import FlightPlans, default_plan, last_tower_call


def test_plans_alternate_runway_ends_and_are_stable_without_elastic():
    plans = FlightPlans(settings=())  # no Elastic: local plans
    a = asyncio.run(plans.get("N123AB", 0))
    b = asyncio.run(plans.get("H456", 1))
    assert (a["runway"], a["route"], a["source"]) == ("33", "Bravo", "local")
    assert b["runway"] == "15"
    assert asyncio.run(plans.get("N123AB", 5))["runway"] == "33"  # first plan sticks
    assert default_plan("X", 2)["summary"] == "departure, runway 33 via Bravo"


class FakeEdge:
    def __init__(self):
        self.memory, self.flight_idx = LocalMemory(), "flight-N123AB"
        self.memory.register_index(self.flight_idx, "cockpit")


def test_last_tower_call_is_the_newest_tower_transmission():
    edge = FakeEdge()

    async def go():
        await edge.memory.add_docs(edge.flight_idx, [
            Doc(id="1", text="Cessna 123 taxi to A3", metadata={"speaker": "atc", "ts": 1000, "type": "heard"}),
            Doc(id="2", text="taxi to A3, Cessna 123", metadata={"speaker": "N123AB", "ts": 2000, "type": "readback"}),
            Doc(id="3", text="Cessna 123 hold short runway 33", metadata={"speaker": "atc", "ts": 3000, "type": "heard"}),
        ], writer="cockpit")
        return await last_tower_call(edge)

    last = asyncio.run(go())
    assert last["text"] == "Cessna 123 hold short runway 33" and last["ts"] == 3000 and last["backend"] == "local"


def test_last_tower_call_skips_calls_to_other_planes():
    edge = FakeEdge()

    async def go():
        await edge.memory.add_docs(edge.flight_idx, [
            Doc(id="1", text="Helicopter four five six, taxi to A3", metadata={"speaker": "atc", "ts": 1000}),
            Doc(id="2", text="Cessna one two three, runway 33, cleared for takeoff", metadata={"speaker": "atc", "ts": 2000}),
        ], writer="cockpit")
        return await last_tower_call(edge, "Helicopter 4-5-6")

    assert asyncio.run(go())["text"] == "Helicopter four five six, taxi to A3"
