"""Clean footage for the edited demo video: the ATC console and both pilot phones recorded as separate videos,
with a timeline of every story beat and every sound the room played (Cartesia radio voices, the private
advisory), so an editor (video/ Remotion project) can cut, frame and caption them.

    python scripts/capture_demo_footage.py --port 8796      # a hub already running there
Writes data/video/footage/: console.webm, phoneA.webm, phoneB.webm, timeline.json, audio/*.wav, audio.json.

The console's own chrome that a viewer doesn't need (legend, QR card, camera toolbar, footer) is hidden;
the radio panel and the agents panel stay. The story is one complete flow (demo-first):
  queue -> Plane A asks for taxi (Clearance agent: Elastic flight plan + Moss) -> taxi to the 33 hold short
  -> the tower's "hold short" is stepped on by Plane B -> detected, approved -> private advisory on Plane A
  -> a wrong readback is flagged, then corrected -> the agent proposes takeoff unasked -> Plane A departs.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from record_live_video import SOCKET_PROBE, Pilots, StepFailed, audio_plan, step  # noqa: E402

OUT = ROOT / "data" / "video" / "footage"
HIDE = """.legend-card,.pilot-join,.toolbar,.field-readout,footer{display:none!important}"""
T = 60_000


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--port", type=int, required=True)
    args = p.parse_args(argv)
    from playwright.sync_api import expect, sync_playwright

    base = f"http://127.0.0.1:{args.port}"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "audio").mkdir(exist_ok=True)
    marks = []

    def mark(name):
        marks.append({"t": time.time() * 1000, "beat": name})
        print(f"mark {name}", flush=True)

    with sync_playwright() as pw:
        pilots = Pilots(args.port)
        browser = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required", "--use-gl=angle", "--ignore-gpu-blocklist"])

        def ctx(name, w, h, scale=1):
            c = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=scale,
                                    record_video_dir=str(OUT / f"_{name}"), record_video_size={"width": w * scale, "height": h * scale})
            c.add_init_script(SOCKET_PROBE)
            pg = c.new_page()
            return c, pg, pg.evaluate("performance.timeOrigin")

        cc, atc, t_atc = ctx("console", 1920, 1080)
        ca, a, t_a = ctx("phoneA", 430, 932, 2)
        cb, b, t_b = ctx("phoneB", 430, 932, 2)
        atc.goto(f"{base}/live/atc/", wait_until="domcontentloaded"); atc.add_style_tag(content=HIDE)
        a.goto(f"{base}/pilot/#/fly/N123AB"); b.goto(f"{base}/pilot/#/fly/H456")

        def feed(text, timeout=T):
            expect(atc.locator("#feed .feed-row", has_text=text).first).to_be_visible(timeout=timeout)

        def planes():
            return atc.evaluate("() => window.unstepAirport?.inspect?.() || []")

        def wait_plane(station, pred, timeout=T):
            end = time.monotonic() + timeout / 1000
            while time.monotonic() < end:
                pl = next((x for x in planes() if x["id"] == station), None)
                if pl and pred(pl):
                    return
                atc.wait_for_timeout(400)
            raise AssertionError(f"{station}: {planes()}")

        def readback(station, instruction, text):
            who = "Plane A" if station == "N123AB" else "Plane B"
            feed(f"{who} was told"); feed(instruction)
            atc.wait_for_timeout(900)  # a beat, as a pilot would
            mark(f"readback {station}: {text}")
            pilots.say(station, text)

        def tower(text):
            mark(f"tower: {text}")
            atc.evaluate("(t) => { const s = document.getElementById('say'); s.value = t; s.dispatchEvent(new Event('input')); document.getElementById('transmit').click(); }", text)

        def card(title):
            return atc.locator("#requests .clearance", has_text=title).first

        failed = None
        try:
            step("console up", lambda: expect(atc.locator("#autonomy")).to_be_enabled(timeout=45_000))
            if atc.locator("#autonomy").is_checked():
                atc.evaluate("() => document.getElementById('autonomy').click()")
            atc.evaluate("() => window.unstepAirport?.setView?.('overview')")

            def queue():
                expect(a.get_by_role("button", name="More")).to_be_visible(timeout=T)
                wait_plane("N123AB", lambda x: x["state"] == "queue")
                wait_plane("H456", lambda x: x["state"] == "queue")
                feed("Plane A now in Taxiway B at 37.")
                atc.wait_for_timeout(2500)
            step("both planes queue", queue); mark("queue")

            def request_taxi():
                mark("plane A asks: request taxi")
                pilots.say("N123AB", "Tower, Cessna one two three, request taxi")
                expect(card("Plane A asks")).to_be_visible(timeout=T); mark("clearance card")
                atc.wait_for_timeout(3500)
                card("Plane A asks").locator("button.approve").click(); mark("clearance sent")
                readback("N123AB", "taxi to runway 33 via Bravo, hold short", "taxi to runway 33 via bravo, hold short of runway 33, Cessna 123")
                feed("Plane A read it back correctly"); mark("readback ok, taxiing")
                atc.evaluate("() => window.unstepAirport?.setView?.('runway')")
                wait_plane("N123AB", lambda x: x["state"] == "holding" and x["x"] == -33); mark("holding short 33")
                atc.wait_for_timeout(1500)
                # the agent proposes takeoff unasked while she holds; not yet: dismiss so the stepped-on call is clean
                nxt = card("Next for Plane A")
                if nxt.count():
                    nxt.locator("button.reject").click()
            step("Plane A asks, the agent clears it, it taxis", request_taxi)

            def step_on():
                b.get_by_role("button", name="More").click(timeout=T)
                expect(b.get_by_role("button", name="Request transition")).to_be_visible(timeout=T)
                atc.wait_for_timeout(1000)
                mark("tower: Cessna 1-2-3, hold short runway 33  +  Plane B talks at the same time")
                atc.locator('[data-say*="hold short runway three three"]').evaluate("x => x.click()")
                b.get_by_role("button", name="Request transition").evaluate("x => x.click()")
                expect(atc.locator(".talked-over >> visible=true").first).to_be_visible(timeout=T); mark("TALKED OVER")
                atc.wait_for_timeout(2500)
                atc.get_by_role("button", name="Approve and send").first.click(timeout=T); mark("controller approves")
                expect(a.get_by_text("From Tower").first).to_be_visible(timeout=T); mark("private advisory on Plane A")
                atc.wait_for_timeout(6500)  # the advisory finishes speaking
                mark("readback of the advisory"); pilots.say("N123AB", "Hold short runway 33, Cessna 1-2-3")
                atc.wait_for_timeout(6000)
            step("the stepped-on call", step_on)

            def wrong_then_correct():
                tower("Cessna 123 line up and wait runway 33")
                readback("N123AB", "line up and wait runway 33", "line up and wait runway 13, Cessna 123")
                feed("Wrong readback from Plane A"); mark("wrong readback flagged")
                atc.wait_for_timeout(3000)
                mark("readback N123AB corrected"); pilots.say("N123AB", "line up and wait runway 33, Cessna 123")
                feed("Plane A read it back correctly")
                wait_plane("N123AB", lambda x: x["state"] == "lined_up"); mark("lined up 33")
            step("wrong readback, then right", wrong_then_correct)

            def takeoff():
                expect(card("Next for Plane A")).to_be_visible(timeout=T); mark("agent proposes takeoff unasked")
                atc.wait_for_timeout(3000)
                card("Next for Plane A").locator("button.approve").click(); mark("takeoff clearance sent")
                readback("N123AB", "cleared for takeoff", "runway 33 cleared for takeoff, Cessna 123")
                wait_plane("N123AB", lambda x: x["alt"] > 1); mark("Plane A airborne")
                atc.wait_for_timeout(4000)
            step("unasked takeoff clearance, departure", takeoff)

            def panels():
                atc.evaluate("() => document.getElementById('show-evidence').click()"); mark("evidence: how Unstep handled it")
                atc.wait_for_timeout(6000)
                atc.evaluate("() => document.getElementById('close-evidence').click()")
                atc.evaluate("() => document.querySelector('.side-tabs [data-tab=safety]').click()"); mark("safety analytics (Elastic)")
                atc.wait_for_timeout(4000)
            step("evidence and Elastic panels", panels)
        except StepFailed as exc:
            failed = exc

        events = []
        for pg in (atc, a, b):
            try:
                events += pg.evaluate("window.__audio || []")
            except Exception:
                pass
        clips = audio_plan(events, 0)  # absolute ms (Date.now) -> we keep them absolute
        audio = []
        for i, (at, wav) in enumerate(clips):
            path = OUT / "audio" / f"{i:03d}.wav"; path.write_bytes(wav)
            audio.append({"t": at, "file": f"audio/{path.name}"})
        paths = {}
        for name, c, pg in (("console", cc, atc), ("phoneA", ca, a), ("phoneB", cb, b)):
            v = Path(pg.video.path()); c.close()
            dst = OUT / f"{name}.webm"
            if dst.exists():
                dst.unlink()
            v.replace(dst); paths[name] = dst.name
        browser.close(); pilots.close()
        json.dump({"starts": {"console": t_atc, "phoneA": t_a, "phoneB": t_b}, "files": paths, "marks": marks},
                  open(OUT / "timeline.json", "w"), indent=1)
        json.dump(audio, open(OUT / "audio.json", "w"), indent=1)
        print(f"wrote {OUT} ({len(marks)} marks, {len(audio)} sounds)")
        if failed:
            print(f"FAILED: {failed}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
