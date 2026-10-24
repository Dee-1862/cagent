# Research and Evidence

The numbers that justify Unstep, and where each one comes from. A number only counts once it has a source link.

| Field | Value |
| --- | --- |
| Status | In progress |
| Last updated | 2026-10-23 |
| Related | [PRD section 15](01-prd.md#15-research-plan), [Work Split](04-work-split.md), [Sponsor Review](07-sponsor-review.md), [Advice](08-advice.md) |

## 1. Rules

- **Primary sources first:** NTSB, FAA, NASA ASRS, EUROCONTROL, ICAO, and official vendor docs or benchmarks.
- **Two sources** for any headline number used in the pitch.
- **Record the date** of the source and the date we checked it.
- **Confidence:** High (independent primary source, exact figure), Medium (vendor's own benchmark, or secondary source), Low (estimate, needs work).
- **Vendor numbers are background, not our numbers.** On screen we show what we measured (M-001).
- **If we can't source a claim,** reword it or drop it. Never round up.

## 2. Research Questions

### Dev A: technical feasibility

| ID | Question | Why it matters |
| --- | --- | --- |
| RA-1 | What is Cartesia Sonic's time to first audio, from the vendor and from independent tests? | Sets expectations for our measured number (M-001) |
| RA-2 | What search latency does Moss publish, and what do we measure on our laptop? | Backs up the local hint speed |
| RA-3 | **On hold.** What audio latency does a Pi 5 with a USB or HAT audio interface add? | Only needed once Pi integration resumes |
| RA-4 | Can overlapping VHF transmissions be detected from audio (heterodyne tone, squelch)? Any papers or products? | Shows detection is feasible |
| RA-5 | What datalinks could carry events in a real aircraft (CPDLC, ACARS, cellular on the ground)? | Answers M-003 for the real product |
| RA-6 | How accurate is Cartesia STT with key terms on ATC phrases? | Backs up readback checking and tower transcripts |
| RA-7 | How does Moss run and hand off between machines? | Decided the transport (M-011) |
| RA-8 | What is the exact syntax of the Moss `$near` filter? | Needed for position-based search |

### Dev B: problem size and impact

| ID | Question | Why it matters |
| --- | --- | --- |
| RB-1 | How many NASA ASRS reports mention blocked or stepped-on transmissions per year? | Shows how often it happens |
| RB-2 | Which NTSB investigations name blocked transmissions or readback errors as a factor? | Shows the safety impact |
| RB-3 | What is the exact source of the February 2026 NTSB finding? | Fixes M-005 |
| RB-4 | How many runway incursions does the FAA record per year, and how many involve communication or readback errors? | Sizes the problem |
| RB-5 | Has EUROCONTROL or the FAA studied simultaneous transmissions or readback errors? | Independent evidence |
| RB-6 | What exists today (anti-blocking radios, CPDLC, stuck-mic detection) and why isn't it enough? | Competitor comparison |
| RB-7 | How many towers, frequencies and daily operations are in the US? | Market size and scale |
| RB-8 | What rules apply to recording and transcribing ATC audio? | Backs up the privacy notes |
| RB-9 | Can Elastic Agent Builder call an external tool such as Moss's MCP server? | Decides whether agents read Moss or only Elastic |

## 3. Evidence Table

| ID | Claim | Value | Source (link) | Checked | Confidence | Owner |
| --- | --- | --- | --- | --- | --- | --- |
| RA-1 | Cartesia Sonic time to first audio, model only | Under 90 ms | Cartesia's own claim, exact page link still needed | 2026-10-23 | Low until linked | A |
| RA-1 | Sonic 3 time to first audio including network | About 166 to 190 ms | [invideo measurement](https://invideo.io/blog/cartesia-sonic-ai-voice/) | 2026-10-23 | Medium (secondary) | A |
| RA-2 | Moss search latency, 100k docs, M4 MacBook, embedding included | About 3 ms median, 5 ms p99 | [Moss README](https://github.com/usemoss/moss) | 2026-10-23 | Medium (vendor) | A |
| RA-2 | Moss session operations on device | About 1 to 10 ms | [Moss sessions docs](https://docs.moss.dev/docs/integrate/sessions.md) | 2026-10-23 | Medium (vendor) | A |
| RA-3 | On hold | | | | | n/a |
| RA-4 | | | | | | A |
| RA-5 | | | | | | A |
| RA-6 | Cartesia STT keyword recall with key terms | 93.8% on Cartesia's benchmark | [Cartesia keyterm blog](https://www.cartesia.ai/blog/keyterm-prompting) | 2026-10-23 | Medium (vendor) | A |
| RA-7 | Moss handoff goes through Moss Cloud, `push_index()` replaces the index, auto-refresh polls every 300 s | Answered: use WebSocket for live messages | [Cross-agent handoff](https://docs.moss.dev/docs/build/cross-agent-handoff.md), [Python API](https://docs.moss.dev/docs/reference/python/api.md) | 2026-10-23 | High for design | A |
| RA-8 | | | | | | A |
| RB-1 | | | | | | B |
| RB-2 | | | | | | B |
| RB-3 | | | | | | B |
| RB-4 | | | | | | B |
| RB-5 | | | | | | B |
| RB-6 | | | | | | B |
| RB-7 | | | | | | B |
| RB-8 | | | | | | B |
| RB-9 | | | | | | B |

Vendor figures above were collected by Rishit in [Advice](08-advice.md#sources).

## 4. Our Own Measurements

Numbers we measure on our prototype. These go into [PRD section 9](01-prd.md#9-latency) and on screen in the demo.

| Segment | Target | Measured | Runs | Hardware | Date |
| --- | --- | --- | --- | --- | --- |
| Overlap detection | Under 10 ms | | | | |
| Moss local hint search | Under 10 ms | | | | |
| Tower transcript final after PTT release | TBD | | | | |
| Gateway and Workflow trigger | TBD | | | | |
| Agent verification | TBD | | | | |
| TTS first audio | Measure | | | | |
| Readback verdict after pilot stops | TBD | | | | |
| Readback slot accuracy on test phrases | TBD | | | | |
| Key term accuracy on tower test phrases | TBD | | | | |
| End to end, without the human | TBD | | | | |

## 5. Headline Numbers for the Pitch

Fill these in at the end of the day, from High confidence rows and our own measurements only. Past winning sponsor projects are benchmarked in [Sponsor Review, section 4](07-sponsor-review.md#4-past-winners) and [Advice, section 2](08-advice.md#2-benchmark-against-the-tracks).

1. _How often instructions are blocked or misheard:_
2. _Safety impact:_
3. _How fast Unstep responds (measured):_
