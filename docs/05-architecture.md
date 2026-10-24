# Architecture

How data flows through Unstep, from the moment a transmission is stepped on to the final audit record.

| Field | Value |
| --- | --- |
| Status | Draft v0.1 |
| Last updated | 2026-10-23 |
| Related | [PRD](01-prd.md), [Work Split](04-work-split.md), [Research](06-research.md) |

## 1. System Overview

```mermaid
flowchart LR
    subgraph Air["Cockpit (Dev A)"]
        RADIO[VHF audio panel<br/>and PTT/squelch]
        DET[Collision detector]
        MOSS[(Moss<br/>local cache)]
        EDGE[Edge agent]
        TTS[Cartesia TTS]
        EAR[Pilot headset<br/>left ear]
    end

    subgraph Ground["Ground (Dev B)"]
        TOWER[Tower audio capture<br/>and speech-to-text]
        INT[Intercept Agent]
        REG[Regulatory Compliance Agent]
        FAA[(Elastic index<br/>FAA JO 7110.65)]
        UI[Controller dashboard]
        AUD[(Elastic audit indices)]
    end

    RADIO --> DET --> EDGE
    MOSS --> EDGE
    EDGE -- AnomalyEvent --> INT
    TOWER -- transcript --> INT
    INT --> REG
    FAA --> REG
    REG -- ProposedDirective --> UI
    UI -- ApprovedDirective --> EDGE
    EDGE --> TTS --> EAR

    EDGE -. AuditRecord .-> AUD
    INT -. AuditRecord .-> AUD
    REG -. AuditRecord .-> AUD
    UI -. AuditRecord .-> AUD
```

Solid lines are the live path. Dotted lines are audit writes, which never block the live path.

## 2. Data Flow, Start to Finish

```mermaid
sequenceDiagram
    autonumber
    participant ATC as Controller (voice)
    participant TWR as Tower capture + STT
    participant PI as Cockpit edge (Pi 5)
    participant M as Moss
    participant INT as Intercept Agent
    participant REG as Compliance Agent
    participant ES as Elastic
    participant UI as Controller dashboard
    participant C as Cartesia
    participant P as Pilot headset

    Note over PI,M: Pre-flight: Pi pulls NOTAMs and taxiway graph from Elastic into Moss

    ATC->>TWR: "Hold short of Runway 33"
    ATC--xPI: Transmission blocked by overlap
    PI->>PI: Detect squelch break and collision signature (under 10 ms)
    PI->>M: Look up position and taxiway node (under 5 ms)
    M-->>PI: Node, active runway, NOTAMs
    PI->>INT: AnomalyEvent
    TWR->>INT: Transcript of the controller's transmission
    INT->>REG: Matched event and transcript
    REG->>ES: Hybrid search (BM25 plus vectors)
    ES-->>REG: Matching FAA paragraph
    REG->>UI: ProposedDirective (text, confidence, citation)
    UI->>UI: Controller reviews
    UI->>PI: ApprovedDirective
    PI->>C: Directive text
    C-->>P: Spoken whisper (first audio under 90 ms)
    PI-)ES: AuditRecord (each stage also writes one)
```

## 3. Stage by Stage

| # | Stage | Where | Input | Output | Owner | Target |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | Pre-flight sync | Pi | Elastic: NOTAMs, taxiway graph | Moss cache | A | Before pushback |
| 1 | Audio capture | Pi | Audio panel, PTT/squelch line | Audio frames | A | Continuous |
| 2 | Collision detection | Pi | Audio frames | Collision flag, duration | A | Under 10 ms |
| 3 | Local lookup | Pi (Moss) | Aircraft ID, GPS | Taxiway node, active runway | A | Under 5 ms |
| 4 | Event uplink | Pi to ground | Collision plus local state | `AnomalyEvent` | A | TBD (datalink) |
| 5 | Tower transcript | Ground | Controller audio | Instruction text | B | TBD |
| 6 | Intercept | Ground | `AnomalyEvent`, transcript | Matched event | B | TBD |
| 7 | Compliance check | Ground (Elastic) | Matched event | `ProposedDirective` | B | TBD |
| 8 | Human approval | Dashboard | `ProposedDirective` | `ApprovedDirective` | B | Human-paced |
| 9 | Directive downlink | Ground to Pi | `ApprovedDirective` | Directive on device | B | TBD (datalink) |
| 10 | Speech | Pi (Cartesia) | Directive text | Audio in left ear | A | Under 90 ms to first audio |
| 11 | Audit | Elastic | Every stage | `AuditRecord` | Both | Async |

## 4. Message Contracts

See [Work Split, section 3](04-work-split.md#3-shared-contracts-both-do-first) for the fields.

| Message | From | To |
| --- | --- | --- |
| `AnomalyEvent` | Edge agent | Intercept Agent |
| `ProposedDirective` | Compliance Agent | Controller dashboard |
| `ApprovedDirective` | Controller dashboard | Edge agent |
| `AuditRecord` | Every component | Elastic audit indices |

## 5. Failure Paths

| Failure | Behavior |
| --- | --- |
| No datalink to ground | Pi plays a local alert: "Transmission blocked, request say again" (M-003) |
| No tower transcript | Directive is not proposed. Dashboard shows "blocked transmission, content unknown" (M-002) |
| Low confidence or no rule match | Card is marked low confidence. The controller must reissue by voice |
| Controller rejects | Nothing is sent to the cockpit. The rejection is audited |
| Cartesia unavailable | Fall back to local TTS or pre-recorded phrases (M-004) |
