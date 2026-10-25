# Milliseconds: What Is Fast, Why, and What Elastic Contributes

A language model call takes seconds, so the pilot-facing path cannot wait on one. This document says which parts of Unstep answer in milliseconds, why, and what claim about Elastic is honest. It separates BUILT, MEASURED LIVE and PROPOSED.

| Field | Value |
| --- | --- |
| Status | v0.2. The stored-rules path is BUILT and its Elastic matching time MEASURED LIVE (R47); the card-level numbers still need a live run |
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
- The hub keeps an in-memory copy of the stored rules and answers from it in microseconds. Elastic stays the source of truth: the hub refreshes the copy from the `unstep-rules` index in the background every `UNSTEP_RULES_SYNC_S` seconds (default 30), so a rule edited in Elastic reaches the hub within that time, with no deploy. If no stored rule matches, it falls back to the hybrid search, and the agents explain afterwards, in parallel and off the path.
- Why not ask Elastic on every instruction: Elastic's own matching time was 1 ms but the wall time from outside was about 75 ms, nearly all network. The percolator query is still how the same answer is produced server-side (`rule_latency.py --elastic`), and it is still the way to test a rule against Elastic itself.

What Elastic contributes that a hard-coded table does not:

1. **Rules are data.** Change a rule in the index and the next instruction uses it. No deploy, no restart. (BUILT, tested with a fake that returns an edited rule; not yet shown live.)
2. **The matching is in the engine and stays flat as rules grow.** MEASURED LIVE (Rishit, R47, `scripts/rule_latency.py --elastic`, synthetic filler rules): Elastic's own `took` was 2.0 ms at 7 rules and 1.0 ms at 100, 1,000 and 5,000. The same stored queries scanned one by one in Python went from 0.02 ms at 7 rules to about 11 ms at 5,000. The wall time from his laptop was about 75 ms, mostly the network, so the hub must sit near Elastic to see the ms.
3. **Same store for rules, audit and agents.** The rule that fired, its timing and its status go into the audit trail with everything else, and the audit agent can answer "which rule fired most this week".

## 3. What we do not claim

- **Not "only Elastic can do this".** Other engines built on Lucene have percolators too, and at our real size (a handful of rules) a plain dictionary is faster than any network call: 0.0001 ms in `rule_latency.py`. The honest claim is that Elastic gives millisecond matching *and* rules as editable data *and* an audit trail *and* agents in one place, and that the matching does not slow down as the rule set grows (to be measured).
- **Not that the paragraph is right.** Only `hold-short` has a paragraph, and it is a *candidate*. Rishit's agent read the FAA text and found 3-7-2 "Taxi and Ground Movement Operations" governs hold-short instructions (3-7-4 is a weaker fit), and the rule now points at 3-7-2. A person has still not signed it off. The card says "Candidate rule, not yet reviewed" until a person changes the status to `reviewed` in `rules.json` (and redeploys, or edits the document in the index). The other rules have no paragraph and claim nothing.
- **Not a card-level number yet.** The card's rule line (with Elastic's ms) has not been captured in a live room run, and the wall time includes the network.

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

## 7. On-board restore time (Moss MM1)

MEASURED LIVE (Rishit, R46): a plane's memory restored from disk with no cloud in 44.9 ms (4 documents). That number is the Moss SDK's `load_from_disk` for the first restore in a process; the session was already open, so it is not the credential check. Whether the 45 ms is a one-off start-up cost (loading the embedding model) or per restore is NOT known. `scripts/moss_live_check.py` part 5 now restores three times and prints each with its breakdown (`open_ms`, `load_from_disk_ms`), so the cold and the warm numbers can be claimed separately.

What can lower it, in the order I would try, each a hypothesis until measured:
1. If the warm restores are single digit, the first one is a model start-up cost: do the first load at hub start (planes are started then anyway, before any pilot joins), so no pilot waits on it.
2. Restore the planes in parallel at start instead of one after another.
3. Keep snapshots small (a plane holds a handful of documents; the size is not the problem at this scale).

What is honest to say: "after a restart, each plane answers from restored memory with no cloud and no index download; a restore took 45 ms cold on a laptop". Do not say Moss is the only way to do this: any in-process index that can write itself to disk can restore without a network, so the claim is about what we measured, not about exclusivity. What Moss gives us is the same in-process semantic search we already use, with its own snapshot, so we did not build a persistence layer.

## 8. Making the agents faster: what is built, and what the research suggests

Live (Rishit, R47): the parallel pair took 12.2 s, and Intercept is now the slow half (10.7 to 22.6 s, against 5.7 to 7.1 s for compliance-lite). Intercept is also the answer we need least: when the hub's own transcript match is already high confidence, the agent mostly repeats it.

**Built (dev-b, tested with fakes; the timing effect is a hypothesis until a live run):**
1. **Ask Intercept only when the local match is not already high confidence** (`UNSTEP_INTERCEPT=auto`, the default; `always` or `never` also work). For a high-confidence call the agent pipeline is then compliance-lite alone, which was 5.7 to 7.1 s live. This is a cascade: the cheap deterministic check decides, and the model is asked only where the check is unsure.
2. **Reuse the Compliance answer for the same instruction against the same paragraph** (`UNSTEP_COMPLIANCE_CACHE_S`; **off by default since the geography decision, D51**: real questions differ, and a hit skips the agent so it would not credit Elastic; set it above 0 only to replay a scripted demo). A repeat (the demo repeats "hold short runway 33") starts no workflow at all and the branch time is 0. The answer is only reused when the cited paragraph matched the stored rule and was found in `unstep-faa`; the notes say it was reused.

Neither changes what the controller sees first (the card is already there at once); they shorten how long the agents' note takes to arrive and how many model calls we pay for.

**Ideas from the research, not built, each a hypothesis for us:**

| Idea | Source (titles from memory, check before quoting) | Fit for Unstep |
| --- | --- | --- |
| Model cascades: try a cheap path first and call the large model only when unsure | FrugalGPT (Chen, Zaharia, Zou, 2023); RouteLLM (Ong et al., 2024) | This is what item 1 does by hand; a learned router needs labelled calls we do not have |
| Semantic caching of model answers | GPTCache (open source library) | Item 2 is the exact-key version, which is safer for a rule check than a fuzzy match |
| Speculative decoding: a small draft model proposes tokens and the large one verifies them | Leviathan, Kalman, Matias, 2023 | Needs control of the decoding engine; Elastic's hosted agents do not expose it |
| Shorter prompts by compression | LLMLingua (Jiang et al., 2023) | Our prompts are already about 60 words of output; the saving would be small |
| Fewer sequential model turns: write the answer in parallel parts | Skeleton-of-Thought (Ning et al., 2023) | Intercept already answers in one short sentence |
| A faster model for these two agents | Product setting | Agent Builder has no per-agent model field (R47). The default connector for the whole project is set in Kibana; whether switching it to a small fast model helps, and what it does to answer quality, is for Rishit to try. Not claimed |
| Fine-tune a small classifier for "is this the controller's call" | Standard practice | Needs labelled data from real stepped-on calls; roadmap, not demo |

## 9. Measured live in this sandbox (network opened by Deekshith, 2026-10-25)

Real Cartesia and Moss calls from the development sandbox, not from Rishit's laptop, so the network path differs.

| Check | Result |
| --- | --- |
| Moss: restore a plane's session from disk | 0.9 ms the first time and 0.5 to 0.6 ms after (`load_from_disk` itself). Opening the session takes 260 to 340 ms because it contacts Moss; restart to answer was 2,036 ms with that first open included |
| Rishit's laptop, same check (his message to Deekshith) | 1.4 ms warm, 16 ms cold; the roughly 300 ms he saw was opening the session |
| Moss: fragment search, last-minute and whole-exchange answers | 1 ms, 0.0 ms and 0.47 ms; the unrelated fragment scored 0.0 and fell below the floor |
| Moss Cloud push (part 4) | still fails: "usage limit reached; billing must be updated" |
| Cartesia captions, one clip, three runs | manual endpoint: 6 updates while speaking, median gap 793 ms; turns endpoint: 10 updates, median gap 374 ms, but its last update came 992 ms after the clip ended (manual: 202 ms) |
| Cartesia turns endpoint, fast versus paced audio | 5 of 5 correct and 0 empty for both: the empty-transcript report did not reproduce again |
| Cartesia Sonic first audio | 132 ms on the first request, 128 to 146 ms warm |
| Cartesia 429 probe | none up to 4 concurrent generations (this does not rule out a plan limit above that) |
| Pronunciation dictionary | `CARTESIA_PRONUNCIATION_DICT_ID` is not set, so only the no-dictionary baseline ran: tree, fife, fower, Unstep, juliett, quebec all heard right 2 of 2; NOTAM 1 of 2; the "niner" control 1 of 2 |

The caption result suggests `UNSTEP_CAPTION_SOURCE=turns` would look smoother (half the gap between updates). It is one clip and three runs, so it is indicative, not a distribution.

What this means for "single-digit ms": restoring a plane's memory from disk is single digit milliseconds (about 1 ms here and 1.4 ms warm on Rishit's laptop). The 260 to 340 ms is opening the session with Moss, which should be done once at hub start, not per restore.

Opening sessions: with a real Moss project from this sandbox, six sessions took 6.3 s one after another and 3.2 s opened at once. The hub now starts planes at once. The remaining time per session is Moss's own and is spent once at hub start.

## 10. Why the rule is compiled ahead of time (the star-tracker idea)

A star tracker identifies the stars in a camera image in milliseconds because the hard, fuzzy work was done once, on the ground: a catalog of known patterns is built ahead of time, and in flight it is a lookup. Unstep's rule lookup does the same. `scripts/compile_rule_catalog.py` runs the slow, fuzzy search (hybrid keyword and meaning search with a reranker over the FAA order in Elastic) for every instruction type, offline, and prints candidate paragraphs for a person to read. At run time the hub answers from the stored rule and never searches.

MEASURED LIVE (this sandbox, 2026-10-25, `compile_rule_catalog.py`): the hybrid search with `.jina-reranker-v3` took about 700 ms wall (Elastic's own `took` about 650 ms, 475 to 708 ms across seven queries; the first call 1.1 s). So the search is a sub-second tool, not a millisecond one, which is the reason it stays out of the live path. The stored-rule lookup took 1 to 2 ms in Elastic (R47).

What the search suggested (reranker scores rank candidates, they do not prove a paragraph governs; none of these has been read by a person):

| Instruction | Top candidate | Note |
| --- | --- | --- |
| line up and wait | 3-9-4 Line Up And Wait (1.544) | the title names the instruction |
| cleared for takeoff | 3-9-10 Takeoff Clearance (1.514) | the title names the instruction |
| cleared to land | 3-10-5 Landing Clearance (1.625) | the title names the instruction |
| stop | 3-7-1 Ground Traffic Movement (1.522) | weak |
| hold short | 3-7-4 Runway Proximity (1.443), then 3-10-9 (1.393), then 3-7-2 (1.238) | Rishit's reading of the text says 3-7-2; the search and the live Compliance agent prefer 3-7-4: a person must decide |
| hold position | 3-7-4 (1.231), 3-7-2 (1.17) | weak |
| go around | 3-10-9 Runway Exiting (1.273) | weak, not a clear match |

`rules.json` now carries the three title-matching ones as `candidate` (the card says "Candidate rule, not yet reviewed"), keeps hold-short on 3-7-2 with a note that the search disagrees, and leaves the weak ones without a paragraph. The new rules reach the stored copy in Elastic at the next `deploy_elastic.py`.

The agents' part in this picture: they are the compilers' assistants and the second opinion, not the runtime. They can be asked, offline, to explain or challenge a candidate; the runtime lookup is deterministic and the same input gives the same rule.

MEASURED LIVE (this sandbox, against the real index): the hub's copy answered in 0.08 to 0.10 ms, and after one refresh it held all 7 stored rules from Elastic. It showed hold-short as 3-7-4 (candidate), because that is what the deployed index still says; the file now says 3-7-2. That difference is the point of rules as data: the hub follows the index, so the next `deploy_elastic.py` (or an edit in Elastic) changes what the card cites. Someone must decide between 3-7-2 and 3-7-4.

## 11. Does a one-word answer make the agent faster? Measured: no

Idea (Deekshith): have the agent answer with one word from a closed list (a verdict) and let a later step build the prose on it, so the model does less. Test (this sandbox, 2026-10-25, real Elastic project, `POST /api/agent_builder/converse`, a temporary tool-less agent that answers only MATCH, NOMATCH or UNSURE, deleted afterwards):

| Agent | Answer | Wall time per call |
| --- | --- | --- |
| `unstep-intercept-lite` (as deployed, JSON with a sentence) | about 40 tokens | 10.7, 10.1, 9.8 and 5.2 s |
| one-word agent, default connector | `MATCH` | 5.2, 9.9, 9.9 s, and 9.8, 10.1, 10.1, 9.9 s in the first run |
| one-word agent, Claude Sonnet 3.7 connector | `MATCH` | 10.1, 10.1, 4.8 s |
| one-word agent, Claude Sonnet 4.5 connector | `MATCH` | 10.1, 4.9, 10.1 s |

The time clusters at about 5 s and about 10 s whatever the answer length or the model, so the floor is not the model's output. It looks like the Agent Builder call itself (a fixed wait or poll), which also fits the tool-using Compliance agent stopping at exactly 10.02 to 10.03 s. This is 13 calls from one machine, so it is a strong hint, not a proven cause. The direct inference endpoints answered 403 for this key, so a call without Agent Builder could not be tested.

What follows: shrinking the agent's output or switching its model will not get an agent call to milliseconds. Keep agents off the path the pilot waits on (rules, the in-memory stored rules and the cache decide; the agent explains afterwards). A one-word verdict is still worth having for a different reason: a closed list makes the decision deterministic, cacheable and easy to test, and the explanation text can be filled in from a template. That is the rule catalog (`rules.json`) applied to the verdict.
