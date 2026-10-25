"""The watchers: fixed rules over the radio events, each with its own notices, run side by side."""

import asyncio

from unstep import scenario
from unstep.contracts import ApprovedDirective, ReadbackResult, Slots
from unstep.monitor import Team, default_team
from unstep.monitor.watchers import FlowWatcher, ReadbackWatcher, RunwayWatcher, TrackingWatcher, Watcher

T0 = 1_000_000


def approved(event_id="evt-1", callsign="N123AB", action="hold short", runway="33", at=T0):
    return ApprovedDirective(event_id=event_id, instruction_text=f"{callsign}, {action} runway {runway}",
                             slots=Slots(callsign=callsign, action=action, runway=runway), approved_by="atc",
                             approved_via="click", approved_at=at)


def blocked(callsign="N123AB", n=1):
    return scenario.anomaly_event(event_id=f"evt-b{n}").model_copy(update={"callsign": callsign})


def test_a_missing_readback_is_flagged_once_and_a_good_one_clears_it():
    w = ReadbackWatcher()
    assert w.on_message(approved(), T0) == []
    assert w.tick(T0 + 10_000) == []
    flag = w.tick(T0 + 21_000)
    assert len(flag) == 1 and flag[0]["status"] == "flag" and "has not read back" in flag[0]["text"]
    assert flag[0]["kind"] == "rule" and flag[0]["agent"] == "Readback watcher"
    assert w.tick(T0 + 40_000) == []  # not flagged twice
    done = w.on_message(ReadbackResult(event_id="evt-1", readback_text="hold short 33", match=True), T0 + 41_000)
    assert done[0]["status"] == "done" and done[0]["id"] == flag[0]["id"]  # the same row resolves
    assert w.open_items() == []


def test_a_wrong_readback_is_flagged_with_what_was_said():
    w = ReadbackWatcher()
    w.on_message(approved(), T0)
    out = w.on_message(ReadbackResult(event_id="evt-1", readback_text="cleared to cross", match=False, attempt=2), T0 + 5000)
    assert out[0]["status"] == "flag" and "attempt 2" in out[0]["text"] and "cleared to cross" in out[0]["detail"]


def test_two_aircraft_cleared_into_one_runway_is_a_flag_only():
    w = RunwayWatcher()
    assert w.on_message(approved("e1", "N123AB", "cleared to land", "33"), T0) == []
    out = w.on_message(approved("e2", "H456", "cleared for takeoff", "33", T0 + 20_000), T0 + 20_000)
    assert out[0]["status"] == "flag" and "N123AB" in out[0]["text"] and "H456" in out[0]["text"]
    assert "Flag only" in out[0]["detail"]
    assert w.on_message(approved("e3", "H456", "cleared for takeoff", "28", T0), T0 + 21_000) == []  # other runway
    assert w.on_message(approved("e4", "N999", "hold short", "33"), T0 + 22_000) == []  # restrictive: not a clearance in


def test_a_runway_clearance_stops_counting_after_it_expires_and_the_same_aircraft_is_not_a_conflict():
    w = RunwayWatcher()
    w.on_message(approved("e1", "N123AB", "cleared to land", "33"), T0)
    assert w.on_message(approved("e2", "N123AB", "cleared to land", "33"), T0 + 1000) == []
    assert w.on_message(approved("e3", "H456", "cleared to land", "33"), T0 + 200_000) == []  # long after


def test_a_stuck_key_is_flagged_and_clears_on_release():
    w = TrackingWatcher()
    w.on_note("key", {"station": "N123AB", "down": True}, T0)
    assert w.tick(T0 + 5000) == []
    flag = w.tick(T0 + 16_000)
    assert flag[0]["status"] == "flag" and "held the key" in flag[0]["text"]
    assert w.tick(T0 + 30_000) == []
    assert w.open_items()
    done = w.on_note("key", {"station": "N123AB", "down": False}, T0 + 31_000)
    assert done[0]["status"] == "done" and done[0]["id"] == flag[0]["id"] and w.open_items() == []


def test_the_same_aircraft_stepped_on_again_is_noticed():
    w = TrackingWatcher()
    assert w.on_message(blocked("N123AB", 1), T0) == []
    out = w.on_message(blocked("N123AB", 2), T0 + 60_000)
    assert out[0]["status"] == "flag" and "2 times" in out[0]["text"]
    assert w.on_message(blocked("H456", 3), T0 + 61_000) == []


def test_a_busy_frequency_is_flagged_and_clears():
    w = FlowWatcher()
    assert w.on_message(blocked("A", 1), T0) == [] and w.on_message(blocked("B", 2), T0 + 1000) == []
    flag = w.on_message(blocked("C", 3), T0 + 2000)
    assert flag[0]["status"] == "flag" and "busy" in flag[0]["text"]
    assert w.on_message(blocked("D", 4), T0 + 3000) == []  # still busy: no repeat
    done = w.tick(T0 + 120_000)
    assert done[0]["status"] == "done" and done[0]["id"] == flag[0]["id"]


def test_rows_use_the_agreed_feed_format():
    row = ReadbackWatcher().on_message(approved(), T0) or ReadbackWatcher()
    w = ReadbackWatcher()
    w.on_message(approved(), T0)
    row = w.tick(T0 + 25_000)[0]
    assert set(row) == {"type", "id", "ts", "agent", "kind", "station", "event_id", "status", "text", "detail", "sponsor"}
    assert row["type"] == "agent_action" and row["kind"] == "rule" and row["status"] in ("done", "needs_you", "flag")


class Boom(Watcher):
    name = "Boom"

    def on_message(self, msg, now):
        raise RuntimeError("bad watcher")


def test_the_watchers_run_side_by_side_and_one_failing_does_not_stop_the_others():
    rows = []

    async def go():
        clock = {"now": T0}

        async def emit(row):
            rows.append(row)

        team = Team([Boom(), ReadbackWatcher(), RunwayWatcher(), TrackingWatcher(), FlowWatcher()], emit,
                    lambda: clock["now"], tick_s=0.02)
        team.start()
        team.feed(approved("e1", "N123AB", "cleared to land", "33", T0))
        team.feed(approved("e2", "H456", "cleared for takeoff", "33", T0 + 1000))
        team.note("key", station="N123AB", down=True)
        await asyncio.sleep(0.1)
        clock["now"] = T0 + 30_000
        await asyncio.sleep(0.1)
        items = team.open_items()
        await team.stop()
        return team, items

    team, items = asyncio.run(go())
    agents = {r["agent"] for r in rows}
    assert {"Runway watcher", "Readback watcher", "Tracking watcher"} <= agents  # three kinds of notice, side by side
    assert team.errors["Boom"] >= 1 and "Boom" not in agents
    assert items


def test_the_default_team_has_the_four_watchers():
    team = default_team(lambda row: None, lambda: T0)
    assert [w.name for w in team.watchers] == ["Readback watcher", "Runway watcher", "Tracking watcher", "Flow watcher"]


def test_the_room_runs_the_watchers_when_switched_on_and_posts_their_rows_to_the_console(monkeypatch):
    from tests.test_live_join import FakeBrowser, room as make_join_room

    monkeypatch.setenv("UNSTEP_WATCHERS", "1")
    r = make_join_room(monkeypatch)

    async def go():
        await r.start()
        assert r.watchers is not None
        r.watchers.tick_s = 0.05
        next(w for w in r.watchers.watchers if w.name == "Tracking watcher").stuck_ms = 100
        atc = FakeBrowser()
        await r.join("atc", atc)
        r._key("N123AB", True)  # a plane keys up and never lets go
        await asyncio.sleep(0.5)
        rows = [m for m in atc.messages if m.get("type") == "agent_action"]
        assert rows and rows[0]["agent"] == "Tracking watcher" and rows[0]["status"] == "flag"
        r._key("N123AB", False)
        await asyncio.sleep(0.2)
        rows = [m for m in atc.messages if m.get("type") == "agent_action"]
        assert rows[-1]["status"] == "done" and rows[-1]["id"] == rows[0]["id"]
        await r.stop()

    asyncio.run(go())


def test_the_room_has_no_watchers_by_default(monkeypatch):
    from tests.test_live_join import room as make_join_room

    monkeypatch.delenv("UNSTEP_WATCHERS", raising=False)
    r = make_join_room(monkeypatch)

    async def go():
        await r.start()
        assert r.watchers is None
        await r.stop()

    asyncio.run(go())
