# Mistakes and Lessons

A log of mistakes made on Unstep and what we learned from each one. The goal is to stop repeating them, not to assign blame.

## Format

Each entry uses this template:

```
## M-XXX: Short title

**Date found:** YYYY-MM-DD
**Status:** Open | Resolved
**Area:** Edge device | Ground agents | Audio | Audit | Docs | Other

**What happened:** the mistake.
**Why it matters:** the impact if left alone.
**What we learned:** the lesson to carry forward.
**Action:** what we did or will do about it.
```

## Index

| ID | Title | Area | Status |
| --- | --- | --- | --- |
| M-001 | 90 ms read as end-to-end latency | Audio | Open |
| M-002 | No source for the blocked instruction's content | Ground agents | Open |
| M-003 | Offline mode conflicts with ground approval | Edge device | Open |
| M-004 | Cartesia placement unclear | Audio | Open |
| M-005 | Key safety claim has no citation | Docs | Open |
| M-006 | Certification not considered | Edge device | Open |
| M-007 | ES\|QL described as the audit store | Audit | Open |
| M-008 | "99% confidence" shown without a basis | Ground agents | Open |
| M-009 | Sponsor tools used as add-ons, not as the core | Other | Open |
| M-010 | Vendor claims written before checking the docs | Docs | Open |

---

## M-001: 90 ms read as end-to-end latency

**Date found:** 2026-10-23
**Status:** Open
**Area:** Audio

**What happened:** The concept said the system whispers the command "in under 90 milliseconds." That figure is Cartesia's time to first audio byte. The real path also includes an uplink, agent verification, a human click and a downlink.
**Why it matters:** Judges, reviewers or regulators will spot that a human approval cannot happen in milliseconds, which undermines every other number.
**What we learned:** State every latency figure with its start and end point. Never let a component benchmark stand in for system latency.
**Action:** PRD section 8 now has a per-segment latency budget. Measure and fill in the TBD rows.

## M-002: No source for the blocked instruction's content

**Date found:** 2026-10-23
**Status:** Open
**Area:** Ground agents

**What happened:** The workflow has Moss "resolve the missing flight state" and the agents draft the correction. But the cockpit only received static. Nothing in the design captures what the controller actually said.
**Why it matters:** Without the original words, the system can only guess the instruction. Guessing a clearance is unsafe.
**What we learned:** Trace each piece of data back to where it comes from. A step that "knows" something must have an input that carries it.
**Action:** Add a ground-side capture of the controller's own transmission (tower audio plus speech-to-text) and make it the primary source. Local state and the rulebook only verify it.
**Update 2026-10-23:** Design decided. Tower audio is transcribed with Cartesia STT using key terms (task B1). Stays Open until it works.

## M-003: Offline mode conflicts with ground approval

**Date found:** 2026-10-23
**Status:** Open
**Area:** Edge device

**What happened:** The pre-flight step says "Elastic goes silent for offline resilience," but recovery depends on the ground agents and a controller approving in real time.
**Why it matters:** If the aircraft is offline, the core feature does not work.
**What we learned:** Decide which features must work offline and which need a link, and write it down.
**Action:** Choose and document the aircraft-to-ground datalink. Define what the device does when the link is down (for example, only alert "transmission blocked, request say again").
**Update 2026-10-23:** Following the Moss sponsor notes, the edge keeps indexing locally in Moss when offline and plays the local alert (task A8). The datalink choice is still open (RA-5).

## M-004: Cartesia placement unclear

**Date found:** 2026-10-23
**Status:** Open
**Area:** Audio

**What happened:** The concept says Cartesia runs "on the Raspberry Pi," but Cartesia Sonic is mainly used as a cloud API.
**Why it matters:** A cloud call adds network latency and fails offline, which affects M-001 and M-003.
**What we learned:** Confirm how each vendor actually deploys before building claims on it.
**Action:** Check whether an on-device Cartesia model fits the Pi 5. If not, pre-generate common phrases or add a local TTS fallback.

## M-005: Key safety claim has no citation

**Date found:** 2026-10-23
**Status:** Open
**Area:** Docs

**What happened:** The opening cites a February 2026 NTSB finding about a 0.8-second overlap, with no report number or link.
**Why it matters:** The whole pitch rests on this. An unsourced claim is easy to dismiss.
**What we learned:** Every factual claim in the PRD needs a source next to it.
**Action:** Add the NTSB docket or report link to PRD section 1, or soften the wording until it is sourced.

## M-006: Certification not considered

**Date found:** 2026-10-23
**Status:** Open
**Area:** Edge device

**What happened:** The design taps directly into a certified aircraft's audio panel and PTT line, with no mention of approval.
**Why it matters:** Modifying certified avionics generally needs FAA approval. Ignoring it makes the product look unrealistic.
**What we learned:** In aviation, the regulatory path is part of the design, not a later step.
**Action:** Position the prototype as a simulator or portable device first. Note the certification path as future work.

## M-007: ES|QL described as the audit store

**Date found:** 2026-10-23
**Status:** Open
**Area:** Audit

**What happened:** The concept says events "stream into Elastic via ES|QL" and calls the result "immutable." ES|QL is a query language. It reads data, it does not ingest it, and it does not make data immutable.
**Why it matters:** Misusing a sponsor's product names hurts credibility with that sponsor.
**What we learned:** Use each tool's terms the way its own docs do.
**Action:** Describe ingest through Elastic indices or data streams, query through ES\|QL, and immutability through access controls and retention settings.

## M-008: "99% confidence" shown without a basis

**Date found:** 2026-10-23
**Status:** Open
**Area:** Ground agents

**What happened:** The directive card shows "Confidence: 99%" and "FAA Rule 4.2" as examples, but nothing defines how confidence is computed, and the rule reference is a placeholder.
**Why it matters:** Controllers may trust a number that has no meaning. A wrong rule citation is worse than none.
**What we learned:** Any number shown to a human decision maker must have a defined method behind it.
**Action:** Define the confidence score (for example, transcript match plus retrieval score). Replace the placeholder with a real paragraph from FAA Order JO 7110.65.

## M-009: Sponsor tools used as add-ons, not as the core

**Date found:** 2026-10-23 (from the [Sponsor Review](07-sponsor-review.md), S-1 and S-5)
**Status:** Open
**Area:** Other

**What happened:** The first PRD used Cartesia only for one-way speech at the very end, and Moss only for a GPS to taxiway lookup. Any TTS engine or a plain dictionary could have replaced them.
**Why it matters:** Sponsor judges score how central their tool is. An add-on use loses that criterion even if the product is good.
**What we learned:** Read the prize criteria before designing, and design each sponsor's tool into the core loop. Ask: "would the product break without it?"
**Action:** PRD v0.2 makes Cartesia the whole voice loop (tower STT, cut-off detection, advisory TTS, readback check) and Moss the shared agent memory and local search layer.

## M-010: Vendor claims written before checking the docs

**Date found:** 2026-10-23 (from the [Sponsor Review](07-sponsor-review.md), S-6)
**Status:** Open
**Area:** Docs

**What happened:** The PRD says Moss runs "in-process through WebAssembly/Rust." We have not checked this against the Moss docs, and we don't yet know whether one Moss space can be shared between two machines. This is the third time a vendor detail was assumed (after M-004 and M-007).
**Why it matters:** Sponsors know their own product. A wrong detail in the pitch hurts credibility, and a wrong sharing assumption would break our transport design.
**What we learned:** This is a pattern, not a one-off. Every vendor claim gets checked against the vendor's own docs before it goes in the PRD or pitch.
**Action:** Research RA-7. Keep WebSocket as the fallback transport until shared Moss spaces are confirmed. Added a working rule to the [Work Split](04-work-split.md#8-working-rules).
