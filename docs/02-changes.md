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
