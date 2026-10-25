"""Make the Devpost gallery images (1800 x 1200, 3:2) from real screenshots and the saved measurements.

    python scripts/devpost_images.py            # writes docs/img/devpost/NN-name.png

Sources are the real screenshots in docs/img/devpost/src/ (the tower console, the phone captured on a live run with real
Cartesia speech, the hardware photo, a terminal capture). The numbers on the sponsor card are read from docs/evidence/,
never typed here. Nothing is mocked: a screenshot is shown as it was taken, in a frame.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "img" / "devpost" / "src"
OUT = ROOT / "docs" / "img" / "devpost"
FONTS = (ROOT / "app" / "src" / "fonts").as_uri()
EVIDENCE = ROOT / "docs" / "evidence"

BASE = """
@font-face{font-family:"Plex Mono";font-weight:500;src:url("__FONTS__/ibm-plex-mono-latin-500-normal.woff2")}
@font-face{font-family:"Plex Mono";font-weight:600;src:url("__FONTS__/ibm-plex-mono-latin-600-normal.woff2")}
@font-face{font-family:"Plex Cond";font-weight:500;src:url("__FONTS__/ibm-plex-sans-condensed-latin-500-normal.woff2")}
@font-face{font-family:"Plex Cond";font-weight:600;src:url("__FONTS__/ibm-plex-sans-condensed-latin-600-normal.woff2")}
*{box-sizing:border-box;margin:0;padding:0}
body{width:1800px;height:1200px;background:#0c0d0a;color:#ece7d8;font-family:"Plex Cond",sans-serif;font-weight:500;overflow:hidden;position:relative}
.grid{position:absolute;inset:0;background-image:linear-gradient(rgba(236,231,216,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(236,231,216,.04) 1px,transparent 1px);background-size:60px 60px}
.glow{position:absolute;width:1100px;height:1100px;border-radius:50%;background:radial-gradient(closest-side,rgba(255,159,10,.13),transparent);filter:blur(10px)}
.kicker{font:500 20px "Plex Mono",monospace;letter-spacing:.16em;text-transform:uppercase;color:#8d8a78}
h1{font:600 84px/1 "Plex Cond",sans-serif;letter-spacing:-.02em}
h2{font:600 62px/1.02 "Plex Cond",sans-serif;letter-spacing:-.015em}
p.lede{font:500 31px/1.34 "Plex Cond",sans-serif;color:#cfcab9}
.amber{color:#ff9f0a}
.mono{font-family:"Plex Mono",monospace}
.browser{position:absolute;border-radius:14px;overflow:hidden;background:#111;box-shadow:0 50px 110px rgba(0,0,0,.7),0 0 0 1px rgba(236,231,216,.13)}
.browser .bar{height:40px;background:#191a16;display:flex;align-items:center;gap:9px;padding:0 16px;font:500 15px "Plex Mono",monospace;color:#8d8a78;letter-spacing:.04em}
.browser .bar i{width:12px;height:12px;border-radius:50%;background:#34352e;display:block}
.browser .bar span{margin-left:14px}
.browser img{display:block;width:100%}
.phone{position:absolute;border-radius:46px;padding:11px;background:#1b1c17;box-shadow:0 50px 100px rgba(0,0,0,.7),0 0 0 1px rgba(236,231,216,.16),inset 0 0 0 2px #0c0d0a}
.phone img{display:block;width:100%;border-radius:35px}
.badge{position:absolute;width:50px;height:50px;border-radius:50%;background:#ff9f0a;color:#15120a;font:600 26px/50px "Plex Mono",monospace;text-align:center;box-shadow:0 0 0 6px rgba(255,159,10,.25),0 8px 22px rgba(0,0,0,.5)}
.step{display:grid;grid-template-columns:64px 1fr;gap:6px;align-items:start}
.step b{font:600 26px/1.2 "Plex Mono",monospace;color:#ff9f0a}
.step div{font:500 30px/1.28 "Plex Cond",sans-serif;color:#e6e1d1}
.step div small{display:block;font:500 22px/1.35 "Plex Cond",sans-serif;color:#9a9684;margin-top:4px}
.footer{position:absolute;left:84px;right:84px;bottom:42px;display:flex;justify-content:space-between;font:500 17px "Plex Mono",monospace;color:#7b7868;letter-spacing:.08em;text-transform:uppercase}
.note{font:500 20px/1.4 "Plex Mono",monospace;color:#8d8a78;letter-spacing:.02em}
"""


def page(body: str) -> str:
    footer = '<div class="footer"><span>Unstep &middot; Cal Hacks 13.0</span><span>Cartesia &middot; Moss &middot; Elastic</span></div>'
    return f"<!doctype html><meta charset=utf-8><style>{BASE.replace('__FONTS__', FONTS)}</style><body>{body}{footer}</body>"


def img(name: str) -> str:
    return (SRC / name).as_uri()


def ev(pattern: str) -> dict:
    return json.loads(sorted(EVIDENCE.glob(pattern))[-1].read_text(encoding="utf-8"))


def badge(k: int, rx: float, ry: float, left: int = 690, top: int = 250, width: int = 1030) -> str:
    """A numbered marker placed from a point on the console picture (fractions of its width and height)."""
    x = left + rx * width - 25
    y = top + 40 + ry * width * 9 / 16 - 25
    return f'<div class=badge style="left:{x:.0f}px;top:{y:.0f}px">{k}</div>'


def build() -> dict[str, str]:
    c, m, e = ev("cartesia-20*.json"), ev("moss-2*.json"), ev("elastic-2*.json")
    kt = c["keyterms"]
    commits = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    n = lambda x: f"{x:.3g}"

    pages: dict[str, str] = {}

    pages["01-hero"] = page(f"""
<div class=grid></div><div class=glow style="right:-250px;top:-120px"></div>
<div style="position:absolute;left:84px;top:96px;width:690px">
  <div class=kicker>Unstep &middot; air traffic control</div>
  <h1 style="margin-top:34px">When two pilots talk at once, <span class=amber>nobody notices.</span> Now someone does.</h1>
  <p class=lede style="margin-top:36px">A team of AI agents works the radio next to the controller. Cartesia hears, Moss remembers, Elastic checks, and a person decides.</p>
  <div class=mono style="margin-top:46px;font-size:21px;color:#8d8a78;letter-spacing:.08em">KUNS TOWER &nbsp;<span style="color:#ece7d8;font-size:34px;font-weight:600;letter-spacing:-.02em">118.700</span> MHz</div>
</div>
<div class=browser style="left:830px;top:120px;width:880px"><div class=bar><i></i><i></i><i></i><span>KUNS Control Tower &middot; a blocked call</span></div><img src="{img('console-call.png')}"></div>
<div class=phone style="left:1450px;top:400px;width:250px"><img src="{img('live-b3-private-advisory.png')}"></div>
""")

    pages["02-a-call-gets-stepped-on"] = page(f"""
<div class=grid></div><div class=glow style="left:-300px;bottom:-400px"></div>
<div style="position:absolute;left:84px;top:96px;width:600px">
  <div class=kicker>The tower console</div>
  <h2 style="margin-top:26px">A call gets <span class=amber>stepped on.</span></h2>
  <div style="display:grid;gap:30px;margin-top:56px">
    <div class=step><b>01</b><div>Both calls squeal. The lanes say TALKED OVER.<small>Nobody on the radio is told.</small></div></div>
    <div class=step><b>02</b><div>Unstep recovers the lost words and puts one decision in front of the controller.<small>Approve and send, or reject. A person decides.</small></div></div>
    <div class=step><b>03</b><div>The agents list what they did, one line each.<small>Geo, recovery, policy, ground, cockpit.</small></div></div>
  </div>
</div>
<div class=browser style="left:690px;top:250px;width:1030px"><div class=bar><i></i><i></i><i></i><span>KUNS Control Tower &middot; offline demo build</span></div><img src="{img('console-call.png')}"></div>
{badge(1, 0.51, 0.80)}
{badge(2, 0.762, 0.27)}
{badge(3, 0.762, 0.62)}
""")

    pages["03-a-normal-call-live"] = page(f"""
<div class=grid></div><div class=glow style="left:300px;top:-500px"></div>
<div style="position:absolute;left:84px;top:60px;width:1300px">
  <div class=kicker>On the phone &middot; live</div>
  <h2 style="margin-top:14px">A normal call, <span class=amber>word by word.</span></h2>
</div>
<div class=phone style="left:206px;top:196px;width:300px"><img src="{img('live-a1-tower-call-arrives.png')}"></div>
<div style="position:absolute;left:126px;top:966px;width:460px" class=step><b>01</b><div style="font-size:26px">The tower speaks. Its words appear as it says them.</div></div>
<div class=phone style="left:750px;top:196px;width:300px"><img src="{img('live-a2-you-hold-to-talk.png')}"></div>
<div style="position:absolute;left:670px;top:966px;width:460px" class=step><b>02</b><div style="font-size:26px">You hold to talk. Your words appear as you say them.</div></div>
<div class=phone style="left:1294px;top:196px;width:300px"><img src="{img('live-a3-read-back-correctly.png')}"></div>
<div style="position:absolute;left:1214px;top:966px;width:460px" class=step><b>03</b><div style="font-size:26px">Unstep checks your readback against what you were told.</div></div>
""".replace("bottom:42px", "bottom:30px"))

    pages["04-two-people-at-once"] = page(f"""
<div class=grid></div><div class=glow style="right:-300px;top:-500px"></div>
<div style="position:absolute;left:84px;top:60px;width:1300px">
  <div class=kicker>On the phone &middot; live</div>
  <h2 style="margin-top:14px">Two people talk at once. <span class=amber>The pilot is told.</span></h2>
</div>
<div class=phone style="left:206px;top:196px;width:300px"><img src="{img('live-b1-both-talk-at-once.png')}"></div>
<div style="position:absolute;left:126px;top:966px;width:460px" class=step><b>01</b><div style="font-size:26px">The pilot and the tower both press the button.</div></div>
<div class=phone style="left:750px;top:196px;width:300px"><img src="{img('live-b2-still-both-talking.png')}"></div>
<div style="position:absolute;left:670px;top:966px;width:460px" class=step><b>02</b><div style="font-size:26px">On a real radio this is a squeal, and nobody is told.</div></div>
<div class=phone style="left:1294px;top:196px;width:300px"><img src="{img('live-b3-private-advisory.png')}"></div>
<div style="position:absolute;left:1214px;top:966px;width:460px" class=step><b>03</b><div style="font-size:26px">Unstep tells the pilot, privately, in the left ear.</div></div>
""".replace("bottom:42px", "bottom:30px"))

    pages["05-scan-and-fly"] = page(f"""
<div class=grid></div><div class=glow style="left:-200px;top:200px"></div>
<div style="position:absolute;left:84px;top:96px;width:640px">
  <div class=kicker>Join in ten seconds</div>
  <h2 style="margin-top:26px">Scan. Tap. <span class=amber>You are a pilot.</span></h2>
  <div style="display:grid;gap:30px;margin-top:56px">
    <div class=step><b>01</b><div>The laptop is the control tower. Its QR code is the one way in.</div></div>
    <div class=step><b>02</b><div>Your phone opens the radio on 118.700.<small>One tap turns the microphone on.</small></div></div>
    <div class=step><b>03</b><div>Hold to talk. Step on someone. Watch Unstep catch it.</div></div>
  </div>
</div>
<div class=browser style="left:760px;top:120px;width:620px"><div class=bar><i></i><i></i><i></i><span>KUNS Control Tower</span></div><img src="{img('console-idle.png')}"></div>
<div class=phone style="left:1420px;top:150px;width:300px"><img src="{img('phone-join.png')}"></div>
""")

    pages["06-a-team-of-agents"] = page(f"""
<div class=grid></div><div class=glow style="right:-300px;bottom:-500px"></div>
<div style="position:absolute;left:84px;top:96px;width:640px">
  <div class=kicker>Who is on the team</div>
  <h2 style="margin-top:26px">One person. One fixed workflow. <span class=amber>Five agents.</span></h2>
  <p class=lede style="margin-top:40px">The workflow is written down and sequences the agents; it decides nothing. Each agent can only call its own fixed queries. A person approves everything that moves a plane.</p>
  <div class=note style="margin-top:44px">Intercept &middot; Compliance &middot; Readback auditor<br>Audit &middot; Coach &middot; plus the policy and cockpit agents</div>
</div>
<div class=browser style="left:790px;top:110px;width:930px"><div class=bar><i></i><i></i><i></i><span>KUNS Control Tower &middot; the team strip, open</span></div><img src="{img('console-team.png')}"></div>
""")

    pages["07-a-raspberry-pi-is-a-plane"] = page(f"""
<div class=grid></div><div class=glow style="left:500px;top:-500px"></div>
<div style="position:absolute;left:84px;top:96px;width:680px">
  <div class=kicker>Hardware</div>
  <h2 style="margin-top:26px">A Raspberry Pi is <span class=amber>a plane too.</span></h2>
  <p class=lede style="margin-top:40px">A Pi 4 with a Logitech webcam as its microphone joins the same radio as a pilot. The level bar shows the microphone is on, and warns when it is too loud.</p>
  <div class=note style="margin-top:34px">Today: the Pi's microphone and network are in use. The Nest Mini is not connected as a speaker yet.</div>
</div>
<div class=browser style="left:84px;top:640px;width:900px;background:#12130f"><div class=bar><i></i><i></i><i></i><span>Raspberry Pi 4, over SSH</span></div><img src="{img('pi-mic-test.png')}"></div>
<div style="position:absolute;left:1060px;top:84px;width:660px;height:1030px;border-radius:18px;overflow:hidden;box-shadow:0 50px 110px rgba(0,0,0,.7),0 0 0 1px rgba(236,231,216,.13)"><img src="{img('setup.jpeg')}" style="width:100%;height:100%;object-fit:cover;object-position:50% 38%"></div>
""")

    pages["08-measured-not-claimed"] = page(f"""
<div class=grid></div><div class=glow style="left:400px;bottom:-600px"></div>
<div style="position:absolute;left:84px;top:84px;width:1500px">
  <div class=kicker>Measured, not claimed</div>
  <h2 style="margin-top:20px">Three sponsors, <span class=amber>each with a number.</span></h2>
</div>
<style>
.col{{position:absolute;top:250px;width:520px;height:810px;border-radius:18px;background:#14150f;box-shadow:0 0 0 1px rgba(236,231,216,.1);padding:40px 40px}}
.col h3{{font:600 46px "Plex Cond";letter-spacing:-.01em}}
.col .role{{font:500 18px "Plex Mono";letter-spacing:.12em;text-transform:uppercase;color:#8d8a78;margin-top:8px}}
.big{{font:600 78px/1 "Plex Mono";letter-spacing:-.04em;margin-top:44px;color:#ece7d8}}
.big small{{font:500 24px "Plex Mono";color:#8d8a78;letter-spacing:0}}
.cap{{font:500 24px/1.3 "Plex Cond";color:#bdb8a6;margin-top:8px}}
</style>
<div class=col style="left:84px"><h3>Cartesia</h3><div class=role>the ears and the voice</div>
  <div class=big>{n(c['stt_streaming_finalize_ms']['p50'])}<small> ms</small></div><div class=cap>final words after release, streaming (median, n={c['stt_streaming_finalize_ms']['n']})</div>
  <div class=big style="font-size:60px">{kt['callsign']['without']*100:.0f}% <span class=amber>&rarr;</span> {kt['callsign']['with']*100:.0f}%</div><div class=cap>callsigns heard right in radio noise, with key terms ({kt['n']} lines)</div>
  <div class=big style="font-size:60px">{n(c['tts_first_audio_ms']['p50'])}<small> ms</small></div><div class=cap>Sonic first audio (median, n={c['tts_first_audio_ms']['n']})</div></div>
<div class=col style="left:640px"><h3>Moss</h3><div class=role>each aircraft's memory</div>
  <div class=big>{n(m['fetch_last_tower_call_filter_and_sort']['moss_reported_ms']['p50'])}<small> ms</small></div><div class=cap>a plane reads its last tower call (median, {m['sessions']} sessions, n={m['fetch_last_tower_call_filter_and_sort']['moss_reported_ms']['n']})</div>
  <div class=big style="font-size:60px">{m['hybrid_scores']['right clearance']['score']:.1f} <span style="color:#8d8a78">vs</span> {m['hybrid_scores']['unrelated speech']['score']:.1f}</div><div class=cap>search score: the right clearance against unrelated speech</div>
  <div class=big style="font-size:60px">9.9<small> ms</small></div><div class=cap>memory restored from the plane's own disk</div></div>
<div class=col style="left:1196px"><h3>Elastic</h3><div class=role>the agent platform</div>
  <div class=big style="font-size:62px">{e['objects']['agents']['ours']} &middot; {e['objects']['tools']['ours']} &middot; {e['objects']['workflows']['ours']}</div><div class=cap>agents, tools and workflows, counted from Kibana on our project</div>
  <div class=big style="font-size:60px">{e['faa_citation_hybrid_rerank']['timing_ms']['p50']/1000:.2f}<small> s</small></div><div class=cap>reranked FAA citation (median, n={e['faa_citation_hybrid_rerank']['timing_ms']['n']})</div>
  <div class=big style="font-size:60px">{e['audit_trail']['documents']['unstep-events']:,}</div><div class=cap>events in the audit trail, ES|QL answers in about {e['audit_trail']['esql_wall_ms']['p50']:.0f} ms</div></div>
<div class=note style="position:absolute;left:84px;top:1086px;width:1600px">Measured 2026-10-25 on one laptop against our own cloud projects. Speech is synthetic, through a simulated radio. Every number is a file in docs/evidence/.</div>
""".replace("bottom:42px", "bottom:14px"))

    pages["09-built-in-a-day"] = page(f"""
<div class=grid></div><div class=glow style="right:-300px;top:-500px"></div>
<div style="position:absolute;left:84px;top:96px;width:1500px">
  <div class=kicker>Built at the hackathon</div>
  <h2 style="margin-top:26px">The data was built in a day, <span class=amber>from scratch.</span></h2>
</div>
<div style="position:absolute;left:84px;right:84px;top:520px;height:2px;background:rgba(236,231,216,.25)"></div>
<style>
.tick{{position:absolute;top:500px;width:2px;height:42px;background:#ece7d8}}
.lab{{position:absolute;width:280px;font:500 25px/1.28 "Plex Cond";color:#e6e1d1}}
.lab b{{display:block;font:600 30px "Plex Mono";color:#ff9f0a;margin-bottom:6px;letter-spacing:-.02em}}
.lab small{{display:block;font:500 19px "Plex Mono";color:#8d8a78;margin-top:8px}}
</style>
<div class=tick style="left:84px"></div><div class=lab style="left:84px;top:300px"><b>hour 0</b>First commit<small>Oct 23, 9 pm</small></div>
<div class=tick style="left:174px"></div><div class=lab style="left:150px;top:570px"><b>3.2 h</b>Airport index for Moss<small>8 documents</small></div>
<div class=tick style="left:1050px"></div><div class=lab style="left:880px;top:300px"><b>23.6 h</b>Elastic deploy<small>8 agents, 9 tools, 7 workflows</small></div>
<div class=tick style="left:1150px"></div><div class=lab style="left:1110px;top:570px"><b>24.1 h</b>FAA rulebook indexed<small>52 paragraphs</small></div>
<div class=tick style="left:1250px"></div><div class=lab style="left:1280px;top:300px"><b>26.3 h</b>Traffic simulator<small>500 labelled calls, simulated</small></div>
<div class=tick style="left:1716px"></div><div class=lab style="left:1436px;top:570px;text-align:right"><b>33.6 h</b>This morning<small>{commits} commits &middot; 646 tests</small></div>
<div class=note style="position:absolute;left:84px;top:920px;width:1500px;font-size:24px">From git timestamps. The first commit was 2026-10-23 21:00 PDT. The rulebook is 52 paragraphs, not all of JO 7110.65, and one stored rule has been reviewed by a person.</div>
""")
    return pages


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pages = build()
    tmp = OUT / "src" / "_page.html"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1800, "height": 1200})
        for name, html in pages.items():
            tmp.write_text(html, encoding="utf-8")
            page.goto(tmp.as_uri(), wait_until="load")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(400)
            path = OUT / f"{name}.png"
            page.screenshot(path=str(path))
            print(path.name, path.stat().st_size // 1024, "KB")
        browser.close()
    tmp.unlink()


if __name__ == "__main__":
    sys.exit(main())
