# Unstep: Product Requirements Document

| Field | Value |
| --- | --- |
| Status | Draft v0.1 |
| Last updated | 2026-10-23 |
| Related | [Changes](02-changes.md), [Mistakes and Lessons](03-mistakes-and-lessons.md), [Work Split](04-work-split.md), [Architecture](05-architecture.md), [Research](06-research.md) |

## 1. Executive Summary

Air Traffic Control (ATC) and aircraft still talk over analog VHF half-duplex radio, a design from the 1950s. When two people key their microphones at the same moment, the transmissions collide and turn into unreadable static. Pilots call this getting "stepped on."

In February 2026 the NTSB reported that, seconds before a fatal collision, a life-saving ATC command was erased by a 0.8-second static overlap. Today neither the tower nor the pilot knows for sure what was blocked.

Unstep fixes this with two parts:

- An **edge AI safety box** in the cockpit, built on a Raspberry Pi 5.
- A **multi-agent supervisory grid** on the ATC ground side, built on Elastic.

When a transmission is stepped on, the system:

1. Detects the collision at the hardware level.
2. Uses Moss for instant local in-memory search of flight state.
3. Verifies the correct protocol through Elastic Cloud.
4. Drafts a safety correction.
5. Shows it to a human controller for approval (Human-in-the-Loop).
6. Uses Cartesia to speak the approved command into the pilot's headset, with first audio in under 90 ms.

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
- Recover the intended instruction and present it to a human for approval.
- Deliver the approved instruction privately to the pilot's headset.
- Keep a complete, queryable audit trail of every event.

### Non-Goals

- No autonomous action. Agents never issue commands without human sign-off.
- No replacement of the primary VHF radio or of standard phraseology.
- No control of the aircraft. Unstep only advises by audio.

### Current Scope

Raspberry Pi integration is on hold. The Pi 5 is still the target hardware, but for now the cockpit edge runs as a software simulator on a laptop, with recorded radio audio and a simulated PTT/squelch signal. See [Work Split, section 3a](04-work-split.md#3a-on-hold-raspberry-pi-integration).

## 4. Users

| User | Need |
| --- | --- |
| Pilot | Know immediately that an instruction was blocked, and what it said |
| Ground controller | See blocked transmissions and approve the correction in one click |
| Safety inspector / NTSB | Query every anomaly, verification and sign-off after the fact |

## 5. System Architecture

### 5.1 Cockpit Edge Device (Local Reflex Layer)

**Hardware:** Raspberry Pi 5 mounted in the cockpit, connected to the aircraft audio panel and the Push-to-Talk (PTT) squelch line.

**Moss (local in-memory search, under 10 ms):**

- Runs fully in-process through WebAssembly/Rust with no cloud network hops.
- Pre-loaded before flight with the airport's active taxiway layout, NOTAMs and sector clearance graphs.
- When static hits, resolves the missing local flight state in under 5 ms.

**Cartesia Sonic (audio engine, under 90 ms to first byte):**

- Built on State Space Models (SSMs).
- As soon as a correction is approved, streams the first byte of audio in under 90 ms.
- Delivers a clear, urgent co-pilot whisper into the pilot's left ear-cup during the radio silence gap.

### 5.2 Ground and Multi-Agent ATC Infrastructure (Orchestration and Compliance Layer)

**Elastic Cloud Serverless** is the agent orchestrator and compliance core. It runs a structured multi-agent workflow on the ground, instead of unverified agent-to-agent chatter, and coordinates state across the fleet.

| Component | Role |
| --- | --- |
| Agent 1: Intercept Agent | Captures radio anomaly telemetry streamed from the aircraft |
| Agent 2: Regulatory Compliance Agent | Runs Elastic Hybrid Search (BM25 plus dense vectors) over FAA Order JO 7110.65 (1,000+ pages) to find the exact mandatory safety protocol |
| Human-in-the-Loop Gate | Queues a structured Proposed Safety Directive on the controller dashboard |
| Human Sign-Off | Controller clicks "Approve", which sends the command to Cartesia in the cockpit |
| Fleet Audit | Every anomaly, verification and sign-off is indexed in Elastic and queryable with ES\|QL |

Example directive card:

```
Proposed Action: Hold Short of Runway 33
Confidence:      99%
Verified via:    FAA Rule 4.2
[ Approve ]  [ Reject ]
```

## 6. End-to-End Workflow

| Step | Stage | Component | Target |
| --- | --- | --- | --- |
| 1 | Pre-flight sync | Pi pulls NOTAMs and sector maps from Elastic into Moss | Before pushback |
| 2 | Stepped-on event | ATC says "Hold short of Runway 33" while a helicopter keys its mic | n/a |
| 3 | Hardware detection | Pi audio intercept board sees squelch break and collision signature | Under 10 ms |
| 4 | Local lookup | Moss confirms GPS position and active taxiway node | Under 5 ms |
| 5 | Verification | Regulatory Agent runs hybrid search over the FAA rulebook | See section 8 |
| 6 | Human approval | UI card appears on the controller's screen, one-click approve | Human-paced |
| 7 | Headset delivery | Cartesia speaks: "[URGENT] Transmission blocked. HOLD SHORT of Runway 33. Confirm!" | Under 90 ms to first audio |
| 8 | Audit | Full interaction indexed in Elastic for post-flight analysis | Async |

### Step details

1. **Pre-flight sync.** Before pushback, the Pi pulls active NOTAMs and sector maps from Elastic Cloud and caches them in Moss. The edge device can then work offline for local lookups.
2. **Stepped-on event.** ATC issues a clearance. A second station transmits at the same time and the heterodyne crash erases the instruction in the cockpit.
3. **Hardware detection.** The Pi audio intercept board detects the squelch break and collision signature.
4. **Local lookup.** Moss queries local memory with no network hops and confirms the aircraft's current GPS coordinate and taxiway node.
5. **Verification.** The event goes to Elastic Cloud. The Regulatory Agent checks that the recovery directive matches the mandatory FAA procedure.
6. **Human approval.** A UI card appears on the ground controller's screen. The controller approves with one click.
7. **Headset delivery.** Approval triggers Cartesia on the Pi to stream an urgent whisper into the pilot's headset.
8. **Audit.** The whole interaction is indexed in Elastic for post-flight safety analysis.

## 7. Functional Requirements

| ID | Requirement |
| --- | --- |
| FR-1 | The edge device must detect a collision from the audio panel and PTT/squelch signals. |
| FR-2 | The edge device must cache airport and sector data locally before flight. |
| FR-3 | The edge device must stream anomaly telemetry to the ground when a link is available. |
| FR-4 | The ground system must propose a directive with confidence and rule citation. |
| FR-5 | No directive may reach the cockpit without explicit human approval. |
| FR-6 | Approved directives must be spoken into the pilot headset only, not broadcast on VHF. |
| FR-7 | Every event, agent output and human decision must be stored and queryable. |

## 8. Latency Budget

| Segment | Target | Notes |
| --- | --- | --- |
| Collision detection | Under 10 ms | On device |
| Local lookup (Moss) | Under 5 ms | On device |
| Uplink to ground | TBD | Depends on datalink |
| Agent verification | TBD | Hybrid search plus agent reasoning |
| Human approval | Human-paced | Seconds, not milliseconds |
| Downlink to cockpit | TBD | Depends on datalink |
| TTS first audio (Cartesia) | Under 90 ms | Measured from approval arriving on device |

The 90 ms figure covers speech synthesis only. It is not the end-to-end time from collision to headset. See [Mistakes and Lessons](03-mistakes-and-lessons.md), entry M-001.

## 9. Open Questions

These are tracked in detail in [Mistakes and Lessons](03-mistakes-and-lessons.md).

- How does the system learn the *content* of the blocked instruction? (M-002)
- What datalink connects the aircraft to Elastic in flight and on the ground? (M-003)
- Does Cartesia run on the Pi, or is it a cloud call? (M-004)
- What is the source for the February 2026 NTSB finding? (M-005)
- What certification path applies to tapping a certified aircraft's audio panel? (M-006)
- How is "immutable" audit storage actually guaranteed? (M-007)
- How is the directive confidence score calculated? (M-008)

## 10. Research Plan

The pitch needs real numbers. Every claim must be backed by a source or by our own measurement. Full details and the evidence table are in [Research and Evidence](06-research.md).

| Area | What we need to show | Owner |
| --- | --- | --- |
| Problem size | How often transmissions are blocked (NASA ASRS, FAA runway incursion data) | Dev B |
| Safety impact | NTSB investigations naming blocked transmissions, plus the source for the February 2026 finding | Dev B |
| Existing options | Why anti-blocking radios and CPDLC don't solve it | Dev B |
| Feasibility | Published latency for Cartesia and Moss (Pi 5 audio latency on hold) | Dev A |
| Detection | Evidence that collisions can be detected from audio | Dev A |
| Our prototype | Measured latency for each segment in section 8 | Both |

**Deliverable by end of day 1:** each owner has filled their rows in the evidence table, and the three headline numbers in [Research section 5](06-research.md#5-headline-numbers-for-the-pitch) are written using High confidence sources only.

Architecture and data flow are covered in [Architecture](05-architecture.md).
