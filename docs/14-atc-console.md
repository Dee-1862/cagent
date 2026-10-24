# ATC Console and Projector: Design Spec

The laptop is the control tower; two phones are the planes. This spec covers the **laptop** (the ATC console, shown on the projector) and the **seat picker**. It replaces the live room's controller and observer screens for the demo. The pilot phone screen is specified in section 6 for whoever builds it.

| Field | Value |
| --- | --- |
| Status | v0.1, 2026-10-24 |
| Owner | Rishit's side (ATC UI). Pilot phone: see agent mail |
| Code | `web/live/atc/` (new page, same `/live/ws/atc` feed as the live room) |
| Related | [Live Demo](11-live-demo.md), [Demo Design](11-demo-design.md), `CLAUDE.md` "How we build: the bar" |

## 1. Who it's for

Software engineers from voice-AI sponsors. They have never seen an ATC screen and will look at the projector for about 10 seconds before deciding whether they get it. So:

- **Plain English first, aviation second.** "Plane A missed an instruction" before "Stepped-on transmission". Jargon appears in small grey type under the plain phrase, if at all.
- **The planes are the hero.** A simple airport map with two planes shows what the instructions mean physically (stop before the runway, go, wait).
- **One sentence explains every step.** The explainability layer: each agent action is one line, "what it did and why", with the sponsor tag and the measured time.
- **The human is visibly in charge.** Anything that needs a decision is the biggest thing on screen, with Approve and Reject buttons.

## 2. Layout (1920 x 1080 projector, works down to 1366 x 768)

```
+--------------------------------------------------------------------------------------------+
| UNSTEP  Control Tower · KUNS · Radio 118.7      ● 2 planes connected   [QR] join   LIVE    |
+--------------------------------------------------------------------------------------------+
| WHAT JUST HAPPENED  ·  "Tower and the helicopter talked at the same time. Plane A          |
|                         (Cessna 1-2-3) never heard 'hold short Runway 33', and nobody knew."|
+-------------------------------------------------+------------------------------------------+
|                                                 |  NEEDS YOUR DECISION (2)                 |
|            AIRPORT MAP (hero)                   |  +------------------------------------+  |
|   runway 33/15, taxiway B, hold-short line      |  | Plane A · Cessna 1-2-3             |  |
|   Plane A on taxiway B  ⟶  status ring          |  | Missed: "cleared for takeoff ..."   |  |
|   Plane B (helicopter) in the air               |  | Why you: it lets the plane MOVE    |  |
|   red ring = missed a call, amber = told to     |  |  [ Approve and send ]  [ Reject ]  |  |
|   stop, green = confirmed                       |  |  auto-sends nothing · 0:45 left    |  |
|                                                 |  +------------------------------------+  |
+-------------------------------------------------+------------------------------------------+
| RADIO  (one lane per speaker, like a chat)                                                 |
|  Tower     "Cessna 1-2-3, hold short Runway 33"     ██ TALKED OVER ██                      |
|  Plane B   "Helicopter 4-5-6, request transition"   ██ TALKED OVER ██                      |
|  Plane A   heard: "Cessna 1-2-3 ~~~static~~~"                                              |
+--------------------------------------------------------------------------------------------+
| HOW UNSTEP HANDLED IT (explainability, newest event)                                       |
|  1 Heard the squeal on Plane A's radio ........................ cockpit agent · 0.3 ms      |
|  2 Found what Tower actually said .............................. Cartesia · 101 ms          |
|  3 Plane A's own memory agrees: "hold short Runway 33" ........ Moss · 2 ms                 |
|  4 Safe to resend? stop-type ✓ Tower's own words ✓ fresh ✓ ..... policy agent              |
|  5 Told Plane A privately (left ear) .......................... Cartesia · 110 ms          |
|  6 Plane A read it back: "hold short 33" ✓ ..................... Cartesia                  |
+--------------------------------------------------------------------------------------------+
```

- **Header:** product, "Control Tower", airport and radio frequency in plain words, how many planes are connected, a **QR code** to join as a plane (`/live/#N123AB`, `/live/#H456` or the picker), LIVE or OFFLINE.
- **"What just happened" strip:** one sentence, rewritten on every event, from real messages. This is what the presenter points at.
- **Airport map (hero):** an SVG, not a real chart: one runway labelled "Runway 33", one taxiway "B", a dashed **"stop line"** (hold-short line, with "hold short" in small type), the tower. Plane A (Cessna) sits on taxiway B short of the line; Plane B (helicopter) hovers off the field. Each plane has a status ring driven by real events:
  - grey: normal
  - **red pulse, "Missed a call"**: an AnomalyEvent for that plane
  - amber, "Told to stop" or "Told: <short instruction>": directive delivered
  - green check, "Read back correctly": readback match
  - red ✕ "Read back wrong: 23": readback mismatch (flashes at most twice)
  - When a hold short is confirmed, a small stop sign appears at the line in front of the plane.
- **Needs your decision (human in the loop):** escalated proposals as large cards. Each card: plane, what was missed (tower's words, with the lost words highlighted), **"Why you're seeing this"** in one plain sentence from the failed policy checks (e.g. "It would let the plane move, so a human must decide"), big **Approve and send** / **Reject** buttons, the countdown. Empty state: "Nothing needs you. Routine stop-type calls are re-sent automatically, and you see each one below." Auto-relay switch lives here with plain wording: "Auto-resend the tower's own stop/wait instructions".
- **Radio:** chat-like lanes per speaker with the transcript; overlapping transmissions get a red hatched "TALKED OVER" band; each plane's lane shows what that plane *heard*.
- **How Unstep handled it (explainability layer):** numbered steps for the newest event, each one sentence plus the agent, sponsor tag (Cartesia, Moss, Elastic, policy) and measured time. Older events collapse into a list you can click to expand.
- **Footer (small):** what's real vs stand-in, e.g. "Ground agents: stand-in until Elastic Workflow".

## 3. Seat picker and ATC password

- `/live/` opens a picker with three big cards: **Control Tower (laptop)**, **Plane A · Cessna 1-2-3**, **Plane B · Helicopter 4-5-6**, plus a small "Projector only (read-only)" link. Plain one-line descriptions.
- **The Control Tower seat needs a password** (`UNSTEP_ATC_PASSWORD` in `.env`). The page asks for it; the server checks it on the `/live/ws/atc` socket (constant-time compare) and closes the socket with a clear message if it's wrong. If the variable isn't set, the tower seat is open and the header says "ATC password not set". Only the tower can approve, reject or toggle auto-resend.
- Choosing the tower seat goes to `/live/atc/`. Planes keep the existing pilot screen until the phone screen (section 6) lands.

## 4. Visual rules

Same palette and contrast rules as [Demo Design section 3](11-demo-design.md#3-palette): dark background, red only for a missed call or a wrong readback, amber for "told to stop" and pending decisions, green for confirmed, cyan for Unstep's own actions. Color is never the only cue. System fonts, no CDN, works offline. Big type: the "what just happened" sentence at 30 px or more, map labels 16 px or more. Motion once, 150 to 400 ms, respect reduced motion.

## 5. Demo beat this screen serves

1. Two judges hold their phone buttons on a count; the squeal fills the room.
2. Projector: Plane A's ring turns red, the strip says "Plane A never heard 'hold short Runway 33', and nobody knew."
3. Steps fill in one by one; Plane A's phone says it privately; the ring goes amber, then green with the stop sign.
4. Second round: tower says "cleared for takeoff" and gets stepped on. That's not a stop-type instruction, so it lands in **Needs your decision** with "It would let the plane move". The presenter clicks Approve on the laptop.

## 6. Pilot phone (for whoever builds it)

- One screen, no scrolling. The **hold-to-talk button fills about 60%**, with states: idle, **ON AIR** (red), "Someone else is talking" (amber, still pressable: real radios don't block), reconnecting.
- A purple **"Only you can hear this"** panel shows Unstep's private message in readable text (not phonetic), with a left-ear icon, replayable.
- "Say this" buttons with the suggested lines for anyone without a working mic; they go on air for real.
- A small "Ask Unstep" button (the Unstep key) separate from the radio button.
- One "Turn on my radio" tap unlocks audio, mic and the screen wake lock. Debug lines hidden behind a "details" toggle.
- Web limits: the mic needs HTTPS or localhost; iOS is silent with the ringer switch off; no vibration on iPhone; re-request the wake lock when the tab comes back.

## 7. Done when

- A stranger watching the projector can say what happened after one stepped-on call.
- The full beat in section 5 runs live and offline without touching the keyboard except the Approve click.
- Screenshots at 1920 x 1080 and 1366 x 768 look right; tests pass; the existing live room pages still work.
