# Work Split

How the two of us divide Unstep so we can build in parallel and get the full system wired end to end as early as possible.

| Field | Value |
| --- | --- |
| Status | Draft v0.4 |
| Last updated | 2026-10-23 |
| Related | [PRD](01-prd.md), [Changes](02-changes.md), [Mistakes and Lessons](03-mistakes-and-lessons.md), [Architecture](05-architecture.md), [Research](06-research.md), [Sponsor Review](07-sponsor-review.md), [Advice](08-advice.md) |

## 1. Strategy

1. **Agree on the contracts first.** We fix the message formats before writing anything else. After that, neither of us waits on the other.
2. **Mock the other side.** Each person builds against a fake version of the other's half, so both halves work alone from day one.
3. **Wire early on WebSocket.** The first end-to-end path (M2) uses plain WebSocket and fake data. It does not depend on Moss, Elastic or Cartesia behaving as we expect.
4. **Simulate the aircraft.** Recorded radio audio on a laptop, not a real audio panel (M-006). Raspberry Pi is on hold (section 3a).
5. **One owner per sponsor.** Each of us becomes the expert on our sponsor, writes its part of the pitch and answers its judges.
6. **One flow that works every time.** The [demo flow](01-prd.md#11-demo-flow-2-minutes) comes before anything else.

## 2. Owners

| Role | Owner | Area | Sponsor owned |
| --- | --- | --- | --- |
| Dev A | _name_ | Cockpit edge, cockpit voice, readback check, pilot voice queries, all Moss work including the Frequency Monitor | **Moss** and Cartesia in the cockpit |
| Dev B | _name_ | Gateway, tower transcription, controller voice approval, all Elastic work, dashboard, audit | **Elastic** and Cartesia on the ground |

Fill in the names. Cartesia is split by side: Dev A owns TTS, readback STT and pilot query STT in the cockpit. Dev B owns tower STT and the controller's voice approval loop on the ground.

### Why this split is balanced

| | Dev A | Dev B |
| --- | --- | --- |
| Build tasks | 10 | 10 |
| Effort (S = 1, M = 2, L = 3) | 20 | 20 |
| Sponsor depth | Moss: hint search, pilot queries, three indexes, handoff, monitoring | Elastic: Workflow, three Agent Builder agents, hybrid search, ES\|QL |
| Cartesia | TTS, pronunciation dictionary, chime, interruption, turn STT for readbacks and pilot queries, cockpit STT | Tower STT with key terms, PTT finalize, word timestamps, blocked words, controller voice approval (TTS and turn STT) |
| Hardest piece | Readback check with interruption (L) | Workflow with Intercept and Compliance agents (L) |
| Main dependency on the other | Needs `ApprovedDirective` from B (mocked until M2) | Needs `AnomalyEvent` from A (mocked until M2) |

If one of us finishes early, take the other's lowest task in the list rather than starting new scope.

## 3. Shared Contracts (Both, do first)

We agree on these before splitting up. They live in `contracts/` once code exists. All go over the WebSocket gateway, which also writes each one to the Elastic events index.

| Contract | Written by | Fields |
| --- | --- | --- |
| `TowerTranscript` | Tower STT (B) | `transcript_id`, `frequency`, `callsign`, `ptt_start`, `ptt_end`, `text`, `words` (`word`, `start`, `end` as seconds from `ptt_start`), `confidence` |
| `AnomalyEvent` | Cockpit (A) | `event_id`, `callsign`, `frequency`, `squelch_open`, `squelch_close`, `overlap_start`, `overlap_end`, `heard_text`, `local_hint` (`text`, `kind` restrictive or none, `source_doc_id`, `source_text`, `moss_ms`), `gps`, `taxiway_node` |
| `ProposedDirective` | Compliance Agent (B) | `event_id`, `transcript_id`, `blocked_words`, `instruction_text`, `slots` (`callsign`, `action`, `runway`), `confidence`, `confidence_method`, `rule_citation` |
| `VoiceApproval` | Controller voice loop (B) | `event_id`, `heard_text`, `decision` (approve, reject, unclear), `attempt`, `ts` |
| `ApprovedDirective` | Gateway (B) | `event_id`, `instruction_text`, `slots`, `approved_by`, `approved_via` (voice or click), `approved_at`. A dashboard click sends one, but the gateway rebuilds it from the stored proposal, so the client can't change the text |
| `RejectedDirective` | Gateway (B) | `event_id`, `rejected_by`, `rejected_via` (voice, click or timeout), `rejected_at`. Lets the cockpit say "request say again" |
| `ReadbackResult` | Cockpit (A) | `event_id`, `readback_text`, `slots`, `match`, `attempt` |
| `PilotQuery` | Cockpit (A) | `query_id`, `callsign`, `question`, `answer`, `source_doc_id`, `moss_ms`, `ts` |
| `Insight` | Frequency Monitor (A) | `insight_id`, `frequency`, `callsign`, `kind`, `text`, `ts` |
| `AuditRecord` | Everyone | `event_id`, `stage`, `actor`, `ts`, `latency_ms`, `payload` |
| Transport | B hosts, A connects | One WebSocket gateway on the ground laptop. Each role may only send its own message types (`ALLOWED_SENDERS` in `unstep/gateway/server.py`). Undecided proposals expire after 60 s and are never sent. Optional `UNSTEP_GATEWAY_TOKEN` |
| Clock | Both | Every `ts`, `*_start`, `*_end` and `*_at` field is epoch milliseconds from one clock (the gateway's). Only `TowerTranscript.words` uses seconds from `ptt_start` |

**Done when:** the schemas are written as JSON examples and both of us have signed off.

## 3a. On Hold: Raspberry Pi Integration

Not assigned to anyone for now. We pick this up after the demo flow works on a laptop.

| Item | Why it waits |
| --- | --- |
| Running the cockpit stack on a Raspberry Pi 5 | The laptop simulator proves the flow first |
| Audio intercept board and audio panel connection | Needs hardware and raises certification questions (M-006) |
| Real PTT/squelch line tap | Simulated signal is enough for the demo |
| Pi 5 audio latency research (RA-3) | Only matters once we run on the Pi |

Keep audio input behind one interface so the code can move to the Pi later.

## 3b. Not in Scope Yet

| Item | When |
| --- | --- |
| ATC practice mode | Only after the demo flow is done |
| AI that runs ATC | Vision slide only |

## 4. Dev A: Cockpit, Voice and Moss

| # | Task | Size | Done when |
| --- | --- | --- | --- |
| A1 | Audio input from file or mic, simulated PTT, plus the demo clips (clean call, stepped-on call, wrong readback) | S | Each clip plays through the pipeline |
| A2 | Overlap detector that outputs the overlap window | M | Stepped-on clip flagged with the right window, clean clip ignored, under 10 ms |
| A3 | Cockpit STT (Cartesia, finalize on squelch close) | S | Cockpit transcript reads "Cessna 1-2-3 [static]" for the stepped-on clip |
| A4 | Moss `airport-<ICAO>` index and `flight-<callsign>` session seeded with the earlier taxi clearance, plus the local hint search with the restrictive-only rule and source record | M | Fragment "Cessna 1-2-3" finds "Runway 33, taxi via Bravo" and returns "Likely hold short Runway 33" with `time_taken_ms`. A permissive guess returns no hint |
| A5 | Frequency Monitor: subscribes to `TowerTranscript`, sole writer of the Moss `freq-<frequency>` session, two insights (repeated blocked calls, rising readback errors) | M | Insights appear on the gateway after a scripted run |
| A6 | Advisory TTS: chime, ATC number converter, pronunciation dictionary, calm voice, left channel only, word timestamps for highlighting | L | Chime, then "Advisory. Cessna one two tree, hold short runway tree tree" plays left ear only, words highlight |
| A7 | Readback check: turn STT on pilot mic, slot comparison, "Readback incorrect" repeat (max 2), interruption on `turn.start` | L | Wrong readback caught and repeated, right one confirmed, pilot can cut the voice off |
| A8 | Offline: pre-generated alert audio, flight session `push_index()` at end of event | S | Alert plays with the network off, flight session visible on the ground after push |
| A9 | Cockpit latency overlay (detection, Moss search, first audio, pilot query) and measurements | S | Numbers show live and are written into [Research section 4](06-research.md#4-our-own-measurements) |
| A10 | Pilot voice queries: Unstep key, Cartesia turn STT, intent for "last clearance", "say again" and "which taxiway", Moss search, spoken answer, `PilotQuery` audit | M | "Unstep, what was my last clearance?" is answered by voice with the Moss search time on the overlay |
| AR | Research RA-1, RA-2, RA-4 to RA-8 (1 hour) | | Rows filled with links |

Dev A total: S x4, M x4, L x2 = 4 + 8 + 6 = 18, plus the Moss section of the pitch and 30-second Moss version = 20.

## 5. Dev B: Gateway, Tower and Elastic

| # | Task | Size | Done when |
| --- | --- | --- | --- |
| B1 | WebSocket gateway that relays all contracts and writes each one to the Elastic events index | S | A mock cockpit and mock dashboard exchange messages, all visible in Elastic |
| B2 | Tower STT (Cartesia manual mode): stream while PTT is held, `finalize` on release, key term list, word timestamps | M | Runway, taxiway and callsign come out right, words have timestamps |
| B3 | Blocked words: mark tower words inside the overlap window | S | Card shows "Cessna 1-2-3, ~~hold short Runway 33~~" |
| B4 | FAA Order JO 7110.65 indexed in Elastic with hybrid search (BM25 plus vectors) | M | "hold short" query returns the right paragraph |
| B5 | Elastic Workflow (endpoint, trigger, action) running the Intercept and Compliance agents in Agent Builder | L | Trigger with an `event_id` produces a `ProposedDirective` with a real citation and defined confidence (M-008) |
| B6 | Readback Auditor agent | S | Every `ReadbackResult` gets an audit outcome in Elastic |
| B7 | Controller dashboard: card with blocked words, Approve or Reject as the click fallback, readback status, monitoring panel, live word highlighting | L | One click sends `ApprovedDirective`, insights and readback status update live |
| B8 | Audit and live ES\|QL: event trail, blocked calls per hour, readback error rate by frequency | M | Queries run live on screen (M-007) |
| B9 | Ground latency measurements, including "Approve" spoken to directive sent | S | Numbers written into [Research section 4](06-research.md#4-our-own-measurements) |
| B10 | Controller voice approval: chime and Cartesia TTS prompt in the controller headset, Unstep key with turn STT for "Approve" or "Reject", repeat-back, one retry, 10 second timeout, `VoiceApproval` contract | M | Saying "Approve" sends the directive and is repeated back. "Approve" played on the radio clip does nothing. Silence sends nothing |
| BR | Research RB-1 to RB-9 (1 hour) | | Rows filled with links |

Dev B total: S x4, M x4, L x2 = 4 + 8 + 6 = 18, plus the Elastic implementation write-up the sponsor asked for = 20.

## 5a. Shared Tasks

| # | Task | Lead | Done when |
| --- | --- | --- | --- |
| S1 | Contracts as JSON examples (M0) | Both | Signed off |
| S2 | README with setup, Cartesia features used, known limitations | B | At repo root |
| S3 | Privacy and accessibility notes for README and pitch | A | In README |
| S4 | `.env` for keys, short-lived tokens for the browser | A | No keys in the repo or history |
| S5 | 2-minute demo-first presentation, plus a 30-second version per track | Both | Rehearsed twice |

## 6. Milestones

| Milestone | What works | Tasks |
| --- | --- | --- |
| M0: Contracts | Schemas agreed | S1 |
| M1: Halves alone | Each side runs against its own mock | A1, A2 and B1 |
| **M2: First wire** | **Fake stepped-on event goes cockpit to gateway to dashboard, Approve comes back, text prints in the cockpit. WebSocket only** | **Both** |
| M3: Real voice and search | Cartesia STT on both sides, Moss hint, FAA hybrid search | A3, A4 and B2, B3, B4 |
| M4: Demo flow | The full [demo flow](01-prd.md#11-demo-flow-2-minutes) works by voice, including readback, pilot query, voice approval and Workflow | A6, A7, A10 and B5, B7, B10 |
| M5: Depth and polish | Monitoring, auditor, ES\|QL stats, offline alert, latency overlay, README, pitch | A5, A8, A9 and B6, B8, B9, S2 to S5 |

M2 is the main early target. If we fall behind, use the [cut list](01-prd.md#13-cut-list).

## 7. Day 1 Plan

Goal for the end of the day: M2 works, and the headline numbers are backed by sources.

| Block | Dev A | Dev B |
| --- | --- | --- |
| 1: Kickoff | Together: contracts (M0), fill in owner names | Same |
| 2: Morning | Research AR (1 hour), then A1, A2 | Research BR (1 hour), then B1 |
| Midday sync | Swap findings, connect cockpit to gateway | Same |
| 3: Afternoon | Push for M2 together, then start A4 | Push for M2 together, then start B2 |
| 4: End of day | Measure cockpit latency | Fill evidence gaps, write the headline numbers |
| Wrap-up | Commit and push, log changes and mistakes | Same |

Research is time-boxed and never blocks the build.

## 8. Working Rules

- Commit and push after each task, with a one-line title and bullet-point description.
- Log notable changes in [02-changes.md](02-changes.md) and mistakes in [03-mistakes-and-lessons.md](03-mistakes-and-lessons.md).
- Any contract change needs both of us to agree, and gets a changes log entry.
- If you're blocked on the other half, extend your mock instead of waiting.
- Check every vendor claim against the vendor's own docs before it goes in the PRD or pitch (M-010, M-011).
- Say "stepped-on" or "blocked," never "collision," for radio overlap (M-012).
- Voice first: if a feature only works by clicking, add the voice path or ask why not (M-013).

## 9. Integration Checkpoints

| Checkpoint | Test |
| --- | --- |
| After M0 | Each of us sends a sample message through the gateway, and the other parses it |
| After M2 | Full fake path 10 times in a row without errors |
| After M3 | Real STT and Moss on the demo clip, latency recorded |
| After M4 | Full demo flow 5 times in a row with the screens off until step 7, including the wrong readback and the pilot query |
| Before demo | Full dry run, plus a dry run with the network off |
