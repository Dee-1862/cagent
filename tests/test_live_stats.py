"""W4: per-frequency stats for the console, from Elastic ES|QL or the room's own traces."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from unstep.clock import now_ms
from unstep.ground import stats
from unstep.live.app import create_live_app

from tests.test_live_join import room as make_join_room
from tests.test_live_room import make_room, only_trace, stepped_on, wait_for  # noqa: F401 (fixture)


def traces():
    return {
        "e1": {"event_id": "e1", "callsign": "N123AB", "created_ms": 2000, "readbacks": [{"match": False}, {"match": True}],
               "decision": {"approved_via": "auto"}},
        "e2": {"event_id": "e2", "callsign": "N123AB", "created_ms": 3000, "readbacks": [], "decision": None},
        "e3": {"event_id": "e3", "callsign": "H456", "created_ms": 4000, "readbacks": [{"match": True}],
               "decision": {"approved_via": "click"}},
        "old": {"event_id": "old", "callsign": "H456", "created_ms": 10, "readbacks": [{"match": False}]},
    }


def test_queries_inline_only_checked_values():
    events, outcomes = stats.esql_queries("118.700", 1234, index="unstep-events")
    assert 'frequency == "118.700"' in events and "ts >= 1234" in events and events.startswith("FROM unstep-events")
    assert 'approved_via == "auto"' in outcomes and "BY event_id" in outcomes
    with pytest.raises(ValueError):
        stats.esql_queries('118.7" OR true', 0)


def test_local_stats_count_since_and_per_callsign():
    s = stats.local_stats(traces(), since_ms=1000)
    assert (s["blocked_calls"], s["readback_errors"], s["auto_resends"]) == (3, 1, 1)
    assert s["per_callsign"][0] == {"callsign": "N123AB", "blocked": 2, "readback_errors": 1, "auto_resends": 1}
    assert s["per_callsign"][1]["callsign"] == "H456"


def es_transport(seen, fail=False):
    def handler(request):
        seen.append(request)
        if fail:
            return httpx.Response(503)
        q = json.loads(request.content)["query"]
        if "AnomalyEvent" in q:
            return httpx.Response(200, json={"columns": [{"name": "n", "type": "long"}, {"name": "event_id", "type": "keyword"},
                                                         {"name": "callsign", "type": "keyword"}],
                                             "values": [[1, "e1", "N123AB"], [1, "e3", "H456"]]})
        return httpx.Response(200, json={"columns": [{"name": "readback_errors", "type": "long"},
                                                     {"name": "auto_resends", "type": "long"},
                                                     {"name": "event_id", "type": "keyword"}],
                                         "values": [[2, 1, "e1"], [0, 0, "e3"], [5, 5, "other-frequency"]]})
    return httpx.MockTransport(handler)


def test_elastic_backend_joins_outcomes_to_this_frequencys_events():
    seen = []
    s = asyncio.run(stats.frequency_stats("118.7", 0, traces(), settings=("https://es.example", "k"),
                                          transport=es_transport(seen)))
    assert s["backend"] == "elastic" and s["took_ms"] is not None
    assert (s["blocked_calls"], s["readback_errors"], s["auto_resends"]) == (2, 2, 1)
    assert [r.url.path for r in seen] == ["/_query", "/_query"]
    assert seen[0].headers["authorization"] == "ApiKey k"
    assert "FROM" in s["esql"] and s["frequency"] == "118.7" and s["since_ms"] == 0


def test_elastic_failure_falls_back_to_local():
    s = asyncio.run(stats.frequency_stats("118.7", 1000, traces(), settings=("https://es.example", "k"),
                                          transport=es_transport([], fail=True)))
    assert s["backend"] == "local" and s["elastic_error"] == "HTTPStatusError" and s["blocked_calls"] == 3


def test_endpoint_counts_a_real_stepped_on_call(make_room, monkeypatch):
    monkeypatch.setattr(stats, "elastic_settings", lambda: None)

    async def go():
        room, atc, pilot = await make_room()
        start = now_ms()
        await stepped_on(room)
        await wait_for(lambda: only_trace(room) and only_trace(room)["status"] in ("auto_relayed", "delivered",
                                                                                   "needs_you"))
        s = await stats.frequency_stats(room.frequency, start - 60_000, room.traces)
        assert s["backend"] == "local" and s["blocked_calls"] == 1
        assert s["per_callsign"][0]["callsign"] == "N123AB"
        assert (await stats.frequency_stats(room.frequency, now_ms() + 1000, room.traces))["blocked_calls"] == 0
        await room.stop()

    asyncio.run(go())


def test_live_stats_route(monkeypatch):
    monkeypatch.setattr(stats, "elastic_settings", lambda: None)
    r = make_join_room(monkeypatch)
    with TestClient(create_live_app(live=False, room=r)) as client:
        body = client.get("/live/stats?since_ms=0").json()
    assert body["backend"] == "local" and body["blocked_calls"] == 0 and body["frequency"] == r.frequency
    assert set(body) >= {"window_s", "esql", "readback_errors", "auto_resends", "per_callsign", "since_ms"}
