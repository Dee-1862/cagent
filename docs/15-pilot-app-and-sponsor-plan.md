# Pilot App, Crowd Demo and Sponsor Plan

The pilot side of the live room, how to host it for a demo where anyone in the room can join as a pilot, and a plan to use Moss, Cartesia and Elastic as the core of the product instead of as a plain STT, TTS or search call.

| Field | Value |
| --- | --- |
| Status | v0.1, 2026-10-24 |
| Owner | Deekshith's side (pilot app, hub join backend). ATC console: Rishit's side ([14-atc-console.md](14-atc-console.md)) |
| Code | `app/` (pilot app), `unstep/live/room.py`, `unstep/live/app.py` |
| Related | [Live Demo](11-live-demo.md), [ATC Console](14-atc-console.md), [Research](06-research.md) |

**Honesty note.** Our sandbox's network policy blocks Cartesia, Moss and Elastic, so nothing in sections 4 to 6 was run against the live services here. Vendor claims come from vendor pages read through search results and from the `moss` 1.21 package source. Every claim marked "check" must be confirmed on the vendor's own docs before it goes into the pitch (CLAUDE.md rule).

## 1. What Is Built

| Piece | What it does |
| --- | --- |
| Join on demand | `POST /live/join` gives the next free plane from a six-plane fleet (`scenario.FLEET`: Plane A to F) and starts its own cockpit agent. Seats are reserved for 20 s so two people tapping at once get different planes |
| Live key state | Every radio key press and release goes to every seat at once (`keyed`). Two keys down sends `stepon_live` to everyone, before any audio or transcript exists |
| Clock sync | Phones ping the hub and keep the fastest round trip (NTP style), so key and mic times are hub times. Error bound is half the best round trip |
| Pilot app (`app/`) | React, TypeScript, Vite. One tap: audio, mic, screen wake lock, join. Big hold-to-talk button with idle, ON AIR, "Tower is talking" and TALKED OVER states. Stepped-on banner, private "only you can hear this" advisory, readback result, tap-to-say lines (one deliberately wrong), Ask Unstep, timings panel |
| Hosting | One static build runs on Vercel or at `/pilot/` on the hub. `GET /live/pilot-link` returns the right join link for the QR code |

Checked end to end with three headless phones on the offline hub: a hold short stepped on by Plane B, the private advisory on Plane A, a wrong readback caught, the right one confirmed, no page errors.

## 2. Hosting for the Demo

Vercel serves static pages and functions; it does not keep a WebSocket server running, so the room itself stays on the tower laptop (the hub). Vercel hosts only the pilot app.

```
phones (Vercel pilot app, https)  --wss-->  tunnel  -->  tower laptop: python -m unstep.live
projector (ATC console)           ------------------>  same laptop, /live/atc/
```

1. On the laptop: `cd app && npm install && npm run build`, then `python -m unstep.live --host 0.0.0.0`.
2. Expose it over https with a tunnel (for example `cloudflared tunnel --url http://localhost:8765`). Https matters: phones only allow the microphone on https.
3. In `.env`: `UNSTEP_PUBLIC_URL=https://<tunnel host>`, `UNSTEP_ALLOWED_HOSTS=<tunnel host>`, `UNSTEP_PILOT_APP_URL=https://<app>.vercel.app`, `UNSTEP_ALLOWED_ORIGINS=https://<app>.vercel.app`, and a room token in `UNSTEP_GATEWAY_TOKEN` so strangers can't join.
4. Deploy `app/` to Vercel (root directory `app`, build `npm run build`, output `dist`).
5. The ATC console shows the QR from `/live/pilot-link`.

**Fallback with no internet:** phone hotspot, no tunnel. Run `python -m unstep.live --host 0.0.0.0 --https`: the hub makes a self-signed certificate for localhost and the laptop's LAN address (`data/certs/`, gitignored) and serves https and wss. Set `UNSTEP_PUBLIC_URL=https://<laptop IP>:8765` so the QR points there. Each phone opens `https://<laptop IP>:8765/pilot/` once and accepts the certificate warning; after that the mic works. With your own certificate use `--cert` and `--key`. Checked here: https and wss answer with the generated certificate (`tests/test_hub_https.py`); not yet tried on a real iPhone or Android. If a phone refuses the certificate, pilots use the tap-to-say lines over plain http, which still go on air through Cartesia TTS (or fake speech offline). The hosted Vercel app can't use a self-signed hub unless each phone has accepted the hub's certificate first, so the tunnel stays the main path.

**Public link anyone can try (Render):** the hub is a long-running Python server holding WebSockets, the shared room and Moss sessions in memory, so it can't run on Vercel's serverless functions. One Docker container (`Dockerfile`) serves everything: the hub, the ATC console at `/live/atc/` and the pilot app at `/pilot/`. On Render: New, Blueprint, pick this repo and branch (`render.yaml`), then fill the secret values in the dashboard.
- `UNSTEP_OFFLINE=1` (the default in `render.yaml`) uses fake speech and no API credits. Delete it to run live on Cartesia, Moss and Elastic.
- `UNSTEP_GATEWAY_TOKEN` is generated: only people with the QR link (it carries the token) can join and spend API credits. Set `UNSTEP_ATC_PASSWORD` for the tower seat.
- `UNSTEP_ALLOWED_HOSTS=*.onrender.com` and `FORWARDED_ALLOW_IPS=*` make links and QR codes use https behind Render's proxy, so phone mics work.
- One room for everyone who opens the link. `render.yaml` uses the free plan: no card needed, but it sleeps after about 15 minutes idle, takes about a minute to wake, and has 512 MB of memory (fine offline; live mode with Moss may be tight).
- Checked here by running the container's start command with Render-style host and proxy headers: the pilot link comes out as `https://<service>.onrender.com/pilot/?token=...`, all pages answer, a foreign host is refused. The Docker image itself was not built here (no Docker daemon in this sandbox).

Vercel stays optional: it can host the pilot app only (`app/`), pointed at the Render hub with `UNSTEP_PILOT_APP_URL` and `UNSTEP_ALLOWED_ORIGINS`.

## 3. Demo Flow for a Crowd

The laptop is the tower. Two judges get pre-joined phones (Plane A and B). The QR stays on screen so anyone can join as Plane C to F.

| # | Beat | The one "wow" |
| --- | --- | --- |
| 1 | Two judges hold their buttons on a count. Both phones flip to TALKED OVER, the projector flashes | The failure is something they did, and Unstep saw it in milliseconds (number on screen) |
| 2 | Tower says "hold short 33" while Plane B talks over it | Squeal on the room speakers |
| 3 | Plane A's phone turns purple: "Only you can hear this" | Private, left ear, Cartesia voice |
| 4 | Judge taps the wrong readback, Unstep catches it, then the right one | Big tick on the phone and on the projector |
| 5 | "Everyone with the QR, join and talk over each other" | Unscripted: proves it is real |
| 6 | Projector: Elastic stats for the session, per plane | The audit story |

Flow changes we recommend over the earlier plan: open with the judges causing the stepped-on call (beat 1) instead of a recording, show the measured detection time on the phone itself, and keep tap-to-say as the default input in a noisy hall.

## 4. Millisecond-Level Communication

What exists now and what would make "milliseconds" visible and true:

| Idea | Status | Why it matters |
| --- | --- | --- |
| Key-level stepped-on detection: two keys down = stepped on, broadcast at once | Built (`stepon_live`) | Detection no longer waits for audio, STT or the 300 ms quiet gap. Cost is one network hop |
| Clock sync with error bound | Built | We can say "Plane B keyed 412 ms into the tower's call, ±4 ms" instead of guessing |
| Stream mic audio in 100 ms frames while the key is held, instead of one clip on release | Next | Cartesia STT can start while the pilot is still talking, so the transcript is ready at release. The hub can also mix live |
| Overlap window from key times, cross-checked with the audio detector | Next | Radio truth from keys, audio detector as independent evidence. Show both and their difference in ms |
| Per-hop latency waterfall on the projector (key, uplink, detect, STT final, Moss, policy, TTS first audio, readback verdict) | Next | Every stage measured on one clock, which is PRD section 9 made visible |
| WebRTC data channel instead of WebSocket for key events | Later | Avoids head-of-line blocking on bad wifi. Only worth it if the hall network is poor |

## 5. Sponsor Plan: From Namesake to Core

### Moss (in-session indexing)

From the `moss` 1.21 source: `client.session(name)` is a local in-memory index. Embedding runs locally (default `moss-minilm`), docs are searchable once `add_docs` returns, queries are documented at about 1 to 10 ms, and only `push_index()` writes the cloud index, replacing it rather than merging (check on docs.moss.dev). That is what the Moss team meant by in-session indexing.

| Today | Push it to |
| --- | --- |
| One aircraft gets Moss, others local memory, out of caution about the plan's index limit | Done: every plane gets its own Moss session on join (`UNSTEP_MOSS_AIRCRAFT`, default 6). Rishit ran six real sessions at once: 0 to 1 ms searches, no new cloud indexes. Per-aircraft sessions are never pushed |
| Seeded clearances, queried for the hint | Index every transmission the moment it is transcribed, per plane and per frequency, with `callsign`, `speaker`, `ts`, `stepped_on` metadata |
| Hint search | Readback check as a second opinion: the readback queried against that plane's latest instruction, score shown next to the slot check |
| Ground has no Moss | Built: a frequency session on the hub (`freq-<frequency>`), a Moss session when live, written only by the Frequency Monitor from tower transcripts, so "what did tower say to Plane C in the last minute" is a local query in milliseconds |
| Nothing pushed | At the end of a flight, `push_index()` hands off the plane's session; ground queries it with `query_multi_index` across the airport index and the pushed sessions (check) |
| Moss Inference for free-form questions | Stream it (`stream=True`) straight into Cartesia TTS, grounded on the plane's own index (`indexes=[...]`) (check that Inference can see a session before push; assume not) |
| Text only | `$near` geo filter on runway and taxiway records from the plane's position: "you are 40 m from the Runway 33 hold short line" (check) |

### Cartesia

| Today | Push it to |
| --- | --- |
| Manual-finalize STT after release | Streaming during the key press (section 4), so finalize returns almost at once |
| Turn STT for readbacks | Start the readback check on `turn.eager_end` and drop it on `turn.resume`, which Cartesia's Pipecat guide says saves about 0.5 s (check) |
| Fixed key terms | Key terms rebuilt per connection from the fleet that is actually flying (limit about 100 terms, set at connect only, ink-2 only; check) |
| One advisory voice | Distinct voice per plane on the say lines, an urgent `emotion` for the stepped-on alert, calm for advisories (emotion is guidance, not strict; check on sonic-3.6) |
| Clean TTS on the radio | Radio band shaping on the hub (300 to 3400 Hz, noise, squelch tail) so the room hears a real radio, Unstep's voice stays clean, so the contrast itself says "this is not ATC" |
| Advisories can be talked over | Cancel the advisory context the moment the pilot keys (`keyed` message), already the PRD's FR-10, now driven by real key events |
| Live transcripts only | Batch STT with word timestamps on the whole session recording for a clean audit transcript in Elastic |

Rishit has found and fixed several Cartesia issues: idle TTS sockets reopened (57738b1), hanging STT handshakes retried with a 4 s timeout (20723b7), empty turn transcripts retried once, a 20 s deadline per TTS line and no double speaking (16b822c), and canonical phraseology so an STT slip like "holds short" can't fail a correct readback (19063b8). [09-cartesia-feedback.md](09-cartesia-feedback.md) records finalize latency from 76 ms to 7.4 s for the same clip. We asked Rishit in agent mail (D1 item 9) whether there are newer ones.

### Elastic

| Today | Push it to |
| --- | --- |
| Every message bulk-written to an events index | Keep it, and make Elastic decide things in the hot path |
| Mock ground agents | **Percolator clearance matcher:** each delivered directive is stored as a percolator query (callsign plus runway plus action). Every pilot transcript is percolated: a match confirms the readback, no match flags it. Expect tens of ms on a small set (check) |
| Planned Compliance agent | `semantic_text` over FAA JO 7110.65 with a pinned `inference_id`, hybrid with BM25, reranked, to cite the paragraph for each directive (check defaults on Serverless) |
| Planned Workflow per event | The hub calls the Workflow's manual trigger after each blocked call: percolate, then the Readback Auditor agent (`ai.agent` step) only on a mismatch, then index the finding. Keep it off the radio path because of LLM latency. No per-document trigger was found in the docs |
| ES\|QL in the plan | Agent Builder ES\|QL tools ("open clearances for callsign ?cs", "stepped-on calls in the last 10 minutes"), exposed over MCP so the console and the agents use the same tools (check endpoint) |
| Static stats | `CHANGE_POINT` on per-minute stepped-on counts: "congestion spike at 12:41" on the projector during free play (GA on Serverless; check) |

## 6. Dataset: Build and Validate Fast

No public labelled set exists for stepped-on detection or restrictive versus permissive instructions that we found, so we synthesize those and validate on real ATC speech for transcription.

| Need | Source | License note |
| --- | --- | --- |
| Real ATC speech, transcription and callsign slots | ATCO2 1 h test set (Hugging Face `Jzuluaga/atco2_corpus_1h`), UWB-ATCC (`Jzuluaga/uwb_atcc`) | Check each dataset card; likely non-commercial |
| Clean controller speech for overlap mixing | ATCOSIM (TU Graz) | Check the included license |
| Realistic incident scenarios | NASA ASRS narratives | Public, unverified reports |
| Not usable in a shipped dataset | LiveATC recordings | Terms forbid use in third-party products |

**Synthetic set (one day):**

1. 40 instruction templates from FAA phraseology, each tagged restrictive or permissive, with sampled callsigns, runways and taxiways.
2. 500 instruction and readback pairs, 30 percent with a labelled error (runway digit, callsign digit, missing "hold short", wrong taxiway).
3. Render with several Cartesia voices, then radio band shaping and noise at 5 to 20 dB SNR.
4. 300 radio mixes: 200 with a second station keyed at a random offset (exact overlap window and lost words stored as ground truth), 100 clean.
5. Split by template and by voice, not by clip, so the test set holds templates and voices never used for tuning.

**Validation:**

| Task | Metric |
| --- | --- |
| Transcription | WER with numbers normalized, plus exact-match F1 for callsign, runway, taxiway. Real and synthetic reported separately |
| Readback check | Precision and recall on "wrong", confusion matrix per error type |
| Stepped-on detection | Window IoU (hit at 0.5 or more), detection latency in ms, false alarms on clean calls |
| Restrictive or permissive | Accuracy and macro F1 |
| Hand labels | Both of us label the same 50 real clips; Cohen's kappa of 0.8 or more, otherwise fix the guidelines |

With 100 items a 95 percent interval is about plus or minus 10 points; 500 items gets it to about 4. Our own live room is also a data source: every judge session is a labelled stepped-on event (keys give ground truth), stored in Elastic.

## 7. Decisions Needed

| Question | Who |
| --- | --- |
| Auto-relay on or off by default for the demo, and the README "human approval for every directive" line | Deekshith and Rishit |
| Allow the network hosts in this sandbox's environment so we can test live (Cartesia, Moss, Elastic) | Deekshith |
| Vercel project name and the tunnel to use on demo day | Deekshith |
| Raise `UNSTEP_MOSS_AIRCRAFT` to 6 after a live check | Done (Rishit checked six sessions, R3) |
