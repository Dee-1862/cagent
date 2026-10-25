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

## 6. Agent Builder depth: what the product offers and where we stand

From Elastic's [Agent Builder overview](https://www.elastic.co/docs/explore-analyze/ai-features/elastic-agent-builder) (GA from 9.3, also on Serverless). The judge's point was to go deeper than retrieving from a document store, so each capability is listed with what we do.

| Agent Builder capability | What we do | Tag |
| --- | --- | --- |
| Custom agents with their own instructions and toolsets | Four agents, each with its own tool list (section 2) | BUILT, MEASURED LIVE |
| Custom tools (ES\|QL with parameters, index search) | Seven tools | BUILT, MEASURED LIVE |
| Workflows call agents (`ai.agent` step) | `unstep-blocked-call` and `unstep-readback-audit` | BUILT, MEASURED LIVE |
| Agents call workflows (a `workflow` tool on an agent) | Not used. Plan: the audit agent gets a tool that writes the shift briefing | PROPOSED |
| Search step before the agent, saving the answer to an index | Not yet in the blocked-call workflow. Plan: hybrid retrieval ahead of the agent, and the briefing workflow | PROPOSED |
| Scheduled and manual workflow triggers (alert-rule trigger also documented) | Manual only (the hub starts runs). Plan: a scheduled briefing | PROPOSED |
| Late answer shown on the open card instead of blocking it | Built in the room (3a): see below | BUILT, NEEDS LIVE RUN |
| MCP server (`/api/agent_builder/mcp`) and A2A server | Not used. A one-line MCP demo from a coding agent is cheap | PROPOSED |
| Permissions: security roles and API keys control which tools an agent can use and what data it can query | We use one key for all four agents. Per-agent keys or roles could turn "least privilege by tool" into enforced separation; not checked | PROPOSED, UNVERIFIED |
| Model selection: other model providers or local models through inference endpoints | Not used. A faster model for the agents is one lever on the 6.2 s; not measured | PROPOSED, UNVERIFIED |
| Skills (reusable instruction and tool bundles) | Not used | PROPOSED |
| Token usage monitoring | Not used. Would let us report tokens per stepped-on call | PROPOSED |

**Do the agents need to talk to each other?** Not on the critical path. Today the Intercept and Compliance agents run one after the other in a workflow; they do not hold a conversation, and each extra hop is another model call of seconds. Passing data through a workflow (search, then one agent, then save) gets the depth without the delay. Agent-to-agent work belongs off the critical path, for example a briefing workflow that an agent starts as a tool.

**Late citation (3a), and the one case that still waits.** The proposal card now goes out at once from the local check, and the Elastic agents' citation is added to the open card when it arrives (up to `UNSTEP_AGENTS_LATE_S`, default 30 s). The instruction never changes, confidence can only go down, and the step is labelled as arriving after the card. The exception: if the policy might relay a proposal by itself (restrictive and high confidence), the room still waits for the agents, because Intercept can veto it (match false lowers confidence). Making that case late would let an auto-relay happen before the veto.

## 7. Where the time goes, and the search-first fix

Rishit's measurement of five real runs of `unstep-blocked-call` (Kibana workflow history, R42):

| Step | Typical | Slowest |
| --- | --- | --- |
| Intercept agent | 12.7 s | 19.3 s |
| Compliance agent | 10.0 s | 10.0 s |
| Store result | 0.3 s | 0.4 s |
| Whole run | 24 s | 31 s |

Two things follow. The earlier 6 s wait mostly gave up before the agents answered, so the veto it was meant to give rarely arrived in time. And the Compliance agent takes 10.02 to 10.03 s on every run, which looks like a 10 s cap, not real work (not yet checked in the workflow's step settings). The citations it produced were real.

What the hub does about it now (BUILT, NEEDS LIVE RUN):

1. **Closest rule by search, no model.** Before the card is sent, the hub runs a hybrid search of the FAA order (keyword and semantic results fused, then reranked with `.jina-reranker-v3`, falling back to plain hybrid if the reranker is rejected). The card shows "Closest FAA rule: paragraph, score, ms". It is labelled as a search result, not as a judgment that the paragraph governs the call; the agents can still replace it. The search waits at most `UNSTEP_CITE_WAIT_S` (default 1.5 s). Its real latency is unmeasured.
2. **One agent call instead of two** (`unstep-blocked-call-fast`, agent `unstep-ground`, no tools). The hub passes in the paragraph it found, so the agent makes no tool calls. Opt in with `UNSTEP_BLOCKED_WORKFLOW=unstep-blocked-call-fast` after a live run shows it is faster. Not run live yet.
3. **Briefing workflow** (`unstep-briefing`): search the last hour of the audit trail, the audit agent writes a handoff briefing citing event ids, saved to `unstep-briefings`. Off the radio path. Not run live yet. The step type names used (`elasticsearch.search`, `ai.agent`, `elasticsearch.index`) are the ones in Elastic's workshop repo.

Still unproven and not claimed: that the one-agent version is faster, that search latency is low enough to stay on the path, and that the closest paragraph is usually the governing one.

**Parallel mode (BUILT, NEEDS A LIVE RUN).** `UNSTEP_BLOCKED_WORKFLOW=parallel` splits the two-agent workflow by topic into `unstep-blocked-intercept` (is this the controller's call, what was lost) and `unstep-blocked-compliance` (does the paragraph the hub already found govern the instruction). The hub starts both at the same moment and waits for the slower one, so the wait is the maximum of the two, not the sum. Each uses a tool-less "lite" agent that makes one model call from the data it is given, and writes its answer to its own document (`<event>:intercept`, `<event>:compliance`) so neither overwrites the other. If only one answers, its half is still used, and an Intercept "no match" still lowers confidence. Each branch's own time is recorded (`branches_ms` in the audit record). From the 24 s sum (12.7 s plus 10.0 s plus 0.3 s) the best case is the slower single call; that number is a hypothesis until measured. The next levers are a faster model for the lite agents (Agent Builder's model selection; not checked) and shorter outputs (already capped in their instructions).

## 8. A team of four watchers, side by side (BUILT, behind a switch, NEEDS A LIVE RUN)

Separate from the per-call parallelism in section 7, there is parallelism across jobs. Four watchers each own one part of the tower's work and run at the same time over the same radio events (`unstep/monitor/`). Each keeps its own timers, has its own queue and task, and posts rows to the console feed in the agreed `agent_action` format. One failing does not stop the others (tested).

| Watcher | Watches | Flags |
| --- | --- | --- |
| Readback watcher | Every approved clearance and its readback | No readback after 20 s; a readback that does not match (and clears when it does) |
| Runway watcher | Landing, takeoff and line-up clearances | Two aircraft cleared into one runway while the first is still open (90 s). Flag only, it never proposes an order |
| Tracking watcher | Keys and stepped-on calls per aircraft | A key held over 15 s; the same aircraft stepped on twice in 5 min |
| Flow watcher | The frequency as a whole | Three stepped-on calls in 60 s (busy), and clears when quiet |

They are fixed rules, not language models: they answer in microseconds, same input same output, and the thresholds are our own early warnings, not FAA procedures. An Elastic agent can be asked to explain a row afterwards, off this path. `team.open_items()` lists what is still waiting, which is what the shift handoff briefing needs.

Connected to the live room behind `UNSTEP_WATCHERS=1` (off by default): `_observe` feeds every gateway message, `_key` notes key down and up, and rows go to the console feed. Not done: the console drawing (Rishit's side) and a live run. The landing of an idle pilot already posts its own Monitor row.
