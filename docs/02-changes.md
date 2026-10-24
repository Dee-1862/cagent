# Changes

A running log of changes to the Unstep project. Newest entries go at the top.

## Format

Each entry uses this template:

```
## YYYY-MM-DD: Short title

**Type:** Added | Changed | Fixed | Removed | Docs
**Area:** Edge device | Ground agents | Audio | Audit | Docs | Other

What changed and why, in a few lines.

**Related:** links to PRD sections or mistake entries
```

---

## 2026-10-23: Dev A status on branch `rishit`

**Type:** Added
**Area:** Edge device

| Task | Status |
| --- | --- |
| A1 audio input, clips | Done: synthetic clips plus real Cartesia-voiced clips in `assets/clips/real/` |
| A2 overlap detector | Done, tuned on real speech. Only proven on clips we mixed (RA-4) |
| A3 cockpit STT | Done: Cartesia `ink-2` manual mode, finalize on squelch close, live tested |
| A4 Moss hint | Done and verified on real Moss: hint search 0.6 ms, pilot query 1.0 ms, numeric ts filters correct |
| A5 Frequency Monitor | Done |
| A6 advisory TTS | Done: `sonic-3.6`, pronunciation dictionary uploaded, chime, left ear, live tested |
| A7 readback check | Done: live tested on real readback clips |
| A8 offline | Done: pre-generated alert, outbox, memory fails safe |
| A9 latency | Measured live: TTS first audio about 100 ms, manual STT 143 ms, turn end about 650 ms |
| A10 pilot queries | Done: live tested on a real question clip |

- Red team found 18 issues across the gateway and cockpit. All fixed with regression tests (130 tests pass).
- `python scripts/run_demo.py` runs offline. `--live` runs on the real Cartesia API.
- Cartesia feedback logged in [09-cartesia-feedback.md](09-cartesia-feedback.md).
- **For Dev B:** tower STT must choose between `ink-2` (key terms) and `ink-whisper` (word timestamps), see CF-9. The gateway now enforces per-role senders and rebuilds directives from the stored proposal.

**Related:** [README](../README.md), [Work Split](04-work-split.md)

## 2026-10-23: Blue-team fixes to the Moss layer, local hint and pilot queries

**Type:** Fixed
**Area:** Edge device

- `MossMemory` translates our filters into the Moss SDK form (`{"field", "condition"}`, string values, `$and`/`$or` lists) via `to_moss_filter`. Local filter semantics unchanged.
- New `fetch()` (filter-only, unranked) on both backends. The local hint and "last clearance" now use the newest record by `ts`, so a superseded clearance can't win on score. Hints need a clearance from the last 15 minutes.
- `likely_instruction` picks the runway the hold short applies to. A "go around" or "stop" fragment gets no hold short hint. Permissive fragment check normalizes case, hyphens and spacing and covers take off, cleared, clear, depart, cross, line up.
- "Say again" never reads back a "Likely" hint, and repeats the newer approved clearance once one exists. "Repeat the last clearance" is a last-clearance question.
- `record()` never overwrites an existing id (writes `<id>-v2`). Records naming another aircraft are ignored for this aircraft.
- Memory errors give no hint or "No record found" instead of crashing. The edge opens Moss sessions at startup.
- Regression tests in `tests/test_blue_team.py`.

**Related:** [PRD section 7, local hint rules](01-prd.md)

---

## 2026-10-23: Overlap detector retuned for real speech

**Type:** Fixed
**Area:** Audio

The old detector (peak share of in-band power over 3 frames) false-fired on Cartesia TTS speech. It now scores each bin's prominence over a local spectral median (500 to 3400 Hz), takes the minimum over the last 300 ms, and opens when a line stays 12 dB above its neighbours for 5 more frames; start is backdated 280 ms, windows under 300 ms are dropped. Real and synthetic clean clips give no window; both stepped-on clips give one window from 1.3 s to the end. About 0.07 ms per frame. Added real-clip tests (skipped when the files are missing). Limits: tones below 500 Hz are ignored, a second voice without a beat tone is not flagged, and a beat tone at level 0.07 or lower against this speech gives broken or late windows.

**Related:** tests/test_overlap.py, scripts/make_real_clips.py


## 2026-10-23: M0 contracts and M2 first wire

**Type:** Added
**Area:** Other

- Python stack: FastAPI WebSocket gateway, Pydantic contracts, plain HTML dashboard.
- `unstep/contracts.py` implements every contract from Work Split section 3, plus `RejectedDirective` (the cockpit needs it to say "request say again"). Please confirm this addition.
- `contracts/examples/` has one JSON example per contract, generated from `unstep/scenario.py`.
- Gateway routes messages by role, stores every message (JSON lines for now, Elastic in B1), and turns voice or click decisions into one `ApprovedDirective` or `RejectedDirective`. A second decision on the same event is refused.
- Mock cockpit, mock agents, auto approver and mock dashboard. M2 passes 10 runs in a row live and in tests.

**Related:** [Work Split, milestones](04-work-split.md#6-milestones), [README](../README.md)

## 2026-10-23: Voice first in PRD v0.4

**Type:** Changed
**Area:** Audio

- PRD v0.4: voice first. The pilot asks Unstep questions on a separate Unstep key, answered from Moss. The controller hears each proposed correction and approves by voice, with the click as a fallback. A chime starts every Unstep message.
- Added voice approval rules: only the Unstep key counts, repeat back before sending, one retry, 10 second timeout to "nothing sent."
- Local hint is now restrictive instructions only, and always shows its source Moss record.
- Cockpit transcript finalizes on squelch close. One clock for all timestamps, tower word times as offsets from `ptt_start`.
- Architecture v0.4: controller voice loop, pilot query path, Frequency Monitor as the only writer to the frequency session. New contracts `VoiceApproval` and `PilotQuery`.
- Work split v0.4: new tasks A10 (pilot voice queries) and B10 (controller voice approval). Both developers now at 10 tasks and 20 points.
- Demo flow: nobody touches a screen until step 7.
- Mistakes: added M-013 and M-014. Advice: added section 10 with the reasoning.

**Related:** [PRD](01-prd.md), [Advice, section 10](08-advice.md#10-voice-first-added-after-v03-folded-into-v04)

## 2026-10-23: Folded Rishit's advice into PRD v0.3

**Type:** Changed
**Area:** Docs

- Accepted all of [08-advice.md](08-advice.md) and folded it into the PRD, architecture, work split and research.
- PRD v0.3: the product is now "no ATC instruction lost or misheard" (blocked transmission recovery plus readback checking, plus a thin monitoring agent). Added Terms, Scope, Responsibility, Cut List and a new 2-minute demo flow.
- PRD v0.3: added local hint rules so the spoken "Likely" hint never acts as a clearance.
- Architecture v0.3: live messages over a WebSocket gateway, Moss as local memory with three indexes and one writer each, and events also written to Elastic so Agent Builder agents can read them.
- Work split v0.3: Dev A owns the cockpit, cockpit voice and all Moss work including the Frequency Monitor. Dev B owns the gateway, tower STT and all Elastic work including the Readback Auditor. Both have 9 tasks with equal effort.
- Research: filled in vendor figures for Cartesia and Moss with sources, added RA-8 and RB-9.
- Mistakes: added M-011 and M-012, resolved M-004 and M-010, updated M-001, M-002, M-003 and M-009.

**Related:** [PRD](01-prd.md), [Advice, section 9](08-advice.md#9-how-this-was-folded-in)

## 2026-10-23: Added advice on scope, tracks, Moss and Cartesia

**Type:** Docs
**Area:** Docs

- Added [08-advice.md](08-advice.md), a proposal to agree on before changing the PRD.
- Defines the product as "no ATC instruction lost or misheard": blocked transmission recovery plus readback checking, plus a thin monitoring agent for the Moss and Elastic tracks. Rules out collision avoidance and a full agentic ATC.
- Benchmarks each version of the idea against the Cartesia, Moss and Elastic track criteria and past track winners.
- Moss: based on its docs, use it as local memory with handoff, one writer per index, and send live messages over WebSocket.
- Cartesia: manual STT with finalize on PTT release for the tower, turn STT for readbacks, word timestamps to highlight blocked words, key terms, pronunciation dictionary, interruption.
- Lists eight concerns with PRD v0.2, a cut list and a demo flow.

**Related:** [Advice](08-advice.md), [Sponsor Review](07-sponsor-review.md)

## 2026-10-23: Folded sponsor review into the plan

**Type:** Changed
**Area:** Docs

- Merged Rishit's sponsor review and applied the accepted concerns S-1 to S-10.
- PRD v0.2: Cartesia is now the whole voice loop (tower STT with key terms, cut-off detection, advisory voice with ATC numbers, readback check).
- PRD v0.2: Moss is now the shared agent memory and local search layer, with offline indexing. Agents share context and don't chat.
- PRD v0.2: ground agents run in Elastic Agent Builder as an Elastic Workflow. Added a demo flow, responsibility section and sponsor fit table.
- Architecture v0.2: new diagrams with the Moss shared space, the readback loop and a WebSocket fallback.
- Work split v0.2: one owner per sponsor (Dev A: Moss and cockpit voice, Dev B: Elastic and tower STT), new contracts, shared tasks for README and demo.
- Research: added RA-6, RA-7 and RB-8, plus new measurement rows.
- Mistakes: added M-009 and M-010, updated M-002 and M-003.
- `.gitignore`: added `.env` and key files.

**Related:** [Sponsor Review, section 8](07-sponsor-review.md#8-where-each-concern-was-addressed)

## 2026-10-23: Added sponsor review and benchmark

**Type:** Docs
**Area:** Docs

- Added [07-sponsor-review.md](07-sponsor-review.md) with the Cartesia and Moss prize criteria, concerns S-1 to S-10, notes from sponsor conversations and a benchmark against past winning projects.
- Main findings: Cartesia is only used for final TTS, and the Moss use case is a lookup rather than search. Both need to change before the demo.
- No changes to the PRD yet. Accepted items will be folded in separately.

**Related:** [Sponsor Review](07-sponsor-review.md)

## 2026-10-23: Put Raspberry Pi integration on hold

**Type:** Changed
**Area:** Edge device

- Raspberry Pi integration is on hold and not assigned to anyone.
- The cockpit edge now runs as a laptop simulator with recorded audio and a simulated PTT/squelch signal.
- Added an "On hold" section to the work split and a current scope note to the PRD and architecture.
- Marked research question RA-3 (Pi 5 audio latency) as on hold.

**Related:** [Work Split, section 3a](04-work-split.md#3a-on-hold-raspberry-pi-integration)

## 2026-10-23: Added architecture and research plan

**Type:** Docs
**Area:** Docs

- Added [05-architecture.md](05-architecture.md) with a system diagram, a start-to-finish sequence diagram, a stage table and failure paths.
- Added [06-research.md](06-research.md) with research questions, an evidence table and a measurements table.
- Added a research plan to the PRD (section 10).
- Added research tasks AR and BR and a day 1 plan to the work split.

**Related:** [Architecture](05-architecture.md), [Research](06-research.md)

## 2026-10-23: Added work split plan

**Type:** Docs
**Area:** Docs

- Added [04-work-split.md](04-work-split.md), which divides the build between two developers.
- Dev A owns the cockpit edge device. Dev B owns the ground side.
- Shared contracts come first so both halves can be built in parallel against mocks.
- Milestone M2 (first end-to-end wire with fake data) is the main early target.

**Related:** [Work Split](04-work-split.md)

## 2026-10-23: Created documentation folder

**Type:** Docs
**Area:** Docs

- Created the `docs/` folder. All Markdown files except the README live here.
- Added [01-prd.md](01-prd.md), restructured from the original concept write-up into sections: summary, problem, goals, users, architecture, workflow, requirements, latency budget and open questions.
- Added this changes log.
- Added [03-mistakes-and-lessons.md](03-mistakes-and-lessons.md) with the first review of the concept.
- Removed all em dashes from the source text and replaced them with colons, commas or table columns.
- Split the latency claims into a per-segment budget so the 90 ms speech target is not read as an end-to-end figure.
- Added open questions to the PRD for issues found during review (see M-001 to M-008).

**Related:** [PRD](01-prd.md), [Mistakes and Lessons](03-mistakes-and-lessons.md)
