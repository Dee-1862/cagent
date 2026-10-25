"""End-to-end taxi and readback edge cases on a live hub (15 checks).

Start a hub first:  python -m unstep.live --port 8796 --no-browser
Then:              python scripts/e2e_taxi.py
Tower lines are typed on the console; the two pilots are websocket clients that can speak.
"""
import asyncio
import json
import sys
import threading

import websockets
from playwright.sync_api import sync_playwright

H = "http://localhost:8796"
WS = "ws://127.0.0.1:8796/live/ws/"
from pathlib import Path
S = str(Path(__file__).resolve().parent.parent / "data")
results = []

# ---- pilots: keep N123AB and H456 connected and let the test make them speak ----
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

    ps = wait_for(lambda ps: {"N123AB", "H456"} <= set(ps), 20)
    check("both planes spawn in the queue", all(ps.get(i, {}).get("state") == "queue" for i in ("N123AB", "H456")), str(ps))
    a, h = ps.get("N123AB", {}), ps.get("H456", {})
    check("queue is on taxiway B, Plane A ahead (west) of Plane B", a.get("z") == 14 and h.get("z") == 14 and a.get("x", 0) < h.get("x", 0), f"A {a} B {h}")

    # 1. line up and wait goes to the runway 33 END, not the middle
    tower("Cessna 1, 2, 3, clear for departure, line up and wait runway 33")
    ps = wait_for(lambda ps: ps["N123AB"]["state"] == "lined_up", 40)
    a = ps["N123AB"]
    check("line up and wait runway 33 -> lined up at the 33 end", a["state"] == "lined_up" and a["x"] <= -30 and a["z"] == 22, str(a))
    check("Plane B moved up to the front of the queue", ps["H456"]["x"] == -26, str(ps["H456"]))

    # 2. the user's real wrong readback is caught and the plane is held
    pilot_says("N123AB", "line up and wait here for departure runway 13")
    atc.wait_for_timeout(6000)
    check("wrong readback (runway 13 vs 33) flagged in the feed", feed_has("Wrong readback from Plane A"))
    check("plane with the wrong readback is held", planes()["N123AB"]["state"] == "stopped", str(planes()["N123AB"]))

    # 3. taxi to A3 from the runway
    tower("Cessna 123, taxi to A3")
    ps = wait_for(lambda ps: abs(ps["N123AB"]["x"] - 6) < .2 and abs(ps["N123AB"]["z"] - 9.2) < .3, 40)
    check("taxi to A3 (from the runway) arrives at A3", abs(ps["N123AB"]["x"] - 6) < .2 and abs(ps["N123AB"]["z"] - 9.2) < .3, str(ps["N123AB"]))
    pilot_says("N123AB", "taxi to alpha three, Cessna one two three")
    atc.wait_for_timeout(5000)
    check("correct readback of A3 marked correct", feed_has("Plane A read it back correctly"))

    # 4. the other runway end: runway 15
    tower("Helicopter 4 5 6, line up and wait runway 15")
    ps = wait_for(lambda ps: ps["H456"]["state"] == "lined_up", 50)
    hh = ps["H456"]
    check("line up and wait runway 15 -> lined up at the 15 end", hh["state"] == "lined_up" and hh["x"] >= 30 and hh["z"] == 22, str(hh))
    tower("Helicopter 456 cleared for takeoff runway 15")
    ps = wait_for(lambda ps: ps["H456"]["alt"] > 1, 30)
    check("takeoff from runway 15 rolls west and climbs", ps["H456"]["alt"] > 1 and ps["H456"]["x"] < 30, str(ps["H456"]))

    # 5. taxi via Alpha to the runway 33 hold short, then takeoff on 33
    tower("Cessna 123 taxi to runway 33 via alpha")
    seen_a = False
    for _ in range(80):
        atc.wait_for_timeout(500)
        cur = planes()["N123AB"]
        seen_a = seen_a or abs(cur["z"] - 4.5) < .3
        if cur["state"] == "holding":
            break
    cur = planes()["N123AB"]
    check("taxi via alpha travels along taxiway A", seen_a, str(cur))
    check("...and ends holding short of runway 33", cur["state"] == "holding" and cur["x"] == -33, str(cur))
    tower("Cessna 123 cleared for takeoff runway 33")
    ps = wait_for(lambda ps: ps["N123AB"]["alt"] > 1, 40)
    check("takeoff from the 33 end rolls east and climbs", ps["N123AB"]["alt"] > 1 and ps["N123AB"]["x"] > -31, str(ps["N123AB"]))
    ps = wait_for(lambda ps: ps["N123AB"]["state"] == "queue", 30)
    check("after departing, the plane rejoins the back of the queue", ps["N123AB"]["state"] == "queue", str(ps["N123AB"]))

    # 6. hold position stops a taxiing plane mid-route
    tower("Cessna 123 taxi to A4")
    atc.wait_for_timeout(3500)
    tower("Cessna 123 hold position")
    p1 = wait_for(lambda ps: ps["N123AB"]["state"] == "stopped", 15)["N123AB"]; atc.wait_for_timeout(2500); p2 = planes()["N123AB"]
    check("hold position stops the plane where it is", p1["state"] == "stopped" and p1["x"] == p2["x"] and p1["z"] == p2["z"], f"{p1} {p2}")

    atc.screenshot(path=S + "/e2e-end.png")
    b.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
