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
| M-004 | Cartesia placement unclear | Audio | Resolved |
| M-005 | Key safety claim has no citation | Docs | Open |
| M-006 | Certification not considered | Edge device | Open |
| M-007 | ES\|QL described as the audit store | Audit | Open |
| M-008 | "99% confidence" shown without a basis | Ground agents | Open |
| M-009 | Sponsor tools used as add-ons, not as the core | Other | Open |
| M-010 | Vendor claims written before checking the docs | Docs | Resolved |
| M-011 | Moss used as a message bus and Cartesia as an overlap detector | Other | Resolved |
| M-012 | "Collision" used for two different things | Docs | Resolved |
| M-013 | Voice was only the output, screens were the interface | Audio | Resolved |
| M-014 | Local hint could have suggested a permissive clearance | Edge device | Resolved |
| M-015 | Both developers built the same gateway and contracts | Other | Resolved |

---

## M-001: 90 ms read as end-to-end latency

**Date found:** 2026-10-23
**Status:** Open
**Area:** Audio

**What happened:** The concept said the system whispers the command "in under 90 milliseconds." That figure is Cartesia's time to first audio byte. The real path also includes an uplink, agent verification, a human click and a downlink.
**Why it matters:** Judges, reviewers or regulators will spot that a human approval cannot happen in milliseconds, which undermines every other number.
**What we learned:** State every latency figure with its start and end point. Never let a component benchmark stand in for system latency.
**Action:** PRD section 8 now has a per-segment latency budget. Measure and fill in the TBD rows.
**Update 2026-10-23:** PRD v0.3 drops "under 90 ms" as our figure. The vendor says under 90 ms for the model, and a third party measured about 166 to 190 ms with network. We show only our own measured numbers on screen.

## M-002: No source for the blocked instruction's content

**Date found:** 2026-10-23
**Status:** Open
**Area:** Ground agents

**What happened:** The workflow has Moss "resolve the missing flight state" and the agents draft the correction. But the cockpit only received static. Nothing in the design captures what the controller actually said.
**Why it matters:** Without the original words, the system can only guess the instruction. Guessing a clearance is unsafe.
**What we learned:** Trace each piece of data back to where it comes from. A step that "knows" something must have an input that carries it.
**Action:** Add a ground-side capture of the controller's own transmission (tower audio plus speech-to-text) and make it the primary source. Local state and the rulebook only verify it.
**Update 2026-10-23:** Design decided. Tower audio is transcribed with Cartesia STT using key terms, finalized on PTT release, with word timestamps to mark the blocked words (tasks B2 and B3). Stays Open until it works.

## M-003: Offline mode conflicts with ground approval

**Date found:** 2026-10-23
**Status:** Open
**Area:** Edge device

**What happened:** The pre-flight step says "Elastic goes silent for offline resilience," but recovery depends on the ground agents and a controller approving in real time.
**Why it matters:** If the aircraft is offline, the core feature does not work.
**What we learned:** Decide which features must work offline and which need a link, and write it down.
**Action:** Choose and document the aircraft-to-ground datalink. Define what the device does when the link is down (for example, only alert "transmission blocked, request say again").
**Update 2026-10-23:** Following the Moss sponsor notes, the edge keeps indexing locally in Moss when offline and plays the local alert (task A8). The datalink choice is still open (RA-5).
**Update 2026-10-23 (v0.3):** Moss sessions must be opened before going offline, since opening one checks credentials with Moss Cloud. Offline, the cockpit plays a pre-generated alert and can still give a labeled local hint.

## M-004: Cartesia placement unclear

**Date found:** 2026-10-23
**Status:** Resolved
**Area:** Audio

**What happened:** The concept says Cartesia runs "on the Raspberry Pi," but Cartesia Sonic is mainly used as a cloud API.
**Why it matters:** A cloud call adds network latency and fails offline, which affects M-001 and M-003.
**What we learned:** Confirm how each vendor actually deploys before building claims on it.
**Action:** Check whether an on-device Cartesia model fits the Pi 5. If not, pre-generate common phrases or add a local TTS fallback.
**Resolution 2026-10-23:** We use Cartesia as a cloud API over WebSocket for STT and TTS. Offline, the cockpit plays pre-generated Cartesia audio for fixed phrases and shows the rest as text.

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
**Update 2026-10-23 (v0.3):** v0.2 over-corrected in places (see M-011). v0.3 keeps sponsors central, but only in ways their docs support: STT on both sides with word timestamps, turn STT for readbacks, Moss local hint search and sessions, and an Elastic Workflow with three agents.

## M-010: Vendor claims written before checking the docs

**Date found:** 2026-10-23 (from the [Sponsor Review](07-sponsor-review.md), S-6)
**Status:** Resolved
**Area:** Docs

**What happened:** The PRD says Moss runs "in-process through WebAssembly/Rust." We have not checked this against the Moss docs, and we don't yet know whether one Moss space can be shared between two machines. This is the third time a vendor detail was assumed (after M-004 and M-007).
**Why it matters:** Sponsors know their own product. A wrong detail in the pitch hurts credibility, and a wrong sharing assumption would break our transport design.
**What we learned:** This is a pattern, not a one-off. Every vendor claim gets checked against the vendor's own docs before it goes in the PRD or pitch.
**Action:** Research RA-7. Keep WebSocket as the fallback transport until shared Moss spaces are confirmed. Added a working rule to the [Work Split](04-work-split.md#8-working-rules).
**Resolution 2026-10-23:** Rishit read the Moss and Cartesia docs ([Advice](08-advice.md#sources)). The unverified wording is gone from PRD v0.3, and how Moss handoff works is recorded in research RA-7. The working rule stays.

## M-011: Moss used as a message bus and Cartesia as an overlap detector

**Date found:** 2026-10-23 (from [Advice](08-advice.md#5-concerns-with-prd-v02), concerns 1 to 4)
**Status:** Resolved
**Area:** Other

**What happened:** PRD v0.2 sent live messages such as `ApprovedDirective` through a shared Moss space and made milestone M2 depend on it. It also listed Cartesia "cut-off detection" as a second overlap detector. Both came from sponsor notes taken at face value. Moss handoff actually goes through Moss Cloud, `push_index()` replaces the whole index, and auto-refresh polls every 300 seconds. Cartesia turn detection finds pauses, not overlaps, and the cockpit hears static anyway.
**Why it matters:** The approval would have taken minutes to arrive, two writers would have overwritten each other, and our first milestone was blocked on an unconfirmed behavior.
**What we learned:** A sponsor's spoken suggestion is a direction, not a spec. Turn it into a design only after reading the docs. Never put an unverified vendor behavior on the critical path of the first milestone.
**Action:** v0.3 uses WebSocket for live messages, Moss as local memory with one writer per index, and replaces cut-off detection with tower and cockpit transcript comparison. M2 runs on WebSocket only.

## M-012: "Collision" used for two different things

**Date found:** 2026-10-23 (from [Advice, section 1.1](08-advice.md#11-why-the-idea-feels-hazy))
**Status:** Resolved
**Area:** Docs

**What happened:** The docs called radio overlap a "collision," while the opening story was about an aircraft collision. Readers couldn't tell whether Unstep was collision avoidance.
**Why it matters:** Judges would think we claim to prevent crashes, which is radar and TCAS territory, and the idea felt hazy.
**What we learned:** One word, one meaning. Define key terms once and keep to them.
**Action:** PRD v0.3 has a Terms section. Radio overlap is "stepped-on" or "blocked." "Collision" only means aircraft.

## M-013: Voice was only the output, screens were the interface

**Date found:** 2026-10-23
**Status:** Resolved
**Area:** Audio

**What happened:** In v0.3 the controller clicked Approve on a dashboard and the pilot only listened. Voice was how Unstep spoke, not how people used it. Every past Cartesia track winner made the voice exchange the product.
**Why it matters:** "Use of Cartesia" is 25% of the Cartesia score, and the judges asked for voice to be core, not a feature added for the demo. Pilots and controllers are also eyes-busy and hands-busy, so screens are the wrong main interface for them.
**What we learned:** Test the product with the screens off. If it stops working, voice isn't core.
**Action:** PRD v0.4 adds pilot voice queries (A10) and controller voice approval (B10), a chime before every Unstep message, and a demo where nobody touches a screen until the end. The click stays as a fallback.

## M-014: Local hint could have suggested a permissive clearance

**Date found:** 2026-10-23
**Status:** Resolved
**Area:** Edge device

**What happened:** The v0.3 hint rules said "Likely" and "Awaiting controller," but didn't limit what could be hinted. A wrong "Likely cleared for takeoff" or "Likely cross Runway 33" could lead a pilot into a runway incursion. Also, the demo hint had no stated source, so it would look hardcoded.
**Why it matters:** A wrong hold short is safe. A wrong permission to move is not. Responsibility judges will ask exactly this.
**What we learned:** Classify every automated suggestion by what happens if it's wrong, and only automate the side where wrong is safe. Show where every suggestion came from.
**Action:** PRD v0.4: hints for restrictive instructions only (hold short, stop, hold position, go around). Every hint shows its source Moss record. The demo seeds the flight session with the earlier taxi clearance the hint is drawn from.

## M-015: Both developers built the same gateway and contracts

**Date found:** 2026-10-23
**Status:** Resolved
**Area:** Other

**What happened:** The gateway (B1) and the contracts (S1) were built twice at the same time: once on master in `unstep/`, once on the Dev B branch in `contracts/` and `ground/`. Neither side pulled or said which task they were starting.
**Why it matters:** Half a block of work was thrown away, and the merge needed manual conflict resolution in eleven files.
**What we learned:** Pull before starting a task, and say which task you are taking before you start it. A shared task (S1) needs one person to draft and the other to review, not both drafting.
**Action:** Kept `unstep/` as the codebase and removed the duplicate. From now on, each task starts with a pull and a short note in the team chat or a draft PR naming the task.
