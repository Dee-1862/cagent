# Elastic and Moss: Where We Are, What Is Real, and What Next

A plan, not a build. Nothing in section 5 or 6 is started. It exists so Deekshith can explain to the Moss and Elastic judges why our use goes beyond "search" and "logging", without claiming more than we have run.

| Field | Value |
| --- | --- |
| Status | v0.2. Decided in R29 (2026-10-24): M-1, M-2, E-1, E-2, E-3 agreed and the not-now list agreed; M-3 and E-4 are not to be built before the demo. M-2, E-2 and E-3 are built and tested offline; M-1 and E-1 need keys (section 8) |
| Written by | Deekshith's side (agent), for review by Rishit's side |
| Related | [20-agent-map.md](20-agent-map.md), [16-sponsor-depth.md](16-sponsor-depth.md), [15-pilot-app-and-sponsor-plan.md](15-pilot-app-and-sponsor-plan.md), [10-agentic-architecture.md](10-agentic-architecture.md), [18-benchmark.md](18-benchmark.md) |

Step ids (M-1 to M-4, E-1 to E-4) belong to this plan. They are not the M1 to M6 and E1 to E3 items in docs/16 (for example docs/16's E3 is the CHANGE_POINT idea, which is still not now).

## 1. How Much Of This Is Verified

Our sandbox cannot reach Moss, Elastic or Cartesia, and elastic.co pages could not be fetched at all (the page fetch failed with a DNS error). So the evidence comes in three grades, and every row below says which one it rests on.

| Grade | Meaning | Used for |
| --- | --- | --- |
| SOURCE | Read in the installed packages: `moss` 1.21.0 (the newest version the package index shows) and its engine `inferedge-moss-core` 0.35.0 (docstrings and strings in the binary). Read, not run, because opening a session needs Moss credentials | Moss capabilities |
| SNIPPET | Seen in web search result summaries of Elastic's docs and blog, never on the page itself | Elastic capabilities |
| UNVERIFIED | Not found in either, or the sources disagree | Anything marked so. Do not say it on stage |

Not checked at all: the usemoss GitHub changelog and any Moss release newer than 1.21.0 (no access). If a newer release exists, this plan may be missing it.

## 2. The Honest Picture Today

**Moss is where we are strongest.** Each plane really has its own in-memory index that it writes to as it hears the radio, and acts on. Rishit measured six real sessions at once (0 to 1 ms searches, no cloud indexes created, R3) and a 0.6 ms hint search in a live run (R14). What is built beyond that has only run offline against our local stand-in.

**Elastic is where we are weakest.** It is the track a judge will most easily call "logging". Everything below has run only against mocks: the event store, the readback percolator, the ES|QL stats, the agents and workflows, the FAA loader. No cluster has seen any of it from our code. Rishit's laptop has no Elastic keys (R27), and our sandbox is blocked from the cluster.

Three things we should say more carefully than we do now:

| Claim in our docs | What the code does | Fix |
| --- | --- | --- |
| "Moss recovers hold short Runway 33 from the garbled fragment" (docs/16 moment 2, the Devpost draft, the social post) | The hint is chosen by the newest-clearance rule from a filter-only fetch. The fragment search runs beside it and is shown as evidence (agreed in R18 so a better-ranked old clearance can never win) | Say "Moss searches the plane's memory with what it heard, in 0.6 ms, and the result agrees with the hint", or make the search decide in a case where it is safe (step M-3 below; changes safety behaviour, so both humans) |
| "Elastic decides" | The percolator verdict is shown next to the slot check and does not change what happens. The agents may only add a citation or lower confidence. The workflow has a 6 s timeout and the local proposal is the fallback | Say "Elastic cross-checks and cites", not "decides" |
| Offline test results as evidence for search quality | The offline stand-in ranks by word overlap, not meaning, so passing tests do not show the semantic behaviour | Quote only live numbers for search quality |

One more rule slip to fix: `scripts/smoke_moss.py` pushes the `flight-N123AB` session to Moss Cloud unless `--no-push` is given. That is the per-aircraft push we agreed never to do. It should default to no push.

## 3. Moss

### 3.1 Capabilities, and what we use

Evidence grade in brackets.

| Capability | Vendor status | What we use today |
| --- | --- | --- |
| In-session index: `client.session(name)`, `add_docs`, `query`, local embeddings, about 1 to 10 ms, no cloud call [SOURCE] | Documented in the SDK | **Built, live-observed once.** One session per plane (248d276, `UNSTEP_MOSS_AIRCRAFT` default 6), every heard call and readback indexed as it arrives (0b62b64), one shared client for all planes and the monitor to fit Render's memory (abdf9ce, a997b01). The Frequency Monitor writes `freq-<frequency>` (248d276) |
| Hybrid search, `alpha` 0 to 1, `top_k`, metadata `filter` with `$eq $ne $gt $gte $lt $lte $in $nin $and $or` [SOURCE] | Documented | **Built.** Garbled-fragment search with `alpha` 0.5 (c9a4ffa, a34a9ca), "what did the tower tell me" with a `ts` filter (0b62b64). Numeric filters on string metadata were checked live in `scripts/smoke_moss.py` |
| `min_score`, `candidate_depth` query options [SOURCE] | Documented in the signature | **Not used.** We never set a score floor |
| `get_docs` with `sort_by`, `ascending`, `group_by`, `doc_ids`, `filter` [SOURCE: signature only] | Present | **Not used.** "Latest clearance" fetches everything and sorts in Python (`queries.py`, `hint.py`). Whether `sort_by` sorts numbers as numbers when metadata is stored as strings is UNVERIFIED |
| `ParentGrouping(parent_field, order_field)`: collapse sibling docs into one result per unit, ordered [SOURCE] | Present | **Not used** |
| `$near` filter operator [SOURCE: the operator name is in the engine; its value format and whether sessions accept it are UNVERIFIED] | Present | **Not used.** Our airport data has no coordinates per node and the scenario has one fixed GPS point, so this needs data work first |
| `push_index()` replaces the cloud index and returns a job; `session()` auto-loads an existing cloud index with the same name [SOURCE, docstrings] | Documented | **Built, offline only.** Flight log (22c2b68): one `flightlog-<frequency>` session, pushed once per flight end, per-aircraft sessions never pushed. The auto-load line suggests the flight log survives a hub restart, which settles the question we asked in D22; it needs one live check |
| `save_to_disk` / `load_from_disk` (snapshot a session, restore without a download) and `load_index(cache_path=...)` [SOURCE] | Documented | **Not used** |
| `query_multi_index`: global top-K across several loaded indexes with the same embedding model [SOURCE] | Documented. Needs `load_index`, so whether a live session can take part is UNVERIFIED | **Not used** |
| Custom embeddings: `QueryOptions(embedding=...)`, custom-model sessions keep their local vectors on push [SOURCE] | Documented | **Not used.** Would need aviation text to tune on |
| Moss Inference: OpenAI-shaped chat grounded in `indexes=[...]`, streaming, tool calls including an `McpServer` entry that Moss connects to and runs during the reply [SOURCE] | Documented | **Built (Rishit's side).** Translation of the private advisory with a digit-preservation check, about 165 ms to first token warm (d711e89, R18); answers may only quote records (`quoted_source`). The MCP tool entry is unused |
| Moss integrations for Pipecat (`pipecat-moss`, community maintained) and LiveKit (third-party listings only) [SNIPPET] | Claimed by Moss, not by Pipecat or LiveKit | **Not used.** Our voice path is our own websockets |
| Newer releases than 1.21.0 [UNVERIFIED] | Unknown | Unknown |

### 3.2 Proposed steps

Owner for all Moss steps: Deekshith's side builds, Rishit's side reviews (the split agreed in R4 and kept).

| Id | Step | Files touched | Offline test plan | Needs live | Effort | Risk |
| --- | --- | --- | --- | --- | --- | --- |
| M-1 | **Moss live proof script.** One script that, on real keys, does the whole loop and prints numbers: open a session, index heard calls, run the fragment search, run the "last minute" search, archive two flights into the flight log, push once, close the client, start a fresh one, check the flight log is back. Also fixes `smoke_moss.py` to default to no push | new `scripts/moss_live_check.py`, `scripts/smoke_moss.py` | Run the same script against `LocalMemory` and a fake push in a test, so the flow and the printed shape are covered | Moss keys (Rishit has them) | S | Low. Its value is that it turns BUILT into MEASURED |
| M-2 | **Use Moss's own sorting, grouping and score floor.** `get_docs(sort_by=ts)` for "newest clearance" instead of fetch-all and sort; `min_score` on the hint and "last minute" searches so a weak match says nothing instead of something; `group_by` on `(flight or event id, ts)` so "what was the whole exchange" returns one ordered unit | `unstep/cockpit/memory.py`, `queries.py`, `hint.py` (all three need the memory layer to expose the options; local stand-in must honour them too) | Local stand-in gets the same options; tests for ordering, the floor refusing a weak match, grouping order. Stand-in ranking is word overlap, so the floor value is tuned live, not offline | Moss keys, to tune the floor and confirm string-metadata sorting | M | Medium. Changes what the pilot hears when a match is weak, so it is a safety-relevant change: it only ever removes a hint, never adds one |
| M-3 | **Let the search decide, in the safe direction only.** When the newest-clearance rule gives no hint (clearance too old, or no restrictive guess) but the plane's session has a restrictive clearance the fragment matches above the floor, say so as a "Likely" hint with the source shown, never as a clearance. Today that case says nothing | `unstep/cockpit/hint.py` | Cases for stale clearance with a strong match, permissive match (must give nothing), other aircraft's clearance (must give nothing), superseded clearance (must give nothing) | Moss keys, to measure false hints | M | Higher. It adds a spoken hint in a new case. **Both humans must agree**, and the PRD hint rules (restrictive only, source shown, never a clearance, newest wins) must still hold. The simulator and eval give the false-hint rate before anyone turns it on |
| M-4 | **Position-aware memory with `$near`.** Give airport nodes coordinates and the plane a moving position; filter the plane's hold-short candidates by distance, so the answer to "which hold short?" depends on where the plane is | `unstep/cockpit/seed.py`, airport docs, `hint.py`, `scenario.py` | Spike first: does a session accept `$near` and what is the value format? Cannot be answered offline. If it works, a stand-in distance filter for tests | Moss keys for the spike | M, after a half-day spike | High. Format and session support UNVERIFIED, plus new airport data. Drop it if the spike fails |

### 3.3 The moment on stage, and its number

| Moment | Number | Needs |
| --- | --- | --- |
| **Restart the hub in front of the judges and the flight log is still there**: "14 flights restored from Moss Cloud in 310 ms" (M-1) | Flights restored, restore time in ms | One live run; supports the claim that Moss is the plane's memory beyond one session |
| **The plane's memory says no when it should**: a weak match speaks nothing, with "best match 0.31, below the 0.5 floor" on the console (M-2) | Score and floor shown, false hints per 100 calls in the simulator | Floor tuned live |
| **Where the plane is changes the answer** (M-4, only if the spike works) | Search ms with a distance filter | Spike |

### 3.4 Ranked top 3 for Moss

1. **M-1, live proof.** It converts three built features (sessions, "last minute", flight log) from tested offline to measured, and answers the restart question.
2. **M-2, native sort, group and score floor.** Makes the safety rule ("no source, no hint") enforceable by Moss's own score, not just by our code.
3. **M-3, search that decides, in the safe direction.** The one change that makes the Moss claim in our pitch literally true. It needs both humans and the false-hint rate first, so it can slip to after the demo without hurting anything.

M-4 (`$near`) is the most striking idea and the least certain; it is a spike, not a commitment.

### 3.5 Not now (Moss)

| Idea | Why not |
| --- | --- |
| `query_multi_index` across airport, flight log and plane | Needs indexes loaded the same way; a live session taking part is UNVERIFIED. Revisit after M-1 |
| Custom embeddings tuned on ATC text | Needs data we do not have. The recorded dataset could feed this later |
| `save_to_disk` for restarts | The cloud auto-load covers it. Useful offline-first, not needed for the demo |
| Pipecat or LiveKit integration | Our voice path is custom; adopting either is a rewrite |
| Indexing the FAA order in Moss | Elastic owns that job (E-2); duplicating it dilutes both stories |
| Moss Inference calling Elastic's MCP tool | See section 5.5: it sends an Elastic API key through Moss's servers |
| Web sources, `create_index_from_files` | Not part of the product |

## 4. What We Can Truthfully Say To Moss

Tags: **BUILT** (code exists and passes offline tests), **TESTED OFFLINE** (against our local stand-in only), **NEEDS LIVE RUN** (not run on real Moss from our code, or not re-measured), **PLANNED** (only in this plan). A claim can carry two tags.

| Say this | Tag | Note |
| --- | --- | --- |
| "Every plane gets its own Moss session and indexes every call it hears the moment it is transcribed, on the plane, with no cloud round trip." | BUILT, TESTED OFFLINE | Six real sessions were run by Rishit (R3) |
| "Searching that memory takes about a millisecond." | BUILT, NEEDS LIVE RUN | 0 to 1 ms over six sessions (R3), 0.6 ms in a live hint (R14). Re-measure before the pitch |
| "A pilot can ask what the tower told them in the last minute and Moss answers from the plane's own session, with the search time on screen." | BUILT, TESTED OFFLINE, NEEDS LIVE RUN | Search quality needs a live check (the stand-in ranks by word overlap) |
| "When a call is stepped on, the plane searches its memory with the garbled fragment it heard and shows what Moss found next to the hint." | BUILT, NEEDS LIVE RUN | Do not say Moss recovers the instruction: the hint comes from the newest clearance (section 2) |
| "A hint only ever says stop or wait, and an old clearance can never come back ahead of a newer one." | BUILT, TESTED OFFLINE | That is our rule, not a Moss feature |
| "When a flight ends the plane's memory is archived to one Moss Cloud flight log, and we never push a session per aircraft." | BUILT, TESTED OFFLINE, NEEDS LIVE RUN | Fakes only. The restart claim needs M-1 |
| "The flight log survives a restart." | NEEDS LIVE RUN | Rests on a docstring (auto-load of an existing index). Do not say it before M-1 |
| "Moss Inference translates the private advisory, kept only if every number survives, about 165 ms to first token." | BUILT | Rishit's side, measured live (R18) |
| "A weak match says nothing instead of guessing." | PLANNED | M-2. Today there is no score floor |
| "The answer depends on where the plane is." | PLANNED | M-4, a spike |

Never say: "Moss decides what the pilot hears", "Moss recovers the lost words" (the words come from the controller's own transmission), or any search-quality number from an offline test.

## 5. Elastic

### 5.1 Capabilities, and what we use

Evidence is SNIPPET unless stated. Elastic's own pages could not be fetched, so read each cited page before relying on a row.

| Capability | Vendor status | What we use today |
| --- | --- | --- |
| Index and search, `_bulk` | Standard | **Built.** Every gateway message stored as one document with promoted fields (`sink.py`). This is the "logging" a judge will see first. **Never run on a cluster by us** |
| Percolator: store queries, run documents against them | Standard | **Built, tested with a mock** (453c396). Each approved directive is stored as a query, each readback percolated. Result shown beside the slot check; it changes nothing yet |
| ES\|QL `_query` with `FROM ... WHERE ... STATS ... BY` | Standard | **Built, tested with a mock** (6938288). `/live/stats` runs two queries and joins them by `event_id` in Python |
| ES\|QL `LOOKUP JOIN` | Reworked in 9.2 with multi-field joins; still labelled preview on the command reference | **Not used.** It would replace our Python join of readbacks to events |
| ES\|QL `CHANGE_POINT` | Listed in the processing commands, platinum license, preview in 8.19 docs [license and status need checking on the page] | **Not used.** R18: not now |
| ES\|QL `TS` command | Introduced in 9.2; the sources disagree on version [UNVERIFIED] | **Not used** |
| Agent Builder: custom tools (`esql`, `index_search`), agents, `converse` API [SNIPPET, GA announced] | `POST /api/agent_builder/tools` and `/agents`, converse with an `agent_id` | **Built, never deployed** (a57af8c): 3 tools, 3 agents, deploy script |
| Agent Builder MCP server at `{KIBANA_URL}/api/agent_builder/mcp`, API-key auth, GA from 9.3 [SNIPPET] | Documented | **Not used** |
| Agent Builder A2A (expose agents to other frameworks) [SNIPPET] | Announced | **Not used** |
| Workflows: `ai.agent`, `waitForInput`, manual trigger by API (`POST /api/workflows/workflow/{id}/run`), bulk create, resume endpoints, added in 9.4 [SNIPPET plus Elastic's public example repo] | Documented | **Built, never deployed** (a57af8c): two workflows, the hub client with a 6 s timeout. `waitForInput` deliberately not used (the gateway is the human gate) |
| `semantic_text` field, hybrid search, reranking | Standard | **Built, never run** (bb721f6): `scripts/ingest_faa.py` creates `unstep-faa` with a `semantic_text` field. Reranking not used. Whether the cluster has a default inference endpoint is unchecked |
| Streams, external MCP (preview), other 2026 releases [UNVERIFIED] | Unknown | **Not used** |

### 5.2 Why the current Elastic story is thin, and what would make it real

A judge who reads our repo finds an event store plus two features that have never run. To go beyond "logging" the plan needs three things Elastic does that a plain log store does not: it **matches** (the percolator turns each instruction into a query), it **cites** (hybrid search over the FAA order), and it **answers questions over the audit trail** (ES|QL tools behind an agent). Only the first two are built, and none has run.

### 5.3 Proposed steps

**Owner, as decided in R29: Deekshith's side keeps the Elastic track and Rishit's side reviews.** This reverses the split first proposed here (Rishit's side owning it end to end): Deekshith has the Elastic keys, so live deploys and measurements happen where they can run. Rishit's side still writes queries and definitions on request. Rishit's laptop has no Elastic keys (R27); definitions, query text, mocks and tests need none.

| Id | Step | Files touched | Offline test plan | Needs live | Effort | Risk |
| --- | --- | --- | --- | --- | --- | --- |
| E-1 | **One real Elastic loop on a live cluster.** Run `check_elastic.py`, then `deploy_elastic.py`, `ingest_faa.py` (with the FAA chapters downloaded), turn on `UNSTEP_ELASTIC_AGENTS=1`, make one blocked call, and read the result. Fix whatever the first contact with a real cluster breaks (request shapes, the inference endpoint, workflow YAML, the output path `steps.<name>.output.message`) | `elastic/**`, `scripts/deploy_elastic.py`, `scripts/ingest_faa.py`, `unstep/ground/elastic_agents.py` | Existing mocked tests keep passing; every fix adds a test that pins the real response shape that was seen | **Yes: this is the live step.** Elastic keys, Kibana URL, FAA chapters | M to L (unknown unknowns) | **High.** Nothing has touched a real cluster. Budget for iteration. Fallback is already in code: the local proposal after 6 s |
| E-2 | **"Ask the audit trail".** A box on the controller console. The question goes to an Agent Builder agent whose tools are ES\|QL over the audit data (blocked calls per plane, readback outcomes, congestion), using `LOOKUP JOIN` instead of our Python join. The answer shows the ES\|QL that ran | new agent and tools in `elastic/`, `GET/POST /live/ask-audit` in `unstep/live/app.py`, a console box in `web/live/atc/` | Mock the converse API; test that the endpoint never blocks the radio path, times out cleanly, and shows the query | Elastic keys; an LLM connector on the cluster | M | Medium. LLM latency (keep it off the radio path), `LOOKUP JOIN` still preview. If it is not ready the box stays hidden |
| E-3 | **Audit and benchmark live in Elastic.** Create the `unstep-eval` and `unstep-sim-events` indexes with explicit mappings, a Kibana dashboard over events, evaluation runs and simulated runs with a "simulated" filter, and the "Simulated traffic" badge on the stats panel from `simulated_runs` | `unstep/gateway/sink.py`, `scripts/eval_bench.py` (`store`), `unstep/ground/stats.py`, `web/live/atc/atc.js`, a dashboard export in `elastic/` | Mock Elastic as today; test the badge logic and mappings | Elastic keys | S to M | Low to medium |
| E-4 | **Percolator as a second opinion that can escalate.** If the percolator and the slot check disagree on a readback, ask the pilot to say again and tell the controller, instead of only showing the disagreement | `unstep/ground/percolate.py`, `unstep/gateway/server.py`, `unstep/cockpit/edge.py` | Disagreement cases in both directions; must never make a wrong readback pass | Elastic keys for the real disagreement rate | M | Higher. Changes safety behaviour and adds Elastic to the readback path. **Both humans must agree** |

### 5.4 The moment on stage, and its number

| Moment | Number | Needs |
| --- | --- | --- |
| **The decision card cites the rule**: after a stepped-on call the controller sees "FAA JO 7110.65 paragraph X" found by the Compliance agent from the FAA index (E-1) | Workflow time in ms, paragraph checked against the index | Live E-1 |
| **The controller asks the audit trail a question in plain English and sees the ES\|QL that answered it** (E-2) | Answer time, rows scanned | Live E-2, LLM connector |
| **The benchmark is in Elastic**: "500 simulated calls, 91.7% detected, filter by simulated" on a dashboard (E-3) | The dashboard's own counts | Live E-3 |

### 5.5 Ranked top 3 for Elastic

1. **E-1, one real loop.** Without it nothing else on this page counts, and every Elastic claim in our drafts stays "not run".
2. **E-3, audit and benchmark in Elastic.** Cheap, safe, and it makes the Elastic panel show real, labelled data, with the simulated badge the labelling rule asks for.
3. **E-2, ask the audit trail.** The clearest "more than logging" moment, but it depends on E-1 and a model on the cluster, so it is third.

E-4 is good engineering and a safety change; it waits for both humans.

### 5.6 Not now (Elastic)

| Idea | Why not |
| --- | --- |
| `CHANGE_POINT` "congestion spike" | R18: not now. Needs a platinum license (SNIPPET, check) and traffic worth detecting |
| `waitForInput` in the workflow | The gateway enforces the human decision; a second pause adds a path to the same gate |
| A2A exposure of our agents, external MCP | No consumer for them |
| Reranking the FAA search | A few hundred paragraphs: hybrid search is enough. Add if citations are poor in E-1 |
| Streams, `TS` command | Not needed for the data we have |
| Elastic on the radio path | Latency. The workflow stays off the live path with a local fallback |
| Moss Inference calling Elastic's MCP endpoint (a neat cross-sponsor bridge: Moss's `McpServer` tool pointing at Agent Builder's MCP) | Moss's servers would connect to our Kibana with an Elastic API key in the headers, which hands a secret to a third party, and it needs a public Kibana URL. Revisit with a read-only key and both humans |

## 6. What We Can Truthfully Say To Elastic

| Say this | Tag | Note |
| --- | --- | --- |
| "Every message through the system is stored in Elastic with fields promoted for ES\|QL." | BUILT, TESTED OFFLINE, NEEDS LIVE RUN | Mock transport only |
| "Each approved instruction becomes a stored percolator query, and each readback is run against it. We show Elastic's verdict beside our own check." | BUILT, TESTED OFFLINE, NEEDS LIVE RUN | The verdict is advisory today. Do not say it decides |
| "The console's safety panel runs ES\|QL on the audit data and shows the query." | BUILT, TESTED OFFLINE, NEEDS LIVE RUN | |
| "Intercept, Compliance and Readback Auditor are Agent Builder agents run by Elastic Workflows." | BUILT (definitions and client), NEEDS LIVE RUN | Never deployed. Say "defined and tested against mocks" until E-1 |
| "The agents never write the instruction. They can add an FAA citation, checked against the index, and can only lower confidence. If Elastic is slow the local proposal is used." | BUILT, TESTED OFFLINE | That is our safety design, true by test |
| "A rule citation from the FAA order appears on the decision card." | NEEDS LIVE RUN | Needs E-1: the order loaded and the agent run |
| "Hybrid semantic search over FAA JO 7110.65." | BUILT (loader), NEEDS LIVE RUN | No FAA text has been loaded |
| "Our benchmark results are stored in Elastic and queryable." | BUILT, TESTED OFFLINE, NEEDS LIVE RUN | `--store` exists; simulated runs are labelled |
| "The controller can ask the audit trail questions." | PLANNED | E-2 |
| "Elastic makes the safety decision in real time." | Do not say | It does not |

Honest framing for the judges: Elastic is our audit and rules layer, deliberately off the radio path so a slow or unreachable cluster can never delay a pilot's instruction; we can show what each piece does once E-1 has run.

## 7. Proposed Split, and What Needs A Yes

This is a proposal for both humans (Rishit and Deekshith), because it changes who owns what (docs/04-work-split.md).

| Item | Proposal | Yes needed from |
| --- | --- | --- |
| Elastic track ownership | **Decided (R29):** Deekshith's side owns it, Rishit's side reviews. Deekshith had asked for it to go to Rishit's side; applied as written for now, Deekshith can still decide otherwise | Deekshith |
| Moss track ownership | **Decided (R29):** stays with Deekshith's side, Rishit's side reviews | done |
| Elastic keys for Rishit | Not needed now that Deekshith owns Elastic | n/a |
| M-3 and E-4 | **Decided (R29): not before the demo.** M-3: the newest-clearance rule stays and Moss's search stays evidence; it needs a measured false-hint rate first. E-4: a percolator disagreement is flagged on the console for the controller to decide, never an automatic say again | done |
| Wording fixes in section 2 | **Done** (docs/12, 15, 16, 17 and the social post): "Moss searches the plane's own memory; the newest clearance gives the hint" and "Elastic checks and remembers" | done |
| `smoke_moss.py` default to no push | **Done**: it pushes only with `--push` | done |

Order as agreed: M-1 and E-1 first, in parallel, since both are live proofs and blocked only on keys; then M-2, E-3, E-2 (built offline already, section 8). M-3 and E-4 are off. M-4 only after a spike.

## 8. Built Offline, And The Exact Steps For The Live Runs

### 8.1 What was built from this plan, all tested with fakes and mocks

| Step | Built | What was checked offline | What only a live run can show |
| --- | --- | --- | --- |
| M-2 | Ordering, grouping and our own score floor in `unstep/cockpit/memory.py`; "what was the whole exchange" answer; floor on the hint's search evidence only (the hint rule is unchanged) | 7 tests, including a fake Moss session that refuses `sort_by` | The right floor value (`UNSTEP_MOSS_MIN_SCORE`, placeholder 0.25) and whether Moss's own sort and grouping behave (step M-1, part 3). Moss documents `min_score` for loaded indexes, not session queries, so the floor is ours |
| E-3 | `unstep-eval` and `unstep-sim-events` indexes with explicit mappings, run summaries stored with flat headline numbers (`kind` benchmark or simulation, simulated runs labelled), Kibana data views in the deploy script, `UNSTEP_STATS_INCLUDE_SIMULATED=1` so the console's "Simulated traffic" badge lights | Mocked Elastic: document shape against the strict mapping, fake runs never stored, real stats exclude simulated records, dry-run lists every request | The data view API path (the deploy script treats a failure as a warning), the dashboard itself (built by hand in Kibana, section 8.3), real mappings accepted |
| E-2 | Agent `unstep-audit` and four read-only ES\|QL tools (blocked per callsign, readback outcomes, blocked per minute, auto-resends), `POST /live/ask-audit`, a console box that shows the ES\|QL that answered | Mocked converse API: tolerant parsing, timeouts, limits, route off without Elastic; headless browser check of the box | The real converse response shape (the parser guesses from search summaries; pin it with a test after the first live answer), the agent's answers, ES\|QL syntax and `BUCKET` on the cluster |
| M-1 follow-ups | Each plane's flight session is warmed at join (one empty fetch and one tiny search, `MossMemory.warm`); a Moss client that cannot be created falls back to local memory; a failed flight-log push records its reason and the status line shows it | 3 tests with fakes | Whether warming brings the first hint from about 783 ms (live, R31) down to the warm 0.2 to 0.4 ms |
| MM1 | Per-plane on-board snapshots: `save_to_disk` after a clearance, readback or advisory (background, at most once a second, failures only log), `load_from_disk` in `CockpitEdge.start` before seeding with no duplicate seed documents, then warm; a JSON equivalent in `LocalMemory`; `moss_live_check.py` part 5 | `tests/test_moss_disk.py` (11 tests): debounce, load before seed, a failed save, a missing or damaged file, the dry run, a fake Moss session receiving the SDK calls | Real `save_to_disk` / `load_from_disk` on a real session: doc count, load ms, and that "what was my last clearance?" answers after a restart (part 5, with keys). Whether a process can open a session with the Moss service unreachable: `client.session()` contacts Moss, so only "on board, from disk, no cloud index" is claimed |

`LOOKUP JOIN` is not used: the command reference still labelled it preview, and the four tools need only `STATS`, `BUCKET` and `CASE`.

### 8.2 M-1: Moss live proof (needs MOSS_PROJECT_ID and MOSS_PROJECT_KEY; Rishit's laptop has them)

1. `pip install -r requirements.txt`, check `.env` has the two Moss keys.
2. `python scripts/moss_live_check.py --dry-run` (no network): the flow must end with `ok`.
3. `python scripts/moss_live_check.py`. It prints, in order:
   - part 1, three fragments with score, floor and search ms: choose `UNSTEP_MOSS_MIN_SCORE` between the unrelated fragment's score and the garbled ones;
   - part 2, the "last minute" and "whole exchange" answers with their ms;
   - part 3, whether Moss's own `sort_by` is numeric and what `group_by` returns (diagnostics, never failures);
   - part 4, the test flight log `flightlog-check-<time>`: two flights, one push, then a brand new client and how many docs came back and how fast. That is the restart claim.
4. The test index is deleted at the end (`--keep` keeps it). It never touches `flightlog-<frequency>` or any `flight-*` index.
5. Known blocker (R31): part 4 failed on Rishit's Moss project with `The project's usage limit has been reached; billing must be updated`. Moss Inference still worked. Run part 4 on a project with room for a cloud index; the hub now shows this reason in the flight log status instead of looking healthy.
6. Paste the whole output to Rishit's side or the main session. Until the part 4 line shows the docs back after a fresh client, do not say the flight log survives a restart.

### 8.3 E-1: one real Elastic loop (needs the Elastic keys, so Deekshith's machine)

1. `.env`: `ELASTIC_CLOUD_URL`, `ELASTIC_API_KEY`, and `KIBANA_URL` if it can't be derived (the Kibana address replaces ".es." with ".kb."). `python scripts/check_elastic.py` must say Elasticsearch and Kibana both answer. The API key needs Kibana application privileges for Agent Builder and Workflows as well as index privileges.
2. `python scripts/deploy_elastic.py --dry-run`, read it, then `python scripts/deploy_elastic.py`. Expect `ok` for five indexes, `ok` or `warn` for the three data views, `ok` for seven tools, four agents and the two workflows. Paste any `FAIL` line with its status and body: the first contact with a real cluster is where request shapes get fixed. Re-run with `--replace` to update existing tools and agents.
3. FAA text: save the chapter pages you need from the FAA's JO 7110.65 page into `data/faa/` as `.html`, then `python scripts/ingest_faa.py --source data/faa --dry-run`, then without `--dry-run`. Check with `curl -s -H "Authorization: ApiKey $ELASTIC_API_KEY" "$ELASTIC_CLOUD_URL/unstep-faa/_count"`. If `semantic_text` is rejected for lack of a default inference endpoint, set `UNSTEP_FAA_INFERENCE_ID` to one that exists and re-run.
4. Start the hub live: `UNSTEP_ELASTIC_AGENTS=1 UNSTEP_STATS_INCLUDE_SIMULATED=1 python -m unstep.live --host 0.0.0.0 --https`. Open `/live/atc/`, make one stepped-on call. Expected: the safety panel says "Elastic ES|QL", the decision card shows an FAA paragraph (checked against `unstep-faa`), the trace step shows the workflow time. If the workflow does not answer within `UNSTEP_AGENTS_WAIT_S` (6 s) the log says so and the local proposal is used; that is the fallback working, not the loop working.
5. Ask the audit trail: the box appears under the safety panel when Kibana is configured. Ask "Which plane was blocked most in the last hour?". Then capture the raw response once and paste it back so the parser can be pinned: `curl -s -X POST -H "Authorization: ApiKey $ELASTIC_API_KEY" -H "kbn-xsrf: true" -H "content-type: application/json" "$KIBANA_URL/api/agent_builder/converse" -d '{"input":"Which plane was blocked most in the last hour?","agent_id":"unstep-audit"}'`.
6. Audit and benchmark in Elastic: `python scripts/simulate_traffic.py --sessions 4 --calls 25 --elastic`, `python scripts/eval_bench.py --live --n 40 --store`. In Kibana, Discover on the `unstep-sim-events` and `unstep-eval` data views; build a dashboard from them by hand (a saved dashboard export was not written because its format could not be checked here). Filter benchmark runs on `kind`, and keep simulated runs separate with `simulated: true`.
7. What to paste back: every `FAIL` or `warn` line from step 2, the first workflow output (Kibana, Workflows, execution view), the raw converse JSON from step 5, and the safety panel's source line.
