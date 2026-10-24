"""Demo seed data (task A4): the airport index and the N123AB flight session.

The flight session holds the earlier taxi clearance ("Runway 33, taxi via Bravo",
clr-0007) that the local hint is drawn from, so the hint has a visible source
instead of looking hardcoded (M-014).
"""

from __future__ import annotations

from unstep.cockpit.memory import Doc, Memory, MossMemory, airport_index, flight_index
from unstep.scenario import CALLSIGN, FREQUENCY, T0

AIRPORT_ICAO = "KUNS"  # fictional demo field
PREFLIGHT = "preflight"
COCKPIT = "cockpit"


def airport_docs() -> list[Doc]:
    def doc(i, kind, text, **meta):
        return Doc(id=i, text=text, metadata={"type": kind, "airport": AIRPORT_ICAO, **meta})

    return [
        doc("rwy-33-15", "runway", "Runway 33/15, 7000 ft, active for departures Runway 33", runway="33"),
        doc("rwy-28l-10r", "runway", "Runway 28L/10R, 9000 ft, active for arrivals Runway 28L", runway="28L"),
        doc("twy-alpha", "taxiway", "Taxiway Alpha runs parallel to Runway 28L, connects to the ramp"),
        doc("twy-bravo", "taxiway", "Taxiway Bravo leads from the ramp to the Runway 33 hold short line at B4", runway="33"),
        doc("twy-charlie", "taxiway", "Taxiway Charlie crosses Runway 28L at C2, hold short line on both sides", runway="28L"),
        doc("notam-0012", "notam", "NOTAM: Taxiway Alpha closed between A3 and A4 for construction"),
        doc("phr-hold-short", "phraseology", "Hold short of Runway 33: stop before the runway hold short line and wait"),
        doc("phr-say-again", "phraseology", "Say again: request the controller repeat the last transmission"),
    ]


def flight_docs(callsign: str = CALLSIGN, t0: int = T0) -> list[Doc]:
    def clr(i, text, minutes_ago, **meta):
        return Doc(
            id=i,
            text=text,
            metadata={"callsign": callsign, "type": "clearance", "frequency": FREQUENCY,
                      "ts": t0 - minutes_ago * 60_000, **meta},
        )

    return [
        clr("clr-0005", "Cessna 1-2-3, Unstep Ground, information Bravo, altimeter 2992", 6),
        clr("clr-0006", "Cessna 1-2-3, VFR departure to the north approved", 5),
        clr("clr-0007", "Cessna 1-2-3, Runway 33, taxi via Bravo", 3, runway="33", route="Bravo"),
    ]


async def seed(memory: Memory, callsign: str = CALLSIGN, t0: int = T0) -> tuple[str, str]:
    """Register owners and load both indexes. Returns (airport index, flight index)."""
    a, f = airport_index(AIRPORT_ICAO), flight_index(callsign)
    memory.register_index(a, PREFLIGHT)
    memory.register_index(f, COCKPIT)
    if isinstance(memory, MossMemory):
        await memory.load_airport(a)
    else:
        await memory.add_docs(a, airport_docs(), writer=PREFLIGHT)
    await memory.add_docs(f, flight_docs(callsign, t0), writer=COCKPIT)
    return a, f
