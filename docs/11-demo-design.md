# Demo Screen and Presenter Mode: Design Spec

What the judges see and hear in the 2-minute demo, and the rules the screen is built on. Research behind it is summarized in section 8.

| Field | Value |
| --- | --- |
| Status | v0.1, built overnight 2026-10-24 |
| Code | `web/demo/` (screen), `unstep/demo/` (presenter mode) |
| Related | [PRD section 11](01-prd.md#11-demo-flow-2-minutes), [Advice section 7](08-advice.md#7-demo-flow-2-minutes), [Sponsor Review](07-sponsor-review.md) |

## 1. Principles

1. **Real, not scripted.** Every word, number and highlight on screen comes from a real message through the gateway (read-only `observer` role). Presenter mode only paces the scenes and chooses the input clips. No result is hardcoded.
2. **One moment per beat.** The squeal, the hint, the approval, the readback catch, the pilot question, the analytics. Each gets one clear visual change and nothing else moves.
3. **Voice first, screen second.** The first minute runs in **audio mode**: a near-empty screen with one large caption line and a waveform. Then the full view reveals what happened underneath. This proves "no screen needed" without losing the judges.
4. **Aviation display conventions.** Dark background. Red means warning and amber means caution, only. Cyan is advisory (Unstep). Green is confirmed. Color is never the only cue: every state also has a text label and a glyph.
5. **Show the hidden work, don't narrate the visible.** Latency badges and source records speak for themselves.
6. **Only our own measurements.** Every number is measured in this run. Vendor figures never appear (M-001).
7. **Demo-day proof.** Works without internet for the screen itself (no web fonts or CDNs), large type for projectors, keyboard driven, and a replay path if a live service fails.

## 2. Layout (1920 x 1080, no scrolling)

```
+---------------------------------------------------------------------------------------------+
| UNSTEP   KUNS TWR 118.300   N123AB   14:02:11Z        Cartesia ● Moss ● Elastic ●   3/8 LIVE|
+--------------------------------------------------------------+------------------------------+
|  TOWER   ▁▂▅▇▅▂▁ "Cessna 1-2-3, hold short Runway 33"        |  LIKELY (cyan)               |
|                               ░░░░░ BLOCKED ░░░░░            |  HOLD SHORT RWY 33           |
|  PILOT   ▁▂▃▂▁  "Cessna 1-2-3 [static]"                      |  Awaiting controller         |
|                                                              |  Moss 0.6 ms · source clr-07 |
|  UNSTEP  ▁▃▅▃▁ "Advisory. Hold short runway tree tree" (L)   +------------------------------+
|                                                              |  READBACK                    |
|  CTRL    ▁▂▁   "Approve"  ✓ voice                            |  heard  RWY 23  ✕            |
|                                                              |  expect RWY 33  ✓            |
|                                                              +------------------------------+
|                                                              |  GROUND / ELASTIC            |
|                                                              |  Intercept ✓ Compliance ✓    |
|                                                              |  FAA JO 7110.65 §...         |
|                                                              |  ES|QL  blocked calls: 2     |
+--------------------------------------------------------------+------------------------------+
| detect 0.3 ms │ cockpit STT 91 ms │ Moss 0.6 ms │ approve→ear 1.2 s │ TTS first audio 95 ms   |
+---------------------------------------------------------------------------------------------+
```

- **Top bar:** frequency, callsign, UTC clock, one status dot per service (from real connection state), scene counter, LIVE or REPLAY.
- **Center (about 62%): radio timeline,** four lanes: TOWER, PILOT, UNSTEP, CONTROLLER. Each transmission is a bar with its waveform and transcript. The overlap window is an amber hatched band labeled BLOCKED, and the blocked tower words get a strikethrough.
- **Right column: three cards:** local hint (Moss), readback (Cartesia), ground and analytics (Elastic). Sponsor names appear as small grey "powered by" labels on the card where that tech acts, never as colored logos.
- **Bottom: latency strip,** monospace pills, our measurements only.
- **Audio mode:** everything hidden except the top bar, one centered caption (speaker label + text, 44 px) and a thin waveform.

## 3. Palette

Checked with the WCAG contrast formula (section 1 rule 7: projectors wash out color, so every text color is at least 6:1).

| Role | Hex | On background | Use |
| --- | --- | --- | --- |
| Background | `#0A0E13` | | Page |
| Panel | `#121922` | | Cards, lanes |
| Grid | `#233041` | 1.4:1 | Lines only, never text |
| Primary text | `#E6EDF3` | 16.4:1 | Transcripts, values |
| Secondary text | `#8B9AAB` | 6.7:1 | Labels, sponsor tags |
| Advisory (Unstep) | `#22D3EE` | 10.7:1 | Unstep lane, hint card |
| Confirmed | `#34D399` | 10.1:1 | Approved, readback correct |
| Caution | `#FBBF24` | 11.6:1 | BLOCKED band, awaiting |
| Warning | `#F87171` | 7.0:1 | Readback incorrect only |
| Pilot | `#A5B4FC` | 9.7:1 | Pilot lane |

Rules: red appears only for a wrong readback. Amber only for a blocked call or a pending decision. Nothing decorative uses either.

## 4. Type

- UI text: `"Segoe UI Variable", "Segoe UI", system-ui, sans-serif`.
- Data, transcripts and numbers: `"Cascadia Mono", "Consolas", ui-monospace, monospace` with tabular figures.
- Sizes: transcripts 28 to 32 px, callsign and runway 40 px bold, audio-mode caption 44 px, labels 13 px uppercase with 0.08em letter spacing.
- System fonts only, so the screen works with no internet.

## 5. Motion

Each animation runs once, 150 to 400 ms, then stops. Respect `prefers-reduced-motion`.

1. **Squeal:** pilot bar shakes once (300 ms), amber hatched band fades in over the overlap window, strikethrough draws left to right across the blocked tower words.
2. **Hint:** hint card slides in from the right with one cyan pulse. The Moss badge counts up to the measured value.
3. **Approval:** "Approve" appears in the controller lane, a green check settles in.
4. **Directive:** words in the UNSTEP lane highlight one by one, timed by Cartesia word timestamps. An "L" glyph marks left ear only.
5. **Readback error:** "23" flashes red twice (under 3 flashes per second, photosensitivity safe) next to a green "33". After the correction, a check settles in.
6. **Analytics:** the ES|QL query types out and the result counts up.

Avoid: glow, glassmorphism, fake radar sweeps, looping motion, small grey text.

## 6. Presenter mode

`python -m unstep.demo` starts the whole stack (gateway, tower, agents, controller voice, Frequency Monitor, cockpit) and opens the screen. Scenes advance by keyboard:

| Key | Action |
| --- | --- |
| Space / Right | Next scene |
| Left / B | Previous scene (screen only) |
| A | Toggle audio mode and full view |
| R | Replay the last audio |
| 0 | Reset to scene 1 |

- `--live` uses real Cartesia, Moss and Moss Inference. Without it, fakes run the same pipeline offline.
- Scene inputs are the recorded clips in `assets/clips/real/`. The pipeline processes them for real each run.
- Audio plays in the browser (served from `/demo/audio/`), so it goes wherever the laptop's sound output goes. The directive plays in the left channel only.

## 7. Storyboard (2:00)

| Time | Mode | What's heard | Presenter says |
| --- | --- | --- | --- |
| 0:00 | Audio | Tower call, then the squeal | (silent) |
| 0:07 | Audio | | "That was an instruction to stop before a runway. The pilot never heard it." |
| 0:15 | Audio | Chime. "Advisory. Transmission blocked. Likely hold short Runway 33. Awaiting controller." | "Found locally in under a millisecond." |
| 0:28 | Audio | Controller: "Blocked call to Cessna 1-2-3: hold short Runway 33. Approve?" "Approve." "Approved, sending to N123AB." | "A human approves every directive." |
| 0:42 | Audio | Directive, left ear | |
| 0:50 | Audio | Readback "runway 23". "Readback incorrect. Runway tree tree." Correct readback. "Readback correct." | (pause) |
| 1:05 | Audio | "Unstep, what runway was I told to stop at?" Answer. | "Hands stay on the yoke." |
| 1:15 | Full | Timeline reveal: struck-out words, 23 vs 33, latency strip | "Every word and millisecond, measured live." |
| 1:40 | Full | Elastic card: agents, FAA citation, ES|QL | "And every event becomes safety analytics." |
| 1:52 | Close | | "No instruction lost or misheard. Humans stay in charge." |

30-second variants lead with one card each: Cartesia (readback catch and word highlight), Moss (hint and pilot question with ms and source), Elastic (agents, citation, ES|QL).

## 8. Research summary

- Winning demos open with a pain the room can feel, then spend most of the time on a live demo built around one memorable moment (AngelHack, Reskilll). Our moment is the squeal.
- Show the hidden work (retrieval, agents) with numbers on screen, don't narrate what's visible, don't show code (AngelHack, Reskilll, shkspr).
- Past Cartesia winners made the voice exchange the product (Cartesia Hacktober). Past Elastic winners showed Agent Builder and ES|QL live (Elastic Cal Hacks 12.0 recap).
- Plan for failure: cached audio, replay mode, recorded backup video, laptop plugged in, sleep and notifications off.
- Aviation conventions: dark background, red and amber reserved for warning and caution, never color alone (FAA display guidance, AC 25-11).

Sources: [AngelHack](https://angelhack.com/blog/10-tips-to-help-you-rock-your-next-hackathon-demo/), [Reskilll](https://blogs.reskilll.com/hackathon-demo-presentation-tips-pitch-3-minutes-win-2026/), [shkspr](https://shkspr.mobi/blog/?p=32308), [Cartesia Hacktober](https://www.cartesia.ai/blog/hacktober), [Elastic Cal Hacks 12.0](https://www.elastic.co/search-labs/blog/agent-builder-projects-learnings-cal-hacks-12-0), [LiveKit Agents UI](https://docs.livekit.io/frontends/agents-ui/audio-visualizer), [NASA ASRS Directline](https://asrs.arc.nasa.gov/publications/directline/dl1_read.htm).

## 9. Demo-day checklist

- Phone hotspot first, venue wifi second. Moss search runs locally either way.
- External speaker. Say "in the left ear" aloud since a hall can't hear stereo.
- Laptop plugged in, sleep and notifications off, browser full screen (F11).
- Recorded 2:00 backup video on the laptop and a phone, plus a 30-second cut per sponsor.
- Code freeze 2 hours before judging.
