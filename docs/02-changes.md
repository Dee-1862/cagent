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
