# Agent Map: Who Does What, What Data Each Sees, and the Team Of Agents

Describes how one spoken sentence moves through Unstep, which Elastic agent can read which data, and the plan to widen the agents' jobs. It separates what exists from what is only proposed. Nothing here claims an effect in a real facility.

| Field | Value |
| --- | --- |
| Status | v0.1. Sections 1 and 2 describe code that exists. Sections 3 and 4 are proposals; the first four jobs and the feed format were agreed by Rishit's side in R34 |
| Written by | Deekshith's side (agent), for review by Rishit's side |
| Related | [19-elastic-moss-plan.md](19-elastic-moss-plan.md), [10-agentic-architecture.md](10-agentic-architecture.md), [18-benchmark.md](18-benchmark.md) |

Tags: **BUILT** (code exists and passes offline tests), **MEASURED LIVE** (run on real services by us), **PROPOSED** (only in this document).

## 1. One sentence, end to end (BUILT)

There is no master agent. Fixed code decides what a sentence is, and only then are the agents that event needs called. A sentence reaches zero to two agents.

```
sentence (speech to text)
   -> gateway + readback matcher + percolator        fixed code, no agent
        |
        |- ordinary call, readback correct -> logged, nothing else runs
        |- stepped-on call -> workflow unstep-blocked-call
        |        -> intercept agent  (what was lost?)
        |        -> compliance agent (which FAA paragraph governs it?)
        |        -> proposal to the controller, who approves or overrides
        |- wrong readback -> workflow unstep-readback-audit
        |        -> readback auditor agent (why it did not match, with the paragraph)
        '- controller types a question -> audit agent (answers from the audit trail)
```

The same sentence always takes the same path. With Elastic agents switched off (`UNSTEP_ELASTIC_AGENTS` unset), the same steps run with local stand-ins. A human decides every proposal. MEASURED LIVE (Rishit, R31): the compliance agent cited paragraph 3-7-4 on a real stepped-on call, and the agents add about 6.2 s, so the call-to-fix time was 9.2 s against 2.9 s with the local stand-in.

## 2. What data each agent can see (BUILT)

| Agent | Tools it can call | What those tools read |
| --- | --- | --- |
| `unstep-intercept` | `unstep_recent_blocked_calls` | Blocked calls for one callsign in the last 30 minutes |
| `unstep-compliance` | `unstep_faa_search` | The FAA text index (`unstep-faa`) only |
| `unstep-readback-auditor` | `unstep_faa_search`, `unstep_readback_history` | FAA text, and the readback history of one event |
| `unstep-audit` | four audit tools | Aggregates over the last hour of the audit trail |

- Every tool is a stored ES|QL query (or an index search) with a fixed shape. An agent fills in parameters such as `callsign` or `event_id`; it cannot run a free-form query.
- The workflow passes the agent only the one event it is about, not the log.
- All four agents run under one API key. Separation is by tool assignment and fixed queries, not by per-agent permission. Say "least privilege by tool". Do not say "isolated by permission" until Elastic's key scoping for Agent Builder has been checked (PROPOSED check).
- Agents never write to the audit trail. The hub and the gateway write events; agents only read through their tools.
- Moss is separate: each plane's session is its own, and only the flight log is shared (section 3.1 of [19-elastic-moss-plan.md](19-elastic-moss-plan.md)).

## 3. Widening the agents' jobs (PROPOSED, first four agreed in R34)

The pitch: the controller supervises a team of agents. The agents take routine checking off a controller who is short-staffed or working combined positions (the NTSB found combined positions at DCA raised workload). They do not replace a position and the project makes no claim about headcount.

| Job | Relatable moment | What it does | Status |
| --- | --- | --- | --- |
| No readback | Saying "okay" without hearing the address | Timer on every clearance; flag when no readback after N seconds | Agreed (R34), not built |
| Stuck mic | A mic left on blocks the whole room | Flag a transmitter keyed too long | Agreed (R34), not built |
| Conflicting clearances | Two people told "go ahead" into one doorway | Flag two aircraft cleared into one runway, or a hold-short never acknowledged. Flag only; no proposed order yet | Agreed (R34), not built |
| Shift handoff briefing | The notes the last shift never left | Briefing from the audit trail through ES|QL and `unstep-audit`, every line linked to its events | Agreed (R34), not built |
| Say-again counter | A call that keeps dropping | Flag an aircraft that asked for a repeat more than twice | Later; fold into no readback |
| Held too long (holiday gate) | The plane that lands and waits for a gate | Timer on hold instructions and a queue count. Gate status would be simulated and labelled | Later; off-story for now |
| Runway or frequency change | Half the planes keep the old runway | List aircraft that have not acknowledged the change | Later |
| Priority | An ambulance in traffic | Medical or low-fuel call moves to the front | Later; needs checking against FAA procedure |
| Debrief | A sports replay | Timeline of a bad call from recorded events | Covered by the audit trail |

Rules that hold for every job: fixed thresholds, written down and tested; agents may add a citation, a draft or a flag but never change a route; the controller can switch each agent off; thresholds are our own early warnings, not FAA procedures.

The monitor jobs post into one "Agents at work" feed on the console (green: done by the agents, amber: waiting for the controller) using one message format, `agent_action` (agreed in R34 pending confirmation). The feed is drawn by Rishit's side from existing messages plus the new monitor jobs.

## 4. Ideas not agreed (PROPOSED, not planned)

These came up and are recorded so they are not lost. None is built or scheduled.

- **A triage ranker.** Open items get a score from a written, tested table (for example a medical or low-fuel call first, then a live runway conflict, then an unconfirmed restrictive instruction). The agent would only write one plain sentence per item and could not reorder or hide anything; the screen shows the top few and the count of the rest. Needs: the table checked against FAA duty-priority text (JO 7110.65 paragraph 2-1-2 puts separating aircraft and safety alerts first and leaves the rest to judgment), and a review by someone who works in a tower. It could be measured only on a simulated shift: whether the item we labelled most critical was shown first, that nothing was lost, and that the same inputs give the same order. That shows the ranker follows its table, not that the table is right.
- **Routing work between people on shift.** Items go to an owner (tower, ground, ramp), overflow is offered to a free colleague who may decline, unacknowledged items go to a supervisor, and a combined position can prompt the supervisor to staff the second position. Control responsibility never moves automatically; positions are tied to a frequency and certification. Ownership rules differ by facility. Measured only on a simulated multi-person shift (unowned items, time to acknowledgement, longest queue, on-time escalations). Needs a per-person console view, so it is Rishit's decision.
- **A roster and headcount model.** Withdrawn (R33). It read as "fewer controllers" and clashed with "the controller decides".

## 5. What we can truthfully say

| Say this | Tag |
| --- | --- |
| "A spoken sentence is checked by fixed code first; only the agents that event needs are called, and a person decides." | BUILT |
| "Each agent can only call its own fixed queries." | BUILT |
| "The compliance agent cites the FAA paragraph for the instruction." | MEASURED LIVE (three real stepped-on calls, R31 to R35) |
| "The agents also watch for a missing readback, a stuck mic and conflicting clearances." | PROPOSED, not built. Do not say it yet |
| "Agents are isolated by permission." | Not checked. Do not say it |
| "This reduces staffing, workload or incidents." | Not measured. Do not say it |
