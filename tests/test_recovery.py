"""C1, tower side: the controller hears who stepped on them and what they said."""

import asyncio

from unstep.contracts import AuditRecord

from tests.test_live_room import make_room, stepped_on, wait_for  # noqa: F401 (fixture)


def test_controller_hears_who_was_blocked_and_what_they_said(make_room):
    async def go():
        room, atc, pilot = await make_room()
        sent = []
        link = room.links["tower"]
        original = link.send

        async def send(msg):
            sent.append(msg)
            return await original(msg)

        link.send = send
        await stepped_on(room)
        await wait_for(lambda: any(m["type"] == "recovery" for m in atc.messages))
        rec = next(m for m in atc.messages if m["type"] == "recovery")
        assert rec["from_station"] == "H456" and rec["to"] == "atc" and rec["kind"] == "blocked_caller"
        assert "request transition" in rec["text"] and rec["text"].startswith("Helicopter")
        assert rec["audio"]  # spoken in Unstep's own voice
        assert not any(m["type"] == "recovery" for m in pilot.messages)  # only the controller
        await wait_for(lambda: any(isinstance(m, AuditRecord) and m.stage == "recovery" for m in sent))
        await room.stop()

    asyncio.run(go())


def test_stale_recovery_is_dropped(make_room, monkeypatch):
    from unstep.live import room as room_mod

    monkeypatch.setattr(room_mod, "RECOVERY_STALE_MS", -1)

    async def go():
        room, atc, pilot = await make_room()
        await stepped_on(room)
        await asyncio.sleep(1.0)
        assert not any(m["type"] == "recovery" for m in atc.messages)
        await room.stop()

    asyncio.run(go())


def test_blocked_pilot_is_told_to_say_again(make_room):
    async def go():
        room, atc, pilot = await make_room()
        calls = []
        for cs, edge in room.edges.items():
            async def notify(event_id, cs=cs, **kw):
                calls.append((cs, event_id))
            edge.notify_blocked = notify
        await stepped_on(room)
        await wait_for(lambda: calls)
        assert [c[0] for c in calls] == ["H456"]  # the helicopter's own call was blocked; tower is not a cockpit
        assert calls[0][1].startswith("rec-tx-")
        await room.stop()

    asyncio.run(go())
