# Architecture

How data flows through Unstep, from the moment a transmission is stepped on to the final audit record.

| Field | Value |
| --- | --- |
| Status | Draft v0.2 |
| Last updated | 2026-10-23 |
| Related | [PRD](01-prd.md), [Work Split](04-work-split.md), [Research](06-research.md), [Sponsor Review](07-sponsor-review.md) |

> **Current scope:** Raspberry Pi integration is on hold. The cockpit edge runs as a software simulator on a laptop, using recorded radio audio and a simulated PTT/squelch signal. The data flow below stays the same when we move to the Pi later.

## 1. Design Principles

- **Agents share context, they don't chat.** Every agent reads and writes a shared Moss space. No agent sends conversational messages to another.
- **Voice runs the whole loop.** Cartesia transcribes the tower, detects cut-offs, speaks the directive and checks the readback.
- **Elastic orchestrates and remembers.** An Elastic Workflow runs the ground agents. Elastic holds the FAA rulebook and the audit trail.
- **A human approves every directive.**
- **Audit never blocks the live path.**

## 2. System Overview

```mermaid
flowchart LR
    subgraph Air["Cockpit edge simulator (Dev A)"]
        RADIO[Recorded radio audio<br/>and simulated PTT/squelch]
        DET[Collision detector]
        CUT[Cartesia<br/>cut-off detection]
        EDGE[Edge agent]
        LOCAL[(Moss local index<br/>NOTAMs, taxiways,<br/>recent clearances)]
        TTS[Cartesia TTS<br/>advisory voice]
        EAR[Pilot headset<br/>left ear]
        MIC[Pilot mic]
        RB[Cartesia STT<br/>readback check]
    end

    SHARED[(Moss shared<br/>context space)]

    subgraph Ground["Ground (Dev B)"]
        TOWER[Tower audio]
        TSTT[Cartesia STT<br/>with key terms]
        WF[Elastic Workflow<br/>trigger]
        INT[Intercept Agent]
        REG[Compliance Agent]
        FAA[(Elastic index<br/>FAA JO 7110.65)]
        UI[Controller dashboard]
        AUD[(Elastic audit indices)]
    end

    RADIO --> DET --> EDGE
    RADIO --> CUT --> EDGE
    LOCAL <--> EDGE
    EDGE -- AnomalyContext --> SHARED
    EDGE -- trigger --> WF
    TOWER --> TSTT -- TowerTranscript --> SHARED
    WF --> INT
    SHARED <--> INT
    INT --> REG
    FAA --> REG
    REG -- ProposedDirective --> UI
    UI -- ApprovedDirective --> SHARED
    SHARED --> EDGE
    EDGE --> TTS --> EAR
    MIC --> RB --> EDGE
    EDGE -- ReadbackResult --> SHARED

    EDGE -. AuditRecord .-> AUD
    INT -. AuditRecord .-> AUD
    REG -. AuditRecord .-> AUD
    UI -. AuditRecord .-> AUD
```

Solid lines are the live path. Dotted lines are audit writes, which never block the live path.

**Fallback transport:** if Moss can't share one space between the edge and the ground machine (M-010), the same messages go over a WebSocket. The message formats don't change, only the transport.

## 3. Data Flow, Start to Finish

```mermaid
sequenceDiagram
    autonumber
    participant ATC as Controller (voice)
    participant TS as Tower STT (Cartesia)
    participant E as Cockpit edge (laptop sim)
    participant ML as Moss local index
    participant MS as Moss shared space
    participant WF as Elastic Workflow
    participant AG as Intercept + Compliance agents
    participant UI as Controller dashboard
    participant C as Cartesia TTS/STT
    participant P as Pilot

    Note over E,ML: Pre-flight: edge pulls NOTAMs and taxiway data from Elastic and indexes them in Moss

    ATC->>TS: "Hold short of Runway 33"
    TS->>MS: TowerTranscript (key terms applied)
    ATC--xE: Transmission blocked by overlap
    E->>E: Collision signature plus cut-off detected (under 10 ms)
    E->>ML: Search position, runway, NOTAMs, recent clearances (under 5 ms)
    ML-->>E: Local context
    E->>MS: AnomalyContext
    E->>WF: Trigger with event_id
    WF->>AG: Run agents
    AG->>MS: Read AnomalyContext and TowerTranscript
    AG->>AG: Hybrid search FAA JO 7110.65 and cite paragraph
    AG->>UI: ProposedDirective (text, confidence, citation)
    UI->>UI: Controller reviews and approves
    UI->>MS: ApprovedDirective
    MS-->>E: ApprovedDirective
    E->>C: Directive text, advisory voice, ATC numbers
    C-->>P: "Advisory. Hold short Runway tree tree. Read back." (under 90 ms)
    P->>C: Readback
    C-->>E: Readback transcript
    E->>E: Compare with directive
    alt Readback matches
        E->>MS: ReadbackResult (correct)
    else Mismatch
        E->>C: "Readback incorrect" and repeat (max 2, then flag controller)
    end
    Note over E,UI: Every stage also writes an AuditRecord to Elastic
```

## 4. Stage by Stage

| # | Stage | Where | Input | Output | Owner | Target |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | Pre-flight index | Edge sim (Moss) | Elastic: NOTAMs, taxiway graph | Moss local index | A | Before pushback |
| 1 | Audio capture | Edge sim | Recorded radio audio, simulated PTT/squelch | Audio frames | A | Continuous |
| 2 | Collision detection | Edge sim | Audio frames | Collision flag, duration | A | Under 10 ms |
| 3 | Cut-off detection | Edge sim (Cartesia) | Audio frames | Cut-off flag | A | TBD |
| 4 | Local search | Edge sim (Moss) | Aircraft ID, GPS | Runway, taxiway node, NOTAMs, recent clearances | A | Under 5 ms |
| 5 | Context handoff | Moss shared space | Collision plus local context | `AnomalyContext` | A | TBD |
| 6 | Tower transcript | Ground (Cartesia STT) | Controller audio | `TowerTranscript` | B | TBD |
| 7 | Workflow trigger | Elastic Workflow | `event_id` | Agents start | B | TBD |
| 8 | Intercept | Elastic agent | `AnomalyContext`, `TowerTranscript` | Matched event | B | TBD |
| 9 | Compliance check | Elastic agent | Matched event | `ProposedDirective` | B | TBD |
| 10 | Human approval | Dashboard | `ProposedDirective` | `ApprovedDirective` | B | Human-paced |
| 11 | Directive delivery | Moss shared space | `ApprovedDirective` | Directive on edge | Both | TBD |
| 12 | Speech | Edge sim (Cartesia TTS) | Directive text | Advisory audio in left ear | A | Under 90 ms to first audio |
| 13 | Readback check | Edge sim (Cartesia STT) | Pilot speech | `ReadbackResult` | A | TBD |
| 14 | Audit | Elastic | Every stage | `AuditRecord` | Both | Async |

## 5. Message Contracts

See [Work Split, section 3](04-work-split.md#3-shared-contracts-both-do-first) for the fields.

| Message | Written by | Read by |
| --- | --- | --- |
| `AnomalyContext` | Edge agent | Intercept Agent |
| `TowerTranscript` | Tower STT | Intercept Agent |
| `ProposedDirective` | Compliance Agent | Controller dashboard |
| `ApprovedDirective` | Controller dashboard | Edge agent |
| `ReadbackResult` | Edge agent | Dashboard, audit |
| `AuditRecord` | Every component | Elastic audit indices |

## 6. Failure Paths

| Failure | Behavior |
| --- | --- |
| No link to ground | Edge keeps indexing in Moss and plays a local alert: "Advisory. Transmission blocked, request say again" (M-003) |
| No tower transcript | No directive is proposed. Dashboard shows "blocked transmission, content unknown" (M-002) |
| Low confidence or no rule match | Card is marked low confidence. The controller must reissue by voice |
| Controller rejects | Nothing is sent to the cockpit. The rejection is audited |
| Readback wrong twice | Edge stops repeating and the dashboard flags the controller to reissue by voice |
| Cartesia unavailable | Fall back to local TTS or pre-recorded phrases (M-004) |
| Moss can't share across machines | Same messages over WebSocket (M-010) |
