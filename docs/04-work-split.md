# Work Split

How the two of us divide Unstep so we can build in parallel and get the full system wired end to end as early as possible.

| Field | Value |
| --- | --- |
| Status | Draft v0.1 |
| Last updated | 2026-10-23 |
| Related | [PRD](01-prd.md), [Changes](02-changes.md), [Mistakes and Lessons](03-mistakes-and-lessons.md), [Architecture](05-architecture.md), [Research](06-research.md) |

## 1. Strategy

1. **Agree on the contracts first.** We fix the message formats between cockpit and ground before writing anything else. After that, neither of us waits on the other.
2. **Mock the other side.** Each person builds against a fake version of the other's half, so both halves work alone from day one.
3. **Wire early, improve later.** The first goal is a thin end-to-end path with fake data. We swap in real Moss, Elastic and Cartesia one at a time after that.
4. **Simulate the aircraft.** We use recorded or generated radio audio on a laptop or Pi, not a real audio panel (see M-006).

## 2. Owners

| Role | Owner | Area |
| --- | --- | --- |
| Dev A | _name_ | Cockpit edge device: audio, detection, Moss, Cartesia |
| Dev B | _name_ | Ground side: Elastic, agents, controller dashboard, audit |

Fill in the names and swap roles if that fits our skills better.

## 3. Shared Contracts (Both, do first)

We agree on these together before splitting up. They live in `contracts/` once code exists.

| Contract | Direction | Contents |
| --- | --- | --- |
| `AnomalyEvent` | Cockpit to ground | `event_id`, `aircraft_id`, `timestamp`, `collision_duration_ms`, `gps`, `taxiway_node`, `audio_clip_ref` |
| `ProposedDirective` | Ground internal | `event_id`, `instruction_text`, `confidence`, `rule_citation`, `source_transcript` |
| `ApprovedDirective` | Ground to cockpit | `event_id`, `instruction_text`, `approved_by`, `approved_at` |
| `AuditRecord` | Both to Elastic | `event_id`, `stage`, `actor`, `timestamp`, `payload` |
| Transport | Both | One choice: WebSocket or MQTT. Local network for the demo. |

**Done when:** the schemas are written down as JSON examples and both of us have signed off.

## 4. Dev A: Cockpit Edge Device

| # | Task | Done when |
| --- | --- | --- |
| A1 | Audio input from a file or mic, plus a simulated PTT/squelch signal | A recorded clip plays through the pipeline |
| A2 | Collision detector (overlap or heterodyne signature) | Flags stepped-on clips, ignores clean ones, under 10 ms |
| A3 | Send `AnomalyEvent` to the ground (to a mock server at first) | Event shows up on the mock |
| A4 | Moss pre-flight cache with taxiway nodes and NOTAMs | Lookup returns position and node in under 5 ms |
| A5 | Receive `ApprovedDirective` | Directive text arrives from a mock sender |
| A6 | Cartesia TTS into the left headset channel | Approved text is spoken in the left ear only |
| A7 | Offline fallback: plain "transmission blocked, request say again" alert | Works with the network unplugged (see M-003) |
| A8 | Measure on-device latency for each segment | Numbers added to PRD section 8 |
| AR | Research RA-1 to RA-5 (time-boxed, 1 hour) | Rows filled in the [evidence table](06-research.md#3-evidence-table) with links |

## 5. Dev B: Ground Side

| # | Task | Done when |
| --- | --- | --- |
| B1 | Ground server that receives `AnomalyEvent` (Intercept Agent) | Events from a mock cockpit arrive and are stored |
| B2 | Tower audio capture and speech-to-text of the controller's transmission | We have the original instruction text for each event (see M-002) |
| B3 | Index FAA Order JO 7110.65 in Elastic with hybrid search (BM25 plus vectors) | Query for "hold short" returns the right paragraph |
| B4 | Regulatory Compliance Agent builds a `ProposedDirective` | Directive has a real rule citation and a defined confidence (see M-008) |
| B5 | Controller dashboard with an Approve/Reject card | One click sends `ApprovedDirective` |
| B6 | Audit logging into Elastic indices, plus ES\|QL queries for review | Every stage of an event can be queried (see M-007) |
| B7 | Measure ground-side latency for each segment | Numbers added to PRD section 8 |
| BR | Research RB-1 to RB-7 (time-boxed, 1 hour) | Rows filled in the [evidence table](06-research.md#3-evidence-table) with links |

## 6. Milestones

| Milestone | What works | Who |
| --- | --- | --- |
| M0: Contracts | Schemas and transport agreed | Both |
| M1: Halves alone | Each side runs against its own mock | A1 to A3 and B1, B5 |
| **M2: First wire** | **Fake collision goes from cockpit to dashboard, approval comes back, text is printed in the cockpit** | **Both** |
| M3: Real services | Moss, Elastic hybrid search and Cartesia replace the mocks | A4 to A6 and B2 to B4 |
| M4: Demo ready | Full scenario: "Hold short of Runway 33" is blocked, recovered, approved, spoken and audited | Both |
| M5: Polish | Offline fallback, latency numbers, audit queries, open mistakes resolved | A7, A8 and B6, B7 |

M2 is the main target. Once it works, everything after it is an upgrade to a system that already runs end to end.

## 7. Day 1 Plan

Goal for the end of the day: the first wire (M2) works, and the headline numbers are backed by sources.

| Block | Dev A | Dev B |
| --- | --- | --- |
| 1: Kickoff | Together: agree contracts (M0) and review the research questions | Same |
| 2: Morning | Research AR (1 hour), then A1 to A3 | Research BR (1 hour), then B1 and B5 |
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

## 9. Integration Checkpoints

| Checkpoint | Test |
| --- | --- |
| After M0 | Each of us sends a sample message, and the other parses it |
| After M2 | Run the full fake path 10 times in a row without errors |
| After M3 | Run the demo scenario with real services and record the latency |
| Before demo | Full dry run, plus a dry run with the network unplugged |
