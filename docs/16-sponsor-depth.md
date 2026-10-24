# Sponsor Depth: One Real Moment per Sponsor

How Unstep uses Moss, Elastic and Cartesia as the product, not as a storyline. Agreed in agent mail (D10, R18); Rishit's side reviews this page.

| Field | Value |
| --- | --- |
| Status | v0.1, 2026-10-24 |
| Owner | Deekshith's side writes it, Rishit's side reviews |
| Related | [PRD](01-prd.md), [Agentic Architecture](10-agentic-architecture.md), [Cartesia Feedback](09-cartesia-feedback.md), [Pilot App and Sponsor Plan](15-pilot-app-and-sponsor-plan.md) |

**Labels.** Built (with commit), Agreed (both sides said yes, not built yet), Proposed (waiting for an answer), Not now. Our sandbox can't reach Moss, Elastic or Cartesia, so "built" means checked with tests and mocks unless a live check is named.

## 1. The Rule

Every sponsor gets one moment in the demo that only that sponsor makes possible, with a measured number on the ATC console (Rishit's timing waterfall and panels show it). Model: past Devpost winners such as SpeakEasy, where Cartesia was the product, with a personal hook and a detailed feedback write-up.

## 2. The Three Demo Moments (picked in R18)

| # | Moment | Sponsor | Number on screen |
| --- | --- | --- | --- |
| 1 | **Three-way recovery (C1).** After a stepped-on call, everyone hears exactly what they need, privately: the plane gets the tower's lost words, the tower hears who was blocked and what they said, the blocked caller hears "your call was blocked, say again" | Cartesia | Time from the call ending to each person hearing their line |
| 2 | **Moss recovers the instruction (M3).** From the garbled fragment the cockpit heard ("Cessna 123, short runway 30" in Rishit's live run), the plane's own Moss session finds "hold short Runway 33", offline | Moss | Query text, top hit, score, search ms |
| 3 | **Elastic agents cite the rule (E2).** The decision card shows the FAA JO 7110.65 paragraph the Compliance agent found | Elastic | Workflow time, Elastic ES\|QL stats panel |

## 3. Moss: "The Plane's Own Memory, Built Live, On Board"

| # | Item | Status | Owner |
| --- | --- | --- | --- |
| M1 | A Moss session per plane (default 6), a frequency session on the hub written only by the Frequency Monitor, local fallback | Built (248d276). Six real sessions checked by Rishit: 0 to 1 ms searches, no cloud indexes | Deekshith's side |
| M2 | Every call a plane hears (static and gaps included) and every readback indexed into its own session as it arrives, with callsign, speaker, ts, stepped_on | Built (0b62b64), reviewed in R18 | Deekshith's side (in Rishit's `edge.py` with his yes) |
| M3 | **Hint as real search:** hybrid query of the plane's session with the garbled fragment, filtered on callsign and the last minutes. A ranked hit becomes a hint only if no newer clearance supersedes it, restrictive only, source shown | Agreed (R18) | Deekshith's side builds, Rishit's side reviews (`hint.py` is theirs) |
| M4 | "What did the tower tell me in the last minute?" as a session search filtered on ts | Built (0b62b64) | Deekshith's side |
| M6 | Flight log: when a flight ends (seat freed, reset, hub stop) the plane's session is copied into one shared `flightlog-<frequency>` session (writer "archive"), pushed once to Moss Cloud in the background, and the plane's session is dropped from the shared client. Per-aircraft sessions are still never pushed. `GET /live/flightlog?q=&callsign=` searches past flights | Built (this commit), offline with fakes; live push needs keys | Deekshith's side |
| M5 | Moss Inference answers may only quote records (`quoted_source`); it also translates the private repeat with a glossary | Built (Rishit's side, d711e89 for translation) | Rishit's side |

## 4. Elastic: "Elastic Decides and Remembers"

| # | Item | Status | Owner |
| --- | --- | --- | --- |
| E1 | Percolator readback matcher (each directive stored as a query), every message stored, `/live/stats` with ES\|QL and the console panel | Built (453c396, 6938288; panel 35ef61e) | Deekshith's side, panel Rishit's side |
| E2 | Agent Builder agents (Intercept, Compliance with search over FAA JO 7110.65, Readback Auditor) run by Elastic Workflows. The agents add the citation and can only lower confidence; the hub writes the instruction and the gateway enforces the human decision | Built as files plus a deploy script and hub client (a57af8c), not deployed: needs Deekshith's keys. FAA index (W2) still to fill | Deekshith's side |
| E3 | ES\|QL `CHANGE_POINT` "congestion spike" during free play | Not now (R18) | |

## 5. Cartesia: "Unstep Has No Screen; It Speaks in the Gaps, to the Right Person"

In the demo the pilot has only AirPods. The phone is the talk button and the radio box; text is for the projector.

| # | Item | Status | Owner |
| --- | --- | --- | --- |
| C0 | Streaming STT while the key is held (d3e183b), ink-2 words with ink-whisper times (f3d2d2a), fast replays (d92aac6), streamed advisory to the phone (167027a), pronunciation dictionary, cancel when the pilot talks, hold while the frequency is busy (P5, bc01591), per-station voices, radio-sounding transmissions with Unstep's voice clean (de4db82), measured repro ([09](09-cartesia-feedback.md)) | Built | both |
| C1 | Three-way recovery (section 2). Priority: restrictive to the addressee first, then the blocked-caller notice, then the controller note; permissive never automatic; anything older than 30 s dropped. No contract change (R19) | Built: controller note (570d30e), blocked-caller notice via `notify_blocked` with directives first (Rishit's ab2f1db, room call this commit), directives say "From Tower" (Rishit's eca04b0) | Room: Deekshith's side. Cockpit voice: Rishit's side |
| C2 | Eyes-free pilot mode: every screen cue becomes an earcon or a short spoken line. Test AirPods early: the mic may switch Bluetooth to call mode and break left-ear-only | Agreed (R18) | `app/`: Deekshith's side. Earcon wording: Rishit's side |
| C3 | Private advisory repeated in the pilot's language after the English (es, hi, fr, only if every number survives) | Built (d711e89; join picker 882d059) | Rishit's side, join Deekshith's side |
| C4 | Slower speech (0.85) for "readback incorrect" corrections. Urgent emotion skipped: sonic-3.6 offers calm, neutral, angry, content, sad | Built (d711e89) | Rishit's side |
| C5 | Console line per advisory: "waited X s for a gap, spoke Y s, overlapped nobody: 0 ms" | Agreed (R18) | Data: Deekshith's side. Drawing: Rishit's side |
| C6 | Voice clone of the consenting pilot | Not now (R17) | |

## 6. Personal Hook

A judge causes the stepped-on call with their own voice and hears the fix privately in their own AirPods, optionally in their own language. Like SpeakEasy's "sounds like you", the moment is about the person holding the phone.

## 7. Feedback Write-ups

[09-cartesia-feedback.md](09-cartesia-feedback.md) with measured numbers and workarounds is our Cartesia issues section. The same short sections for Moss and Elastic follow, only with what was measured on the live services.

### 7.1 Cartesia: our own evaluation (R21)

`scripts/eval_unstep.py --live --n 40` on Rishit's laptop with real Cartesia: 40 synthetic instruction and readback pairs (80 lines), Sonic TTS in, ink-2 with key terms out, audio sent fast.

| Metric | Value |
| --- | --- |
| Callsign accuracy | 0.95 |
| Action accuracy | 1.0 |
| Runway accuracy | 0.852 |
| Readback-error precision / recall | 0.882 / 1.0 (tp 15, fp 2, fn 0, tn 23) |
| STT finalize p50 / p95 | 598.5 ms / 1514 ms |

No wrong readback was missed; two correct readbacks were flagged (the safe direction: an extra correction). Finalize is longer than the repro script's 162 ms p50 because these lines are longer; the script now records each line's length and every miss (`rows`) so runway misses can become key terms or pronunciation fixes.

### 7.2 Moss (Rishit's runs)

| Observed | Value |
| --- | --- |
| Local session search, six plane sessions at once | 0 to 1 ms |
| Cloud indexes created by sessions | none (only `push_index()` writes one; we never push plane sessions) |
| Moss Inference first token, warm (translation) | about 165 ms |

### 7.3 Elastic

Not measured yet: the agents, workflows and FAA index need the live deploy on Deekshith's machine (`scripts/deploy_elastic.py`, `scripts/ingest_faa.py`). Offline checks only so far.

## 8. Decided in R19

| Item | Status | Owner |
| --- | --- | --- |
| Speaker-attributed text: "Advisory. From Tower, to you: ...", party-line summaries optional, last priority, only when nobody is talking | Agreed; "From Tower" prefix built (eca04b0) | Rishit's side |
| Replaying the controller's own clean words cut by word times | Not now (choppy audio, new safety logic). Next | |
| `turn.eager_end` / `turn.resume` to pre-render the advisory and cancel on a key-up (check on sonic-3.6 first) | Agreed | Rishit's side |
| Volume control, Infill, Voice Changer evaluation set | Not now | |
| Evaluation: our synthetic set and live sessions only (public datasets only if the licence clearly allows a public repo); callsign and runway accuracy, readback-error precision and recall, latency p50 and p95 | Built (559f45a), run live by Rishit's side (section 7.1) | Deekshith's side writes the script, Rishit's side runs it live |
| Per-hop STT finalize time on the trace (S1) | Built (7342002) | Deekshith's side |
| Readback check on `turn.eager_end` (S3) | Not now: a partial transcript could flag a pilot who hasn't finished | |
