# Unstep: Product Requirements Document

| Field | Value |
| --- | --- |
| Status | Draft v0.3 |
| Last updated | 2026-10-23 |
| Related | [Changes](02-changes.md), [Mistakes and Lessons](03-mistakes-and-lessons.md), [Work Split](04-work-split.md), [Architecture](05-architecture.md), [Research](06-research.md), [Sponsor Review](07-sponsor-review.md), [Advice](08-advice.md) |

**One line:** Unstep: no ATC instruction lost or misheard.

## 1. Executive Summary

Air Traffic Control (ATC) and aircraft still talk over analog VHF half-duplex radio, a design from the 1950s. When two stations transmit at the same moment, both calls turn into a squeal or static. Pilots call this getting "stepped on." Even when a call does get through, the pilot can mishear it and read back something different.

Voice communication between tower and pilot fails in two ways:

1. **Not heard.** The instruction was stepped on and never arrived.
2. **Misheard.** The pilot reads back something different from what was said.

Unstep catches both. It transcribes the tower and the cockpit, finds exactly which words were lost or misheard, has the correction checked against the FAA rulebook and approved by a human controller, then speaks it into the pilot's headset and checks the readback.

Unstep does not avoid aircraft collisions. It prevents the **communication failure** that can lead to one. The NTSB has reportedly linked a February 2026 fatal collision to a blocked ATC call (source still needed, M-005). We only use that story once it is cited.

**Vision:** the first step toward an AI co-controller that keeps humans in charge.

## 2. Terms

| Term | Meaning |
| --- | --- |
| Stepped-on / blocked transmission | Two radio transmissions overlap and one or both are lost. We never call this a "collision" |
| Collision | Aircraft hitting each other or an obstacle. Only used in this sense |
| Readback | The pilot repeating an instruction back to the controller |
| Advisory voice | Unstep's synthetic voice in the pilot's headset. Always starts with "Advisory" |
| Local hint | The cockpit's own best guess at a blocked instruction, from Moss search. Always labeled "Likely" |
| Directive | An instruction approved by a human controller |

## 3. Problem Statement

| Aspect | Today |
| --- | --- |
| Channel | Shared half-duplex VHF, one speaker at a time |
| Failure 1 | Simultaneous transmissions produce a heterodyne squeal or static |
| Failure 2 | Readback errors are only caught if the controller notices |
| Detection | Neither side reliably knows a message was lost or misheard |
| Recovery | Depends on someone asking "say again" |
| Audit | No structured record of what was blocked or misheard |

## 4. Scope

| In or out | Item | Why |
| --- | --- | --- |
| **In** | A: Blocked transmission recovery | The core problem |
| **In** | B: Readback checking | Same pipeline as A, and makes voice two-way |
| **In** | Thin monitoring agent | Reads what the pipeline already produces and raises insights. Adds Moss and Elastic depth without touching the live path |
| Out | AI that runs ATC | Unsafe, against our human-approval rule, too big. Vision slide only |
| Out | Collision avoidance | Radar and TCAS territory, a different product |
| On hold | Raspberry Pi hardware | Laptop simulator first ([Work Split 3a](04-work-split.md#3a-on-hold-raspberry-pi-integration)) |
| Later | ATC practice mode | Only after the demo flow works |

### Goals

- Detect stepped-on transmissions on the cockpit side as they happen.
- Show exactly which words were blocked, using tower and cockpit transcripts.
- Recover the instruction from the controller's own transmission and get human approval.
- Deliver it to the pilot's headset in a voice that can't be mistaken for ATC.
- Catch wrong readbacks and correct them by voice.
- Keep a complete, queryable audit trail and live frequency stats.

### Non-Goals

- No autonomous action. A human approves every directive.
- No replacement of the primary VHF radio or standard phraseology.
- No control of the aircraft. Unstep only advises by audio and screen.
- No voice cloning of controllers.

## 5. Users

| User | Need |
| --- | --- |
| Pilot | Know immediately that an instruction was blocked, what it said, and that their readback was correct |
| Ground controller | See what was blocked or misheard and approve the correction in one click |
| Supervisor | See trends on a frequency, such as repeated blocked calls or rising readback errors |
| Safety inspector / NTSB | Query every event, verification, sign-off and readback after the fact |

## 6. System Design

Full diagrams are in [Architecture](05-architecture.md). Detailed sponsor usage is in [Advice](08-advice.md).

### 6.1 Principles

- **Live messages go over WebSocket.** Moss is memory, not a message bus.
- **Moss is each agent's fast local memory**, with handoff at clear points (end of an event, end of a flight) and one writer per index.
- **Elastic orchestrates and remembers.** Every event is also written to an Elastic index so Agent Builder agents can read it.
- **A human approves every directive.**

### 6.2 Cockpit Edge (laptop simulator for now)

| Part | What it does |
| --- | --- |
| Overlap detector | Finds the squeal or heterodyne signature and the time window it covers |
| Cockpit transcript | Cartesia STT on the received audio, finalized on PTT release |
| Local hint (Moss) | Searches the flight session and airport index with the fragment that was heard. Gives a "Likely" hint in a few milliseconds, with the search time on screen |
| Advisory voice (Cartesia TTS) | Speaks directives in the left ear only, calm advisory voice, ATC numbers |
| Readback check | Cartesia turn-based STT on the pilot mic. Our code compares callsign, action and runway with the directive. Pilot speech interrupts the advisory voice |
| Offline alert | Pre-generated "Advisory. Transmission blocked, request say again" audio |

### 6.3 Ground

| Part | What it does |
| --- | --- |
| Tower transcript | Cartesia STT on the controller's audio. Audio streams while PTT is held, `finalize` on release. Key terms for callsigns, runways, taxiways and phrases. Word timestamps |
| Blocked words | Tower words whose timestamps fall inside the overlap window are marked as blocked, for example "Cessna 1-2-3, ~~hold short Runway 33~~" |
| Gateway | WebSocket hub for live messages. Writes every message to an Elastic events index |
| Elastic Workflow | Endpoint, trigger, action. Runs the agents for each event |
| Intercept Agent (Agent Builder) | Matches the cockpit event with the tower transcript |
| Compliance Agent (Agent Builder) | Hybrid search (BM25 plus vectors) over FAA Order JO 7110.65 to cite the exact paragraph |
| Readback Auditor (Agent Builder) | Checks each readback result against FAA readback rules and records the outcome |
| Frequency Monitor | Indexes every transmission on the frequency in Moss and raises insights, for example "N123AB has had 2 blocked calls in 5 minutes." Never sends anything to the cockpit |
| Controller dashboard | Directive card with blocked words highlighted, Approve or Reject, readback status, monitoring panel |
| Audit | Every stage in Elastic indices. Live ES\|QL for audit and frequency stats |

### 6.4 Moss Indexes

| Index | Kind | Contents | Writer | Readers |
| --- | --- | --- | --- | --- |
| `airport-<ICAO>` | Long-term, loaded before flight | Runways, taxiways, NOTAMs, procedures, phraseology, key FAA paragraphs | Pre-flight setup | Cockpit, ground |
| `flight-<callsign>` | Cockpit session | Every clearance, readback and event for this aircraft | Cockpit only | Ground and audit, after `push_index()` |
| `freq-<frequency>` | Ground session | Every tower transcript on the frequency, with callsign and timestamp | Ground only | Ground agents, Frequency Monitor |

Sessions open before going offline, since opening one checks credentials with Moss Cloud.

### 6.5 Example Directive Card

```
Callsign:     Cessna 1-2-3 (N123AB)
Tower said:   "Cessna 1-2-3, hold short Runway 33"
Blocked:      hold short Runway 33
Proposed:     Hold short Runway 33
Confidence:   High (transcript match + rule match)
Verified via: FAA JO 7110.65, paragraph TBD
[ Approve ]  [ Reject ]
```

The confidence method and real paragraph number are still to be defined (M-008).

## 7. End-to-End Workflow

| Step | Stage | What happens |
| --- | --- | --- |
| 1 | Pre-flight | Cockpit loads `airport-<ICAO>` and opens `flight-<callsign>`. Ground opens `freq-<frequency>` |
| 2 | Stepped-on call | Tower says "Cessna 1-2-3, hold short Runway 33" while a helicopter keys its mic |
| 3 | Tower transcript | Cartesia transcribes the tower call with word timestamps and adds it to `freq-<frequency>` |
| 4 | Detection | Cockpit finds the overlap window and transcribes what it heard: "Cessna 1-2-3 [static]" |
| 5 | Local hint | Moss search gives a "Likely hold short Runway 33." Pilot hears: "Advisory. Transmission blocked. Likely hold short Runway 33. Awaiting controller." |
| 6 | Event | Cockpit sends `AnomalyEvent` over WebSocket. Gateway writes it to Elastic and triggers the Workflow |
| 7 | Verification | Intercept Agent matches the tower transcript and marks the blocked words. Compliance Agent cites the FAA paragraph |
| 8 | Approval | Controller sees the card and clicks Approve |
| 9 | Delivery | Advisory voice: "Advisory. Cessna one two tree, hold short runway tree tree. Read back." Words highlight as spoken |
| 10 | Readback | Pilot reads back. Wrong: "Readback incorrect" and repeat (max 2, then flag the controller). Right: confirmed |
| 11 | Monitoring | Frequency Monitor updates insights. Readback Auditor records the outcome |
| 12 | Audit | Every stage is in Elastic and queryable with ES\|QL |

### Local hint rules

The local hint is the only thing the pilot hears before a controller approves. To keep it safe:

- It always says "Likely" and ends with "Awaiting controller."
- It is never phrased as a clearance and never asks for a readback.
- It is replaced by the approved directive, or by "request say again" if the controller rejects.

## 8. Functional Requirements

| ID | Requirement |
| --- | --- |
| FR-1 | The cockpit must detect stepped-on transmissions and record the overlap window. |
| FR-2 | The tower and cockpit audio must both be transcribed, with word timestamps on the tower side. |
| FR-3 | The system must show which tower words were blocked. |
| FR-4 | The cockpit must give a labeled local hint from Moss search, following the local hint rules. |
| FR-5 | The ground must propose a directive with a defined confidence and a real FAA citation. |
| FR-6 | No directive may reach the cockpit without explicit human approval. |
| FR-7 | Directives must be spoken in the pilot headset only, in the left ear, never on VHF. |
| FR-8 | The advisory voice must be clearly distinct from ATC, start with "Advisory" and use ATC number pronunciation. |
| FR-9 | The cockpit must check readbacks, repeat on a mismatch, and flag the controller after two failures. |
| FR-10 | Pilot speech must interrupt the advisory voice. |
| FR-11 | The Frequency Monitor must raise insights from existing data and never send to the cockpit. |
| FR-12 | Every event, agent output, human decision, readback and insight must be stored and queryable. |
| FR-13 | No API keys or secrets may be committed. Browsers get short-lived tokens only. |

## 9. Latency

We show our own measured numbers on screen, not vendor figures (M-001). Vendor figures are background only.

| Segment | Target | Vendor or third-party figure |
| --- | --- | --- |
| Overlap detection | Under 10 ms | n/a |
| Moss local search | Under 10 ms | About 3 ms median, 5 ms p99 on 100k docs (Moss benchmark) |
| Tower transcript final after PTT release | TBD | TBD |
| Gateway and Workflow trigger | TBD | n/a |
| Agent verification | TBD | n/a |
| Human approval | Human-paced | n/a |
| TTS first audio | Measure | Under 90 ms model only (Cartesia). About 166 to 190 ms with network (third party) |
| Readback verdict after pilot stops | TBD | n/a |

Sources are in [Research](06-research.md#3-evidence-table).

## 10. Responsibility

| Area | Approach |
| --- | --- |
| Human control | A human approves every directive. Agents never act alone |
| Not mistaken for ATC | Distinct calm advisory voice, every message starts with "Advisory," no voice cloning of controllers |
| Local hint | Always labeled "Likely" and "Awaiting controller," never phrased as a clearance |
| Privacy | Tower audio is transcribed only to recover blocked or misheard instructions. Retention and access rules go in the README |
| Accessibility | Spoken words are highlighted on screen as they are said. Readback checks help with high workload or hearing difficulty |
| Secrets | Keys in a local `.env`, never committed. Browser gets short-lived tokens |

## 11. Demo Flow (2 minutes)

1. **Play the squeal for 5 seconds.** "That was an instruction to stop before a runway, and the pilot just lost it."
2. Dashboard: tower transcript with the blocked words highlighted (Cartesia word timestamps).
3. Cockpit: "Likely hold short Runway 33," with the Moss search time on screen.
4. Controller approves. The Workflow ran the agents and the card cites the FAA paragraph (Elastic).
5. Advisory voice in the left ear, words highlighted as spoken, first audio time on screen (Cartesia).
6. Pilot reads back wrong. Caught and corrected by voice. Reads back right. Confirmed.
7. Monitoring panel and a live ES\|QL query: blocked calls and readback errors on this frequency.
8. Close: "No instruction lost or misheard. Humans stay in charge."

We also prepare a 30-second version per track that opens with that sponsor's moment.

## 12. Sponsor Fit

| Track | Core use | Must-have demo moment |
| --- | --- | --- |
| Cartesia | STT on both sides with key terms and word timestamps, PTT finalize, turn STT for readbacks, advisory TTS with pronunciation dictionary, interruption | Wrong readback caught by voice, blocked words highlighted |
| Moss | Local hint search inside the voice loop, flight and frequency sessions, handoff, monitoring | Hint with search time on screen, agents sharing context through Moss |
| Elastic | Workflow running three Agent Builder agents, hybrid search for FAA citations, live ES\|QL audit and stats | FAA paragraph cited, live ES\|QL stats |

Benchmarks against past winners are in [Sponsor Review](07-sponsor-review.md) and [Advice, section 2](08-advice.md#2-benchmark-against-the-tracks).

## 13. Cut List

Cut in this order if time runs short:

1. Raspberry Pi (already on hold)
2. ATC practice mode
3. Offline mode beyond the pre-generated alert
4. Elastic Workflow, falling back to direct agent calls (last resort, costs Elastic points)

**Never cut:** readback check, blocked-word highlight, Moss search time on screen, human approval.

## 14. Open Questions

| Question | Tracked in |
| --- | --- |
| What datalink would carry events in a real aircraft? | M-003, RA-5 |
| Source for the February 2026 NTSB finding | M-005, RB-3 |
| Certification path for a real audio panel tap | M-006 |
| How audit storage is made tamper-resistant | M-007 |
| How directive confidence is calculated, and the real FAA paragraph | M-008 |
| Exact syntax of the Moss `$near` filter | RA-8 |
| Can Elastic Agent Builder call Moss (for example through MCP)? | RB-9 |
| What does the sponsor note "Slack (Grant)" mean? | Sponsor Review |

## 15. Research Plan

Every number in the pitch needs a source or our own measurement. Details and the evidence table are in [Research](06-research.md).

| Area | What we need to show | Owner |
| --- | --- | --- |
| Problem size | How often transmissions are blocked and readbacks go wrong (NASA ASRS, FAA) | Dev B |
| Safety impact | NTSB investigations naming blocked calls or readback errors, plus the February 2026 source | Dev B |
| Existing options | Why anti-blocking radios and CPDLC don't solve it | Dev B |
| Responsibility | Rules on recording and transcribing ATC audio | Dev B |
| Feasibility | Cartesia and Moss figures, overlap detection from audio | Dev A |
| Our prototype | Measured latency for every segment in section 9 | Both |

**End of day 1:** each owner's rows filled with links, and three headline numbers written from High confidence sources only.
