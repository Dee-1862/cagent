# Research and Evidence

The numbers that justify Unstep, and where each one comes from. A number only counts once it has a source link.

| Field | Value |
| --- | --- |
| Status | In progress |
| Last updated | 2026-10-23 |
| Related | [PRD section 10](01-prd.md#10-research-plan), [Work Split](04-work-split.md) |

## 1. Rules

- **Primary sources first:** NTSB, FAA, NASA ASRS, EUROCONTROL, ICAO, and official vendor docs or benchmarks.
- **Two sources** for any headline number used in the pitch.
- **Record the date** of the source and the date we checked it.
- **Confidence:** High (primary source, exact figure), Medium (secondary or derived), Low (estimate, needs work).
- **If we can't source a claim,** reword it or drop it. Never round up.

## 2. Research Questions

### Dev A: technical feasibility

| ID | Question | Why it matters |
| --- | --- | --- |
| RA-1 | What is Cartesia Sonic's published time to first audio? Is there an on-device option? | Backs up the 90 ms claim (M-001, M-004) |
| RA-2 | What lookup latency does Moss publish, and what do we measure on our laptop? | Backs up the 5 ms claim |
| RA-3 | **On hold.** What audio latency does a Pi 5 with a USB or HAT audio interface add? | Only needed once Pi integration resumes |
| RA-4 | Can simultaneous VHF transmissions be detected from audio (heterodyne tone, squelch)? Any papers or existing products? | Shows detection is feasible |
| RA-5 | What datalinks could carry events (CPDLC, ACARS, cellular on the ground)? What latency does each have? | Fills the TBD uplink and downlink rows |

### Dev B: problem size and impact

| ID | Question | Why it matters |
| --- | --- | --- |
| RB-1 | How many NASA ASRS reports mention blocked or stepped-on transmissions per year? | Shows how often it happens |
| RB-2 | Which NTSB investigations name blocked transmissions as a factor? | Shows the safety impact |
| RB-3 | What is the exact source of the February 2026 NTSB finding? | Fixes M-005 |
| RB-4 | How many runway incursions does the FAA record per year, and how many involve communication errors? | Sizes the problem |
| RB-5 | Has EUROCONTROL or the FAA studied simultaneous transmissions, and what did they find? | Independent evidence |
| RB-6 | What exists today (anti-blocking radios, CPDLC, stuck-mic detection) and why isn't it enough? | Competitor comparison |
| RB-7 | How many towers, frequencies and daily operations are in the US? | Market size and scale |

## 3. Evidence Table

| ID | Claim | Value | Source (link) | Source date | Checked | Confidence | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RA-1 | | | | | | | A |
| RA-2 | | | | | | | A |
| RA-3 | On hold | | | | | | n/a |
| RA-4 | | | | | | | A |
| RA-5 | | | | | | | A |
| RB-1 | | | | | | | B |
| RB-2 | | | | | | | B |
| RB-3 | | | | | | | B |
| RB-4 | | | | | | | B |
| RB-5 | | | | | | | B |
| RB-6 | | | | | | | B |
| RB-7 | | | | | | | B |

## 4. Our Own Measurements

Numbers we measure on our prototype. These go into [PRD section 8](01-prd.md#8-latency-budget).

| Segment | Target | Measured | Runs | Hardware | Date |
| --- | --- | --- | --- | --- | --- |
| Collision detection | Under 10 ms | | | | |
| Moss lookup | Under 5 ms | | | | |
| Uplink | TBD | | | | |
| Agent verification | TBD | | | | |
| Downlink | TBD | | | | |
| Cartesia first audio | Under 90 ms | | | | |
| End to end, without the human | TBD | | | | |

## 5. Headline Numbers for the Pitch

Fill these in at the end of the day, from High confidence rows only.

1. _How often transmissions are blocked:_
2. _Safety impact:_
3. _How fast Unstep responds:_
