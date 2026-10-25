"""End-to-end taxi and readback edge cases on a live hub, following real ATC procedure.

Planes act only after the pilot's readback (JO 7110.65 2-4-3, AIM 4-3); "hold position" acts at once.

Start a hub first:  python -m unstep.live --port 8796 --no-browser
Then:              python scripts/e2e_taxi.py
Tower lines are typed on the console; the two pilots are websocket clients that can speak.
"""
import asyncio
import json
import sys
import threading
from pathlib import Path

import websockets
from playwright.sync_api import sync_playwright

H = "http://localhost:8796"
WS = "ws://127.0.0.1:8796/live/ws/"
OUT = Path(__file__).resolve().parent.parent / "data"
results = []

loop = asyncio.new_event_loop()
sockets = {}


async def pilot(station):
    async with websockets.connect(WS + station) as ws:
        sockets[station] = ws
        async for _ in ws:
            pass


def start_pilots():
    asyncio.set_event_loop(loop)
    loop.run_until_complete(asyncio.gather(pilot("N123AB"), pilot("H456")))


threading.Thread(target=start_pilots, daemon=True).start()


def pilot_says(station, text):
    asyncio.run_coroutine_threadsafe(sockets[station].send(json.dumps({"type": "say", "text": text})), loop).result(5)


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--ignore-gpu-blocklist"])
    atc = b.new_page(viewport={"width": 1600, "height": 900})
    atc.goto(H + "/live/atc/", wait_until="networkidle")
    atc.wait_for_timeout(6000)

    def planes():
        return {e["id"]: e for e in atc.evaluate("window.unstepAirport ? window.unstepAirport.inspect() : []")}

    def tower(text):
        atc.locator("#say").fill(text)
        atc.locator("#transmit").click()

    def wait_for(pred, timeout=30):
        for _ in range(int(timeout * 2)):
            atc.wait_for_timeout(500)
            ps = planes()
            if pred(ps):
                return ps
        return planes()

    def feed_has(snippet):
        return atc.evaluate(f"[...document.querySelectorAll('#feed .feed-row')].some(r => r.textContent.includes({json.dumps(snippet)}))")

    names = {"N123AB": "Plane A", "H456": "Plane B"}

    def await_readback_window(station, timeout=25):
        """A pilot reads back after hearing the call: wait until the console says it is waiting for this plane."""
        for _ in range(timeout * 2):
            if feed_has(f"{names[station]} was told"):
                return
            atc.wait_for_timeout(500)

    def tower_then_readback(station, instruction, readback):
        tower(instruction)
        atc.wait_for_timeout(1500)
        await_readback_window(station)
        pilot_says(station, readback)

    ps = wait_for(lambda ps: {"N123AB", "H456"} <= set(ps), 20)
    check("both planes spawn in the queue", all(ps.get(i, {}).get("state") == "queue" for i in ("N123AB", "H456")), str(ps))
    a, h = ps.get("N123AB", {}), ps.get("H456", {})
    check("queue is on taxiway B, Plane A ahead (west) of Plane B", a.get("z") == 14 and h.get("z") == 14 and a.get("x", 0) < h.get("x", 0), f"A {a} B {h}")

    geo = any(feed_has("in Taxiway B at 37.") or atc.wait_for_timeout(500) for _ in range(20))
    check("geo: the queue is located on Taxiway B with real coordinates (Elastic geo_shape)", geo and feed_has("Elastic geo_shape"))

    # 1. no movement before the readback
    tower("Cessna 1, 2, 3, clear for departure, line up and wait runway 33")
    atc.wait_for_timeout(7000)
    check("an instruction alone doesn't move the plane (waits for the readback)", planes()["N123AB"]["state"] == "queue", str(planes()["N123AB"]))
    waiting = any(feed_has("Waiting for the readback") or atc.wait_for_timeout(500) for _ in range(20))
    check("the feed says it's waiting for the readback", waiting)

    # 2. the user's real wrong readback: flagged, plane stays put
    pilot_says("N123AB", "line up and wait here for departure runway 13")
    atc.wait_for_timeout(5000)
    check("wrong readback (runway 13 vs 33) flagged in the feed", feed_has("Wrong readback from Plane A"))
    check("after a wrong readback the plane stays put", planes()["N123AB"]["state"] == "queue", str(planes()["N123AB"]))

    # 3. corrected readback: now it goes, to the runway 33 END
    pilot_says("N123AB", "line up and wait runway 33, Cessna one two three")
    ps = wait_for(lambda ps: ps["N123AB"]["state"] == "lined_up", 40)
    a = ps["N123AB"]
    check("corrected readback -> lined up at the runway 33 end", a["state"] == "lined_up" and a["x"] <= -30 and a["z"] == 22, str(a))
    check("Plane B moved up to the front of the queue", ps["H456"]["x"] == -26, str(ps["H456"]))

    # 4. taxi to A3 from the runway
    tower_then_readback("N123AB", "Cessna 123, taxi to A3", "taxi to alpha three, Cessna one two three")
    ps = wait_for(lambda ps: abs(ps["N123AB"]["x"] - 6) < .2 and abs(ps["N123AB"]["z"] - 9.2) < .3, 40)
    check("taxi to A3 (from the runway) arrives at A3", abs(ps["N123AB"]["x"] - 6) < .2 and abs(ps["N123AB"]["z"] - 9.2) < .3, str(ps["N123AB"]))
    check("correct readback marked in the feed", feed_has("Plane A read it back correctly"))

    # 5. the other runway end: runway 15
    tower_then_readback("H456", "Helicopter 4 5 6, line up and wait runway 15", "line up and wait runway one five, helicopter four five six")
    ps = wait_for(lambda ps: ps["H456"]["state"] == "lined_up", 50)
    hh = ps["H456"]
    check("line up and wait runway 15 -> lined up at the 15 end", hh["state"] == "lined_up" and hh["x"] >= 30 and hh["z"] == 22, str(hh))
    tower_then_readback("H456", "Helicopter 456 cleared for takeoff runway 15", "cleared for takeoff runway 15, helicopter 456")
    ps = wait_for(lambda ps: ps["H456"]["alt"] > 1, 40)
    check("takeoff from runway 15 rolls west and climbs", ps["H456"]["alt"] > 1 and ps["H456"]["x"] < 30, str(ps["H456"]))

    # 6. taxi via Alpha to the runway 33 hold short, then takeoff on 33
    tower_then_readback("N123AB", "Cessna 123 taxi to runway 33 via alpha", "taxi to runway 33 via alpha, Cessna 123")
    seen_a = False
    for _ in range(90):
        atc.wait_for_timeout(500)
        cur = planes()["N123AB"]
        seen_a = seen_a or abs(cur["z"] - 4.5) < .3
        if cur["state"] == "holding":
            break
    cur = planes()["N123AB"]
    check("taxi via alpha travels along taxiway A", seen_a, str(cur))
    check("...and ends holding short of runway 33", cur["state"] == "holding" and cur["x"] == -33, str(cur))
    tower_then_readback("N123AB", "Cessna 123 cleared for takeoff runway 33", "cleared for takeoff runway 33, Cessna 123")
    ps = wait_for(lambda ps: ps["N123AB"]["alt"] > 1, 40)
    check("takeoff from the 33 end rolls east and climbs", ps["N123AB"]["alt"] > 1 and ps["N123AB"]["x"] > -31, str(ps["N123AB"]))
    ps = wait_for(lambda ps: ps["N123AB"]["state"] == "queue", 30)
    check("after departing, the plane rejoins the back of the queue", ps["N123AB"]["state"] == "queue", str(ps["N123AB"]))

    # 7. hold position acts at once, no readback needed
    tower_then_readback("N123AB", "Cessna 123 taxi to A4", "taxi to A4, Cessna 123")
    wait_for(lambda ps: ps["N123AB"]["state"] == "taxi", 20)
    tower("Cessna 123 hold position")
    p1 = wait_for(lambda ps: ps["N123AB"]["state"] == "stopped", 15)["N123AB"]
    atc.wait_for_timeout(2500); p2 = planes()["N123AB"]
    check("hold position stops the plane at once, without a readback", p1["state"] == "stopped" and p1["x"] == p2["x"] and p1["z"] == p2["z"], f"{p1} {p2}")

    # 8. the Clearance agent: request -> proposal from the flight plan -> controller sends -> readback -> moves
    def proposal(timeout=20):
        for _ in range(timeout * 2):
            cards = atc.locator("#requests .clearance .proposal")
            if cards.count():
                return cards.first.inner_text(), atc.locator("#requests .clearance").first.inner_text()
            atc.wait_for_timeout(500)
        return "", ""

    def send_proposal():
        atc.locator("#requests .clearance button.approve").first.click()

    pilot_says("N123AB", "Tower, Cessna one two three, request taxi")
    text, card = proposal()
    check("request taxi -> the agent proposes a taxi clearance to its runway", "taxi to runway 33 via Bravo, hold short of runway 33" in text, text)
    check("...using the flight plan from Elastic", "Elastic" in card, card[:200])
    send_proposal()
    atc.wait_for_timeout(1500)
    await_readback_window("N123AB")
    pilot_says("N123AB", "taxi to runway 33 via bravo, hold short of runway 33, Cessna 123")
    ps = wait_for(lambda ps: ps["N123AB"]["state"] == "holding", 60)
    check("sent clearance + readback -> holding short of runway 33", ps["N123AB"]["state"] == "holding" and ps["N123AB"]["x"] == -33, str(ps["N123AB"]))

    tower_then_readback("H456", "Helicopter 456 line up and wait runway 15", "line up and wait runway 15, helicopter 456")
    wait_for(lambda ps: ps["H456"]["state"] == "lined_up", 60)
    pilot_says("N123AB", "Tower, Cessna one two three, ready for departure runway 33")
    atc.wait_for_timeout(1500)
    text, card = proposal()
    check("ready for departure with traffic on the runway -> hold short", "hold short of runway 33, traffic on the runway" in text, text)
    check("...because Elastic's geo query found Plane B inside the runway area", "Elastic geo: Plane B" in card, card[:400])
    atc.locator("#requests .clearance button.reject").first.click()

    tower_then_readback("H456", "Helicopter 456 cleared for takeoff runway 15", "cleared for takeoff runway 15, helicopter 456")
    wait_for(lambda ps: ps["H456"]["alt"] > 1, 40)
    pilot_says("N123AB", "Tower, Cessna one two three, ready for departure")
    atc.wait_for_timeout(1500)
    text, card = proposal()
    check("ready for departure with the runway clear -> cleared for takeoff", "runway 33, cleared for takeoff" in text, text)
    check("...with the runway area clear by Elastic geo", "Runway: clear (Elastic geo" in card, card[:400])
    send_proposal()
    atc.wait_for_timeout(1500)
    await_readback_window("N123AB")
    pilot_says("N123AB", "runway 33 cleared for takeoff, Cessna 123")
    ps = wait_for(lambda ps: ps["N123AB"]["alt"] > 1, 50)
    check("sent takeoff clearance + readback -> Plane A departs", ps["N123AB"]["alt"] > 1, str(ps["N123AB"]))

    OUT.mkdir(exist_ok=True)
    atc.screenshot(path=str(OUT / "e2e-taxi-end.png"))
    b.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
