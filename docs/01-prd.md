# Unstep: Product Requirements Document

| Field | Value |
| --- | --- |
| Status | Draft v0.2 |
| Last updated | 2026-10-23 |
| Related | [Changes](02-changes.md), [Mistakes and Lessons](03-mistakes-and-lessons.md), [Work Split](04-work-split.md), [Architecture](05-architecture.md), [Research](06-research.md), [Sponsor Review](07-sponsor-review.md) |

## 1. Executive Summary

Air Traffic Control (ATC) and aircraft still talk over analog VHF half-duplex radio, a design from the 1950s. When two people key their microphones at the same moment, the transmissions collide and turn into unreadable static. Pilots call this getting "stepped on."

In February 2026 the NTSB reportedly found that, seconds before a fatal collision, a life-saving ATC command was erased by a 0.8-second static overlap. (Source still needed, see M-005. Do not lead the pitch with this until it is cited.) Today neither the tower nor the pilot knows for sure what was blocked.

Unstep fixes this with two parts:

- An **edge AI safety box** in the cockpit. The target hardware is a Raspberry Pi 5. For now it runs as a laptop simulator.
- A **multi-agent supervisory grid** on the ATC ground side, built on Elastic.

When a transmission is stepped on, the system:

1. Detects the collision from the audio, backed up by Cartesia's end-of-speech detection.
2. Recovers the controller's original words with Cartesia speech-to-text on the tower audio.
3. Hands context between agents through a shared Moss memory space, which also keeps working offline.
4. Verifies the correct procedure against the FAA rulebook with Elastic hybrid search.
5. Shows the drafted directive to a human controller for approval.
6. Speaks the approved directive into the pilot's headset in a distinct advisory voice.
7. Listens to the pilot's readback and checks it matches, repeating the instruction if not.

Voice runs through the whole loop: transcription in, speech out, and a readback check that closes it.

## 2. Problem Statement

| Aspect | Today |
| --- | --- |
| Channel | Shared half-duplex VHF, one speaker at a time |
| Failure | Simultaneous transmissions produce a heterodyne squeal or static |
| Detection | Neither side reliably knows a message was lost |
| Recovery | Depends on someone noticing and asking "say again" |
| Audit | No structured record of what was blocked |

## 3. Goals and Non-Goals

### Goals

- Detect stepped-on transmissions in the cockpit within 10 ms.
- Recover the intended instruction from the controller's own transmission and present it to a human for approval.
- Deliver the approved instruction privately to the pilot's headset, and confirm the pilot understood it.
- Keep a complete, queryable audit trail of every event.

### Non-Goals

- No autonomous action. Agents never issue commands without human sign-off.
- No replacement of the primary VHF radio or of standard phraseology.
- No control of the aircraft. Unstep only advises by audio.

### Current Scope

- Raspberry Pi integration is on hold. The Pi 5 is still the target hardware, but for now the cockpit edge runs as a software simulator on a laptop, with recorded radio audio and a simulated PTT/squelch signal. See [Work Split, section 3a](04-work-split.md#3a-on-hold-raspberry-pi-integration).
- One demo flow must work every time before anything else is added (see section 11).

## 4. Users

| User | Need |
| --- | --- |
| Pilot | Know immediately that an instruction was blocked, what it said, and that their readback was correct |
| Ground controller | See blocked transmissions and approve the correction in one click |
| Safety inspector / NTSB | Query every anomaly, verification, sign-off and readback after the fact |

## 5. System Architecture

Full data flow diagrams are in [Architecture](05-architecture.md).

### 5.1 Cockpit Edge (Local Reflex Layer)

**Hardware:** target is a Raspberry Pi 5 connected to the aircraft audio panel and the Push-to-Talk (PTT) squelch line. For now, a laptop simulator.

**Moss (shared agent memory and local search):**

- **Shared context space.** Edge and ground agents hand off context by reading and writing a shared Moss space, not by messaging each other.
- **Local semantic search.** Before flight, the edge indexes the airport's taxiway layout, NOTAMs, local procedures and the aircraft's recent clearances. When static hits, it searches this locally in under 5 ms.
- **Offline indexing.** The edge keeps indexing locally when the cloud link is gone, so it still knows recent context and can raise a local alert (M-003).
- **Monitoring.** Everything written to the shared space gives a running view of each aircraft's state and recent events.
- How Moss runs (in-process, WebAssembly, Rust, sync model) must be checked against the Moss docs before we claim it (S-6, M-010).

**Cartesia (voice in and out):**

| Use | What it does |
| --- | --- |
| Cut-off detection | End-of-speech detection on the received audio flags a transmission that stops mid-instruction, a second signal next to the audio collision detector |
| Text-to-speech | Speaks the approved directive into the pilot's left ear-cup, first audio in under 90 ms |
| Advisory voice | A distinct voice and tone so the pilot never mistakes it for real ATC (S-4) |
| ATC pronunciation | Numbers spoken the ATC way: "niner", "tree", "fife" |
| Readback check | Speech-to-text on the pilot's readback, compared with the approved directive. A mismatch triggers "Readback incorrect" and a repeat |

### 5.2 Ground and Multi-Agent ATC Infrastructure (Orchestration and Compliance Layer)

**Elastic Cloud Serverless** is the orchestration and compliance core. The agents are built in Elastic Agent Builder and run as an **Elastic Workflow** (endpoint, trigger, action). They share context through Moss and never chat with each other.

| Component | Role |
| --- | --- |
| Tower transcription | Cartesia speech-to-text on the controller's own transmission, with key terms (callsigns, runway and taxiway names, "hold short"). This is the source of truth for what was blocked (M-002) |
| Agent 1: Intercept Agent | Picks up the anomaly from the shared Moss space and matches it with the tower transcript |
| Agent 2: Regulatory Compliance Agent | Runs Elastic hybrid search (BM25 plus dense vectors) over FAA Order JO 7110.65 to find the exact mandatory procedure and cite it |
| Human-in-the-Loop Gate | Queues a structured Proposed Safety Directive on the controller dashboard |
| Human Sign-Off | Controller clicks "Approve", which sends the directive to the cockpit |
| Fleet Audit | Every anomaly, verification, sign-off and readback is stored in Elastic indices and queried live with ES\|QL |

Example directive card:

```
Proposed Action: Hold Short of Runway 33
Source:          Tower transcript, 14:02:11Z
Confidence:      High (transcript match + rule match)
Verified via:    FAA JO 7110.65, paragraph TBD
[ Approve ]  [ Reject ]
```

The confidence method and the real paragraph number are still to be defined (M-008).

## 6. End-to-End Workflow

| Step | Stage | Component | Target |
| --- | --- | --- | --- |
| 1 | Pre-flight sync | Edge pulls NOTAMs and taxiway data from Elastic and indexes them in Moss | Before pushback |
| 2 | Stepped-on event | ATC says "Hold short of Runway 33" while a helicopter keys its mic | n/a |
| 3 | Detection | Audio collision detector plus Cartesia cut-off detection | Under 10 ms for the audio detector |
| 4 | Local context | Edge searches Moss for position, active runway, NOTAMs and recent clearances, then writes the event to the shared space | Under 5 ms search |
| 5 | Tower transcript | Cartesia speech-to-text on the controller's transmission | TBD |
| 6 | Verification | Elastic Workflow runs the Intercept and Compliance agents with hybrid search | TBD |
| 7 | Human approval | Card appears on the controller's screen, one-click approve | Human-paced |
| 8 | Headset delivery | Cartesia speaks: "Advisory. Transmission blocked. Hold short Runway tree tree. Read back." | Under 90 ms to first audio |
| 9 | Readback check | Pilot reads back, Cartesia transcribes, edge compares with the directive | TBD |
| 10 | Audit | Full interaction stored in Elastic, queryable with ES\|QL | Async |

### Step details

1. **Pre-flight sync.** Before pushback, the edge pulls active NOTAMs and sector maps from Elastic Cloud and indexes them in Moss. It can then search locally without a network.
2. **Stepped-on event.** ATC issues a clearance. A second station transmits at the same time and the heterodyne crash erases the instruction in the cockpit.
3. **Detection.** The audio detector sees the squelch break and collision signature. Cartesia's end-of-speech detection confirms the transmission was cut off.
4. **Local context.** The edge searches Moss for its local state and writes the event and context to the shared Moss space.
5. **Tower transcript.** On the ground, Cartesia transcribes what the controller actually said, using key terms so runway and taxiway names come out right.
6. **Verification.** The Elastic Workflow triggers. The Intercept Agent matches the event with the transcript. The Compliance Agent finds and cites the FAA procedure.
7. **Human approval.** A card appears on the controller's screen. The controller approves with one click.
8. **Headset delivery.** Cartesia speaks the directive in the advisory voice into the pilot's left ear.
9. **Readback check.** The pilot reads the instruction back. If it matches, the system logs "readback correct." If not, it says "Readback incorrect" and repeats the instruction. After two failed readbacks it flags the controller.
10. **Audit.** Every step is stored in Elastic for post-flight safety analysis.

## 7. Functional Requirements

| ID | Requirement |
| --- | --- |
| FR-1 | The edge must detect a collision from the audio and PTT/squelch signals. |
| FR-2 | The edge must index airport and sector data locally in Moss before flight. |
| FR-3 | The edge must write anomaly context to the shared Moss space and trigger the ground workflow when a link is available. |
| FR-4 | The ground system must transcribe the controller's transmission and use it as the source of the directive. |
| FR-5 | The ground system must propose a directive with a defined confidence and a real rule citation. |
| FR-6 | No directive may reach the cockpit without explicit human approval. |
| FR-7 | Approved directives must be spoken into the pilot headset only, not broadcast on VHF. |
| FR-8 | The headset voice must be clearly distinct from ATC and use ATC number pronunciation. |
| FR-9 | The edge must check the pilot's readback and repeat the directive on a mismatch. |
| FR-10 | Every event, agent output, human decision and readback must be stored and queryable. |
| FR-11 | No API keys or secrets may be committed to the repo. |

## 8. Latency Budget

| Segment | Target | Notes |
| --- | --- | --- |
| Collision detection | Under 10 ms | On the edge |
| Local search (Moss) | Under 5 ms | On the edge |
| Tower transcript (Cartesia STT) | TBD | Ground |
| Context handoff and workflow trigger | TBD | Depends on Moss sharing and link |
| Agent verification | TBD | Hybrid search plus agent reasoning |
| Human approval | Human-paced | Seconds, not milliseconds |
| Directive delivery to edge | TBD | Depends on Moss sharing and link |
| TTS first audio (Cartesia) | Under 90 ms | Measured from the directive arriving on the edge |
| Readback check | TBD | From end of pilot speech to verdict |

The 90 ms figure covers speech synthesis only. It is not the end-to-end time from collision to headset (M-001). During the demo we show the Moss search time, the Cartesia time to first audio and the end-to-end time without the human on screen.

## 9. Open Questions

These are tracked in detail in [Mistakes and Lessons](03-mistakes-and-lessons.md) and [Sponsor Review](07-sponsor-review.md).

- What datalink connects the aircraft to the ground in flight? (M-003)
- Does Cartesia TTS run on the edge, or is it a cloud call? (M-004)
- What is the source for the February 2026 NTSB finding? (M-005, S-9)
- What certification path applies to tapping a certified aircraft's audio panel? (M-006)
- How is "immutable" audit storage actually guaranteed? (M-007)
- How is the directive confidence score calculated? (M-008)
- How does Moss share a space between the edge and the ground, and how does it actually run? (M-010, S-6)
- What does the sponsor note "Slack (Grant)" mean?
- Is "ATC practice" mode a feature or just an idea? Not in scope until the main flow works.

## 10. Research Plan

The pitch needs real numbers. Every claim must be backed by a source or by our own measurement. Full details and the evidence table are in [Research and Evidence](06-research.md).

| Area | What we need to show | Owner |
| --- | --- | --- |
| Problem size | How often transmissions are blocked (NASA ASRS, FAA runway incursion data) | Dev B |
| Safety impact | NTSB investigations naming blocked transmissions, plus the source for the February 2026 finding | Dev B |
| Existing options | Why anti-blocking radios and CPDLC don't solve it | Dev B |
| Responsibility | Rules on recording and transcribing ATC audio | Dev B |
| Feasibility | Published latency for Cartesia TTS and STT, and for Moss search (Pi 5 audio latency on hold) | Dev A |
| Detection | Evidence that collisions and cut-offs can be detected from audio | Dev A |
| Moss model | How Moss runs and shares a space between machines | Dev A |
| Our prototype | Measured latency for each segment in section 8 | Both |

**Deliverable by end of day 1:** each owner has filled their rows in the evidence table, and the three headline numbers in [Research section 5](06-research.md#5-headline-numbers-for-the-pitch) are written using High confidence sources only.

## 11. Demo Flow

One flow that must work every time. Nothing else is added until it does.

1. A recorded clip plays: "Cessna 1-2-3, hold short Runway 33" with a helicopter squeal over it.
2. The edge flags the collision. The on-screen overlay shows the detection and Moss search times.
3. The tower transcript appears on the controller dashboard with the directive card and its FAA citation.
4. The controller clicks Approve.
5. The advisory voice speaks the directive in the left ear only. The overlay shows Cartesia's time to first audio.
6. The pilot reads back, first wrong, then right. The system catches the mistake, repeats, then confirms.
7. A live ES\|QL query shows the full audit trail for the event.

## 12. Responsibility

| Area | Approach |
| --- | --- |
| Human control | Agents never act alone. Every directive needs controller approval |
| Not mistaken for ATC | Distinct advisory voice, and every message starts with "Advisory" |
| Privacy | Tower audio is recorded and transcribed only to recover blocked instructions. Retention and access rules go in the README |
| Accessibility | Spoken directives are also shown as text on the dashboard and the edge screen. Readback checks help with high workload or hearing difficulty |
| Secrets | API keys live in a local `.env` file that is never committed |

## 13. Sponsor Fit

Details and the benchmark against past winners are in [Sponsor Review](07-sponsor-review.md).

| Sponsor | How it is core to Unstep |
| --- | --- |
| Cartesia | The voice loop: tower transcription, cut-off detection, advisory speech, readback check |
| Moss | Shared agent memory, local semantic search, offline indexing, monitoring |
| Elastic | Agent Builder agents run as a Workflow, hybrid search over the FAA rulebook, live ES\|QL audit |
