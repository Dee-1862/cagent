"""Frequency Monitor (task A5): insight rules, dedupe, freq index ownership,
transcript matching, and gateway routing (insights reach the dashboard, never the cockpit).
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from unstep import scenario
from unstep.cockpit.memory import Doc, LocalMemory
from unstep.cockpit.monitor import WRITER, FrequencyMonitor, freq_index
from unstep.contracts import Insight, ReadbackResult, TowerTranscript, unwrap, wrap
from unstep.gateway.server import ROUTES, create_app
from unstep.gateway.sink import MemorySink

T0 = scenario.T0
MIN = 60_000
FREQ = scenario.FREQUENCY


def run(coro):
    return asyncio.run(coro)


def event(eid, t, callsign="N123AB", frequency=FREQ):
    return scenario.anomaly_event(event_id=eid, t0=t).model_copy(
        update={"callsign": callsign, "frequency": frequency})


def readback(eid, match=False):
    return ReadbackResult(event_id=eid, readback_text="hold short 33", match=match)


@pytest.fixture
def mon():
    return FrequencyMonitor(LocalMemory())


def test_repeated_blocked_calls(mon):
    assert mon.on_anomaly(event("e1", T0)) == []
    out = mon.on_anomaly(event("e2", T0 + 4 * MIN))
    assert [i.kind for i in out] == ["repeated_blocked_calls"]
    assert out[0].text == "N123AB has had 2 blocked calls in 5 minutes."
    assert out[0].callsign == "N123AB" and out[0].frequency == FREQ
    assert out[0].ts == T0 + 4 * MIN + 40  # message clock, not wall clock


def test_blocked_calls_outside_window_do_not_count(mon):
    mon.on_anomaly(event("e1", T0))
    assert mon.on_anomaly(event("e2", T0 + 6 * MIN)) == []


def test_duplicate_event_counted_once(mon):
    mon.on_anomaly(event("e1", T0))
    assert mon.on_anomaly(event("e1", T0)) == []


def test_dedupe_within_window_then_fires_again(mon):
    mon.on_anomaly(event("e1", T0))
    assert len(mon.on_anomaly(event("e2", T0 + MIN))) == 1
    kinds = [i.kind for i in mon.on_anomaly(event("e3", T0 + 2 * MIN))]
    assert "repeated_blocked_calls" not in kinds  # same key, inside 5 min (congestion may fire)
    later = mon.on_anomaly(event("e4", T0 + 7 * MIN))  # e3 + e4 in window, last fire > 5 min ago
    assert "repeated_blocked_calls" in [i.kind for i in later]


def test_frequency_congestion(mon):
    assert mon.on_anomaly(event("a", T0, callsign="N1")) == []
    assert mon.on_anomaly(event("b", T0 + MIN, callsign="N2")) == []
    out = mon.on_anomaly(event("c", T0 + 2 * MIN, callsign="N3"))
    assert [i.kind for i in out] == ["frequency_congestion"]
    assert out[0].callsign is None and "3 blocked calls" in out[0].text
    assert mon.on_anomaly(event("d", T0 + 3 * MIN, callsign="N4")) == []  # deduped
    # Other frequencies are independent.
    assert mon.on_anomaly(event("x", T0, callsign="N9", frequency="121.900")) == []


def test_readback_errors_rising(mon):
    mon.on_anomaly(event("e1", T0, callsign="N1"))
    mon.on_anomaly(event("e2", T0 + 6 * MIN, callsign="N2"))
    assert mon.on_readback(readback("e1", match=True), T0 + MIN) == []
    assert mon.on_readback(readback("e1"), T0 + MIN) == []
    out = mon.on_readback(readback("e2"), T0 + 9 * MIN)
    assert [i.kind for i in out] == ["readback_errors_rising"]
    assert out[0].frequency == FREQ and out[0].callsign == "N2"
    assert mon.on_readback(readback("e2"), T0 + 10 * MIN) == []  # deduped


def test_readback_errors_window_and_unknown_event(mon):
    mon.on_anomaly(event("e1", T0))
    mon.on_readback(readback("e1"), T0)
    assert mon.on_readback(readback("e1"), T0 + 11 * MIN) == []  # first error aged out
    assert mon.on_readback(readback("nope"), T0) == []  # no frequency to attribute it to


def test_transcript_written_to_freq_index_by_owner_only(mon):
    run(mon.on_transcript(scenario.tower_transcript()))
    mem = mon.memory
    doc = mem.indexes[freq_index(FREQ)]["tx-0001"]
    assert doc.text == "Cessna 1-2-3, hold short Runway 33"
    assert doc.metadata == {"frequency": FREQ, "ts": T0, "callsign": "N123AB"}
    assert mem.owners[freq_index(FREQ)] == WRITER
    with pytest.raises(PermissionError):
        run(mem.add_docs(freq_index(FREQ), [Doc(id="x", text="forged")], writer="cockpit"))
    with pytest.raises(PermissionError):
        mem.register_index(freq_index(FREQ), "cockpit")


def test_match_transcript(mon):
    run(mon.on_transcript(scenario.tower_transcript()))
    other = TowerTranscript(transcript_id="tx-0002", frequency=FREQ, callsign="N456CD",
                            ptt_start=T0 + 500, ptt_end=T0 + 2000, text="Cessna 4-5-6, hold short Runway 33")
    old = TowerTranscript(transcript_id="tx-0000", frequency=FREQ, callsign="N123AB",
                          ptt_start=T0 - 10 * MIN, ptt_end=T0 - 10 * MIN + 2000,
                          text="Cessna 1-2-3, taxi to Runway 33 via Bravo")
    run(mon.on_transcript(other))
    run(mon.on_transcript(old))

    ev = scenario.anomaly_event()
    m = run(mon.match_transcript("N123AB", ev.squelch_open, text=ev.heard_text))
    assert m.doc is not None and m.doc.id == "tx-0001"
    assert m.moss_ms >= 0 and m.backend == "local"

    # Out of the time window, or a callsign never heard: no match.
    assert run(mon.match_transcript("N123AB", T0 + 30 * MIN, text=ev.heard_text)).doc is None
    assert run(mon.match_transcript("N999ZZ", T0, text=ev.heard_text)).doc is None


def test_insights_route_to_dashboard_only():
    assert ROUTES["Insight"] == {"dashboard"}


def test_gateway_monitor_insight_reaches_dashboard_not_cockpit():
    client = TestClient(create_app(MemorySink()))
    mon = FrequencyMonitor(LocalMemory())
    with client.websocket_connect("/ws/cockpit") as cockpit, \
         client.websocket_connect("/ws/monitor") as monitor, \
         client.websocket_connect("/ws/dashboard") as dashboard:
        insights = []
        for i, t in enumerate((T0, T0 + MIN)):
            cockpit.send_text(wrap(event(f"g{i}", t)))
            env, msg = unwrap(monitor.receive_text())
            insights += run(mon.handle(msg, env.ts))
            unwrap(dashboard.receive_text())  # the AnomalyEvent
        assert len(insights) == 1
        monitor.send_text(wrap(insights[0]))

        got = unwrap(dashboard.receive_text())[1]
        assert isinstance(got, Insight) and got.kind == "repeated_blocked_calls"
        assert got.text == "N123AB has had 2 blocked calls in 5 minutes."

        # Probe: the next thing the cockpit sees is its own error, not the insight.
        cockpit.send_text(json.dumps({"type": "Nope", "data": {}}))
        assert json.loads(cockpit.receive_text())["type"] == "Error"
