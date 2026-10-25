# Milliseconds: What Is Fast, Why, and What Elastic Contributes

A language model call takes seconds, so the pilot-facing path cannot wait on one. This document says which parts of Unstep answer in milliseconds, why, and what claim about Elastic is honest. It separates BUILT, MEASURED LIVE and PROPOSED.

| Field | Value |
| --- | --- |
| Status | v0.1. The stored-rules path is BUILT and tested with fakes; its Elastic timing is NEEDS A LIVE RUN |
| Written by | Deekshith's side (agent), for review by Rishit's side |
| Related | [20-agent-map.md](20-agent-map.md), [18-benchmark.md](18-benchmark.md), [19-elastic-moss-plan.md](19-elastic-moss-plan.md) |

## 1. Where the time is, measured

| Stage | Time | Tag |
| --- | --- | --- |
| Tower transcript final after release | 155 ms | MEASURED LIVE (R28) |
| Readback checked by Elastic's percolator | 3.0 ms | MEASURED LIVE |
| Moss lookup in the plane's own session, warm | 0.2 to 0.4 ms (first hint 638 ms) | MEASURED LIVE |
| First audio of the private advisory | 201 ms | MEASURED LIVE |
| Elastic workflow with two agents (Intercept 12.7 s, Compliance 10.0 s, store 0.3 s) | 24 s, up to 31 s | MEASURED LIVE (R42) |

The agents are the slow part because each step is a model call. The fix is not a faster model. It is to take the agents off the path the pilot waits on.

## 2. The idea: ask a database, not a model

Elastic's percolator reverses the usual search. Normally you store documents and run a query. A percolator stores the queries and runs a document through them. We already use it to check readbacks (3.0 ms live, no model). The same mechanism answers "which FAA rule governs this instruction":

- Each rule is stored in the `unstep-rules` index as a query ("hold short" or "holding short") with its paragraph and a review status (`elastic/rules/rules.json`, loaded by `scripts/deploy_elastic.py`).
- A proposed instruction is the document. Elastic returns the matching rules in one request, with its own `took`.
- The hub shows the rule on the card at once. If Elastic is slow (over `UNSTEP_RULES_WAIT_S`, 0.3 s) or down, the hub uses the same rules in process. If no stored rule matches, it falls back to the hybrid search, and the agents explain afterwards, in parallel and off the path.

What Elastic contributes that a hard-coded table does not:

1. **Rules are data.** Change a rule in the index and the next instruction uses it. No deploy, no restart. (BUILT, tested with a fake that returns an edited rule; not yet shown live.)
2. **The matching is in the engine and stays flat as rules grow.** In process, scanning the stored queries one by one took 0.02 ms at 7 rules, 0.2 ms at 100, 2.0 ms at 1,000 and 9.6 ms at 5,000 (`scripts/rule_latency.py`, local, synthetic filler rules). Whether Elastic stays flat is what `--elastic` measures. NEEDS A LIVE RUN.
3. **Same store for rules, audit and agents.** The rule that fired, its timing and its status go into the audit trail with everything else, and the audit agent can answer "which rule fired most this week".

## 3. What we do not claim

- **Not "only Elastic can do this".** Other engines built on Lucene have percolators too, and at our real size (a handful of rules) a plain dictionary is faster than any network call: 0.0001 ms in `rule_latency.py`. The honest claim is that Elastic gives millisecond matching *and* rules as editable data *and* an audit trail *and* agents in one place, and that the matching does not slow down as the rule set grows (to be measured).
- **Not that the paragraph is right.** Only `hold-short` has a paragraph, and it is a *candidate*: the Compliance agent cited it live. Nobody has read the FAA text and signed it off. The card says "Candidate rule, not yet reviewed" until a person changes the status to `reviewed` in `rules.json` (and redeploys, or edits the document in the index). The other rules have no paragraph and claim nothing.
- **Not a measured ms number from Elastic yet.** The `took` and wall time will appear in the card text and in `rule_latency.py --elastic` after a live run.

## 4. What stays slow, on purpose

The agents (Intercept, Compliance, or the one-call `unstep-ground`) explain the stepped-on call and check the rule. They take seconds, run after the card is shown, and can run in parallel. They can add a citation or lower confidence; they never change the instruction. The one case that still waits for them is a proposal the policy might auto-relay, where Intercept can veto it.

## 5. Other ideas, not built

| Idea | Why it might help | Status |
| --- | --- | --- |
| Start work early (search, advisory pre-render, Moss lookup) as soon as an overlap is detected, discard if unused | Hides latency behind the human decision | PROPOSED |
| Pre-render the spoken advisory while the controller decides | Playback right after approval | PROPOSED |
| Explain common cases from templates filled with the call's words; the model only writes unusual cases | Seconds become microseconds for the common case | PROPOSED |
| Cap what agents produce (one label, short JSON) and give them the data, not tools | Output tokens drive model time; the 10 s Compliance step looks like a cap or a tool loop | PROPOSED |
| Keep connections warm and put the hub in the same region as Elastic | Network round trips are part of every number | PROPOSED |
| ES\|QL `ENRICH` or `LOOKUP JOIN` from instruction type to rule | A second Elastic-native lookup | PROPOSED, preview status unchecked |
| Cache by normalized key | Same instruction, same answer | PROPOSED |

## 6. To run live (Rishit's laptop)

1. `python scripts/deploy_elastic.py --dry-run`, then `python scripts/deploy_elastic.py`. It creates `unstep-rules` and one document per rule. Paste any `FAIL` or `warn`.
2. `python scripts/rule_latency.py --elastic --sizes 7,100,1000,5000`. Paste the table. It uses a temporary `unstep-rules-bench` index with synthetic filler and deletes it.
3. One stepped-on call with `UNSTEP_ELASTIC_AGENTS=1`. The card's rule line carries the milliseconds Elastic reported.
4. Read the FAA paragraph for `hold short` in `data/faa` and, if it governs the instruction, change its status to `reviewed`.
