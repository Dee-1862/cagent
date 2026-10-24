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
