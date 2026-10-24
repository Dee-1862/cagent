# Work Split

How the two of us divide Unstep so we can build in parallel and get the full system wired end to end as early as possible.

| Field | Value |
| --- | --- |
| Status | Draft v0.2 |
| Last updated | 2026-10-23 |
| Related | [PRD](01-prd.md), [Changes](02-changes.md), [Mistakes and Lessons](03-mistakes-and-lessons.md), [Architecture](05-architecture.md), [Research](06-research.md), [Sponsor Review](07-sponsor-review.md) |

## 1. Strategy

1. **Agree on the contracts first.** We fix the message formats before writing anything else. After that, neither of us waits on the other.
2. **Mock the other side.** Each person builds against a fake version of the other's half, so both halves work alone from day one.
3. **Wire early, improve later.** The first goal is a thin end-to-end path with fake data. We swap in real Moss, Elastic and Cartesia one at a time after that.
4. **Simulate the aircraft.** We use recorded or generated radio audio on a laptop, not a real audio panel (see M-006). Raspberry Pi integration is on hold (see section 3a).
5. **One owner per sponsor.** Each of us becomes the expert on our sponsors, so the demo and write-up for each one are solid (see section 2).
6. **One flow that works every time.** The [demo flow](01-prd.md#11-demo-flow) comes before any extra feature.

## 2. Owners

| Role | Owner | Area | Sponsors owned |
| --- | --- | --- | --- |
| Dev A | _name_ | Cockpit edge simulator (laptop): audio, detection, Moss, cockpit voice, readback | **Moss**, Cartesia TTS and readback |
| Dev B | _name_ | Ground side: tower transcription, Elastic agents and Workflow, dashboard, audit | **Elastic**, Cartesia tower STT |

Fill in the names and swap roles if that fits our skills better. Cartesia is split by side: Dev A owns the voice in the cockpit, Dev B owns the transcription in the tower.

## 3. Shared Contracts (Both, do first)

We agree on these together before splitting up. They live in `contracts/` once code exists. All of them pass through the shared Moss space, with WebSocket as the fallback transport (M-010).

| Contract | Written by | Contents |
| --- | --- | --- |
| `AnomalyContext` | Edge | `event_id`, `aircraft_id`, `timestamp`, `collision_duration_ms`, `cutoff_detected`, `gps`, `taxiway_node`, `active_runway`, `recent_clearances`, `audio_clip_ref` |
| `TowerTranscript` | Tower STT | `transcript_id`, `timestamp`, `frequency`, `text`, `key_terms_matched`, `confidence` |
| `ProposedDirective` | Compliance Agent | `event_id`, `instruction_text`, `confidence`, `confidence_method`, `rule_citation`, `source_transcript_id` |
| `ApprovedDirective` | Dashboard | `event_id`, `instruction_text`, `approved_by`, `approved_at` |
| `ReadbackResult` | Edge | `event_id`, `readback_text`, `match`, `attempt` |
| `AuditRecord` | Everyone | `event_id`, `stage`, `actor`, `timestamp`, `latency_ms`, `payload` |
| Workflow trigger | Edge | `POST` to the Elastic Workflow endpoint with `event_id` |

**Done when:** the schemas are written down as JSON examples and both of us have signed off.

## 3a. On Hold: Raspberry Pi Integration

Not assigned to anyone for now. We pick this up after the demo path works on a laptop.

| Item | Why it waits |
| --- | --- |
| Running the edge stack on a Raspberry Pi 5 | The laptop simulator proves the flow first |
| Audio intercept board and audio panel connection | Needs hardware and raises certification questions (M-006) |
| Real PTT/squelch line tap | Simulated signal is enough for the demo |
| Pi 5 audio latency research (RA-3) | Only matters once we run on the Pi |

Write the edge code so it can move to the Pi later: keep audio input behind one interface and avoid laptop-only libraries where an easy alternative exists.

## 3b. Not in Scope Yet

| Item | When |
| --- | --- |
| "ATC practice" mode for pilots | Only after the demo flow is done |

## 4. Dev A: Cockpit Edge Simulator

| # | Task | Done when |
| --- | --- | --- |
| A1 | Audio input from a file or mic, plus a simulated PTT/squelch signal | A recorded clip plays through the pipeline |
| A2 | Collision detector (overlap or heterodyne signature) | Flags stepped-on clips, ignores clean ones, under 10 ms |
| A3 | Cartesia cut-off detection on the received audio | A clip that stops mid-instruction is flagged |
| A4 | Moss local index of taxiways, NOTAMs and recent clearances, with semantic search | Search returns runway, node and NOTAMs in under 5 ms |
| A5 | Moss shared context space: write `AnomalyContext`, read `ApprovedDirective`, call the Workflow trigger | Ground mock sees the context, edge sees an approval from the mock |
| A6 | Cartesia TTS in the left headset channel, with a distinct advisory voice and ATC number pronunciation | "Advisory. Hold short Runway tree tree" plays in the left ear only |
| A7 | Readback check with Cartesia STT, compare with the directive, repeat on mismatch | Wrong readback is caught and repeated, right one is confirmed |
| A8 | Offline fallback: keep indexing in Moss and play the local "request say again" alert | Works with the network unplugged (see M-003) |
| A9 | On-screen latency overlay for detection, Moss search and Cartesia first audio | Numbers show live during the demo |
| A10 | Measure edge latency for each segment | Numbers added to PRD section 8 |
| AR | Research RA-1, RA-2, RA-4 to RA-7 (time-boxed, 1 hour) | Rows filled in the [evidence table](06-research.md#3-evidence-table) with links |

## 5. Dev B: Ground Side

| # | Task | Done when |
| --- | --- | --- |
| B1 | Tower audio capture and Cartesia STT with key terms (callsigns, runways, taxiways, "hold short") | `TowerTranscript` gets runway and taxiway names right (see M-002) |
| B2 | Elastic Workflow with an endpoint trigger that starts the agents | Calling the endpoint with an `event_id` runs the agents |
| B3 | Index FAA Order JO 7110.65 in Elastic with hybrid search (BM25 plus vectors) | Query for "hold short" returns the right paragraph |
| B4 | Intercept and Compliance agents in Agent Builder, reading context from Moss | Agents produce a `ProposedDirective` with a real citation and a defined confidence (see M-008) |
| B5 | Controller dashboard with an Approve/Reject card, the transcript, and readback status | One click writes `ApprovedDirective` |
| B6 | Audit logging into Elastic indices, plus live ES\|QL queries for the demo | Every stage of an event can be queried on screen (see M-007) |
| B7 | Elastic implementation write-up (the sponsor asked for it) | Short doc explaining agents, Workflow, search and audit |
| B8 | Privacy and accessibility notes (S-8) | Notes ready for the README and pitch |
| B9 | Measure ground-side latency for each segment | Numbers added to PRD section 8 |
| BR | Research RB-1 to RB-8 (time-boxed, 1 hour) | Rows filled in the [evidence table](06-research.md#3-evidence-table) with links |

## 5a. Shared Tasks

| # | Task | Done when |
| --- | --- | --- |
| S1 | README with setup, Cartesia features used, known limitations (sponsor requirement) | README at repo root covers all three |
| S2 | `.env` for keys, never committed | `.gitignore` covers it and no keys are in history |
| S3 | Demo clip with a realistic squeal over the instruction | Clip plays reliably |
| S4 | 2-minute demo-first presentation | Rehearsed twice |

## 6. Milestones

| Milestone | What works | Who |
| --- | --- | --- |
| M0: Contracts | Schemas and transport agreed | Both |
| M1: Halves alone | Each side runs against its own mock | A1, A2, A5 and B2, B5 |
| **M2: First wire** | **Fake collision goes from edge to dashboard, approval comes back, text is printed on the edge** | **Both** |
| M3: Real services | Moss, Elastic hybrid search and Cartesia replace the mocks | A3, A4, A6 and B1, B3, B4 |
| M4: Demo ready | The [demo flow](01-prd.md#11-demo-flow) works end to end, including the readback check | A7 and B6, plus both |
| M5: Polish | Offline fallback, latency overlay, write-ups, README, open mistakes resolved | A8 to A10, B7 to B9, S1 to S4 |

M2 is the main target. Once it works, everything after it is an upgrade to a system that already runs end to end.

## 7. Day 1 Plan

Goal for the end of the day: the first wire (M2) works, and the headline numbers are backed by sources.

| Block | Dev A | Dev B |
| --- | --- | --- |
| 1: Kickoff | Together: agree contracts (M0) and review the research questions | Same |
| 2: Morning | Research AR (1 hour), then A1, A2, A5 | Research BR (1 hour), then B2, B5 |
| Midday sync | Swap findings, connect the two mocks | Same |
| 3: Afternoon | Push for M2 together | Same |
| 4: End of day | Measure real latency into [Research section 4](06-research.md#4-our-own-measurements) | Fill evidence gaps, write the headline numbers, update the PRD |
| Wrap-up | Commit and push, log changes and mistakes | Same |

Research is time-boxed and never blocks the build. Open questions carry over to day 2.

## 8. Working Rules

- Commit and push after each task, with a one-line title and bullet-point description.
- Log notable changes in [02-changes.md](02-changes.md).
- Log mistakes and lessons in [03-mistakes-and-lessons.md](03-mistakes-and-lessons.md).
- Any contract change needs both of us to agree, and gets a changes log entry.
- If you get blocked on the other person's half, extend your mock instead of waiting.
- Check every vendor claim against the vendor's own docs before it goes in the pitch (M-010).

## 9. Integration Checkpoints

| Checkpoint | Test |
| --- | --- |
| After M0 | Each of us writes a sample message to the shared space, and the other reads it |
| After M2 | Run the full fake path 10 times in a row without errors |
| After M3 | Run the demo scenario with real services and record the latency |
| Before demo | Full dry run, plus a dry run with the network unplugged |
