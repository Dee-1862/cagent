# Changes

A running log of changes to the Unstep project. Newest entries go at the top.

## Agent Builder depth: scheduled workflows, a coach agent, a trend tool, an MCP client

- New: tool `unstep_trend_decisions` (approved and rejected per day, 30 days, real traffic), agent `unstep-coach` (reads the trend, says "not enough data" under 5 days or 20 decisions, never claims the system learns), workflow `unstep-nightly-review` (scheduled daily, saves to the new `unstep-reviews` index, created by `deploy_elastic.py`).
- `unstep-briefing` also runs every 8 hours. Scheduled workflows spend model calls on their own once deployed.
- `scripts/mcp_demo.py`: list and call tools through Agent Builder's MCP server.
- Not done: the agent-calls-workflow tool (`elastic/proposed/`, API body unverified, not deployed) and per-agent API keys (not checked; the hub makes all calls with one key, so enforced separation would need hub changes).
- None of this is deployed or run live. Deploying uses `--replace`, which needs Rishit's OK.


## Compliance cache off by default; a stand-in map for geography (D51)

- `UNSTEP_COMPLIANCE_CACHE_S` now defaults to 0. Real questions differ, and a cache hit skips the agent, so it would not credit Elastic. The agents stay on the slow path and are justified against the human baselines (docs/26).
- `unstep/ground/geo.py`: named points mirroring the console's ground graph, lat/lon from a stand-in scale, nearest point, distance to a hold-short line. Every sentence is labelled "demo map, not surveyed". Not yet wired into the agents: that needs the plane's position, which waits on Rishit's answer to D51.


## Cross-domain human baselines, and the flight log survives a restart in the cloud

- `assets/human_baselines.json`: added the controller speech rate (6.1 syllables per second, Nitta, Okazaki and Klinger 2011), a driving reaction time to unexpected events (Green 2000, abstract only), conversational speech rate (196 wpm) and typing rate (51.56 wpm). Say-again (about 5.6 s) and speaking a clearance (about 2.1 s) are now DERIVED, not modelled. The explain row is a cross-domain bracket (about 70 s typed, about 18 s spoken), labelled as not a controller figure.
- `docs/26`: table and source list updated. Unstep speaks a clearance about 40% slower than a median controller; the doc says so.
- Moss: MM1 no longer saves the shared `flightlog-<freq>` session to disk (plane sessions only). Before, a restart opened the flight log empty and the next push would have replaced the cloud copy. The live check now waits for the push's build job; result: 2 docs back after a fresh client, 1467 ms. Test added in `tests/test_moss_disk.py`.


























## Human baselines checked against the full sources; two overclaims corrected

- Read in full: the NASA 2022 readback paper (average 0.639 s), the FAA CAMI 2005 report (1.16%, the alerting sentence, an average transmission of 2568 ms of voice) and the AIN 2025 hearing article ("There's nothing," Clark Allen). `assets/human_baselines.json` now records the full reference and how far each was checked; the 5.85 s say-again time and 250 ms per word say plainly they have no citation; a hearback claim supported only by search snippets was dropped.
- Corrected: "nothing alerts anyone" (docs/12) and "nothing tells the pilot or the controller" (docs/18) overstated CAMI, which found that a completely blocked call usually raises an audible alarm and the controller repeats it (94.74%); the gap is stepped-on and clipped calls.

## Agents against human ATC, job by job

- New `docs/26-agents-vs-humans.md`, `assets/human_baselines.json` (each human figure marked SOURCED, MODELLED or NOT MEASURED, with its source) and `scripts/task_latency_report.py` (offline measurements plus `--live` for Cartesia speech). It compares six jobs separately and claims a win only where there is a human figure to compare against. Faster: noticing a stepped-on call, checking a readback, recovering a lost instruction (mostly the human approving). No human figure: the rule lookup. Not a win: speaking a clearance (3.9 s for 10 words against a modelled 2.5 s; speed 1.5 trims about 8% and mishears a word) and the model-written explanation (5 to 12 s).

## Moss billing cause found, and a one-word agent test

- The Moss "usage limit" is the Developer plan's **Indexes per Project: 3** (Deekshith's billing screenshot: $13.37 of $105 credit used, so credit is not the problem). The project already holds exactly three indexes (airport-KUNS, flight-N123AB, freq-118.300), so any new cloud index is refused. The earlier note that it was "not our index count" was wrong. Freeing a slot (the two old test indexes) or upgrading fixes it; not yet done.
- Tested live whether a one-word agent answer is faster: no. Agent calls took about 5 s or about 10 s whatever the output length or connector (docs/25 section 11). Agents stay off the path the pilot waits on.

## A one-line record of each flight in Elastic when it ends (R49)

- When a flight is archived (a pilot lands, a seat is freed, the hub stops), a summary with counts only is written to a new `unstep-flights` index: callsign, frequency, why it ended, how many calls it heard, how many were stepped on, readbacks, clearances, advisories. Best effort and off the landing path: a slow or failing Elastic never holds a seat. The words stay in the plane's own flight log. `UNSTEP_FLIGHT_SUMMARIES=0` turns it off.
- New read-only audit tool `unstep_audit_landed_flights` on the `unstep-audit` agent, so "which flights ended in the last hour and how many calls did each miss?" can be asked. The deploy script creates the index. Redeploy with `--replace` to update the agent. Tested with fakes; not yet run live.
- Not recorded: when the pilot joined, and how many readbacks were right or wrong (the archived documents do not carry them).

## The hub answers rules from memory, refreshed from Elastic

- `rule_for` no longer calls Elastic on each instruction: it answers from an in-memory copy of the stored rules in microseconds (0.08 to 0.10 ms live) and refreshes the copy from the `unstep-rules` index in the background (`UNSTEP_RULES_SYNC_S`, default 30). Elastic's own percolate time was 1 ms but the wall time was about 75 ms, almost all network, so a per-instruction call was the slow part. A rule edited in Elastic reaches the hub within the interval, with no deploy; a failed refresh keeps the rules the hub already has. `UNSTEP_RULES_WAIT_S` is gone.
- Seen live: after a refresh the hub held the 7 stored rules, with hold-short as 3-7-4 from the deployed index while `rules.json` says 3-7-2. A person has to settle which paragraph governs.

## Live demo-mic test fixed, rule catalog compiler, and live numbers

- `tests/test_demo_mic.py`: two tests failed since the day they were added. The helper `speak()` polled `mic.waiting` for False, but with instant fakes the scene asks the next prompt in the same event-loop pass, so it never saw it drop and waited forever for a prompt it had already missed (it only passed where timers are slow, such as Windows). It now counts prompts. All six pass, with and without a Cartesia key.
- New `scripts/compile_rule_catalog.py` (read-only): runs the hybrid search with a reranker for each instruction type and lists candidate FAA paragraphs for a person to review. Measured live: about 700 ms per search, so it stays out of the live path. `rules.json` now has three title-matching candidates (line up and wait 3-9-4, takeoff 3-9-10, landing 3-10-5), still unreviewed; hold-short stays on 3-7-2 with a note that the search prefers 3-7-4.
- Pronunciation dictionary round trip run live with the existing `unstep-atc-v2`: `fower`, `juliett` and `NOTAM` were heard worse with it (docs/24).

## Planes start in parallel, and a snapshot race fixed

- `LiveRoom.start` starts every plane at once instead of one after another. Opening a Moss session contacts Moss, and a real test here took 6.3 s for six sessions one after another against 3.2 s all at once (about 2 times, not 6 times; the cause of the gap is not known). The sessions stay open for the life of the hub, so a restore is the only per-plane cost afterwards.
- Snapshot writes are now serialized per plane and shielded from cancellation. Stopping a plane cancels the pending save, but the write already running in its thread kept going and could finish after the final one, leaving the older snapshot on disk (Rishit saw 3 documents instead of 4 on Windows). A test with a slow earlier write fails without the change and passes with it. This is a plausible cause, not a confirmed one on his machine.

## Faster agents: Intercept only when the local match is unsure, and a Compliance answer cache

- `UNSTEP_INTERCEPT=auto` (default) asks the slow Intercept agent only when the hub's own match is not already high confidence; `always` and `never` also work. For a high-confidence call the agent step is compliance-lite alone (5.7 to 7.1 s live).
- A Compliance answer is reused for the same instruction against the same paragraph (`UNSTEP_COMPLIANCE_CACHE_S`, default 3600, 0 = off): a repeat starts no workflow. Both are tested with fakes; the timing effect is not yet measured live.
- `docs/25-latency-ideas.md` sections 8 and 9: the research-based ideas (cascades, semantic caching, speculative decoding, prompt compression) with what fits and what does not, and the first live Cartesia and Moss numbers taken from this sandbox (Moss restore 0.5 to 0.9 ms, opening the session 260 to 340 ms; Cartesia first audio about 130 ms; turns endpoint median caption gap 374 ms against 793 ms).
- Known: `tests/test_demo_mic.py` (two tests) still fails with the network open, and also fails on the commit before the Cartesia work, so it is not a regression from it. Not yet diagnosed.

## Vercel builds only when `app/` changes

- Vercel's free plan stopped new builds ("Deployment rate limited, retry in 24 hours") after we pushed many commits, each of which built a preview, including mail-only and Python-only ones. `ignoreCommand` in `vercel.json` and `app/vercel.json` now skips a build when the commit changed nothing under `app/` (exit 0 means skip; a missing parent commit makes git fail, which builds as before). The site that is up now is the last successful build; the limit lifts after the 24 hours. Not tested on Vercel from here.

## Restart to answer, timed

- `moss_live_check.py` part 5 also prints "restart to answer": the time from opening a restarted session to the answer to "what was my last clearance?" (open, restore, seed what is missing, ask).

## Where the on-board restore time goes

- `moss_live_check.py` part 5 restores three times and prints cold and warm times with a breakdown (`open_ms`, `load_from_disk_ms`), so the 45 ms live number can be split into a one-off start-up cost and a per-restore cost. `docs/25-latency-ideas.md` section 7 records what is and is not claimed (no "only Moss").

## Parallel agents are now the default (live: 12.2 s against 23.4 and 33.8 s)

- Rishit's live runs (R47): the original two-agent workflow took 23.4 s and 33.8 s, the parallel pair 12.2 s, the one-agent version 16.2 s; the tool-using Compliance agent is capped at 10.0 s while compliance-lite takes 5.7 s. `UNSTEP_BLOCKED_WORKFLOW` now defaults to `parallel`; the original is still available by name.
- Intercept-lite instructions shortened (a match flag and a sentence under 20 words), since Intercept is now the slow branch. Redeploy with `--replace` to push it; untested live.
- Rule lookup measured live: Elastic `took` 2.0 ms at 7 rules and 1.0 ms at 100, 1,000 and 5,000 (wall about 75 ms from the laptop). Hold-short now points at 3-7-2 (candidate), per Rishit's reading of the FAA text.
- The audit record names the workflow that actually ran.
## Cartesia: one live-check command, 429 evidence logging, and drafts for the shared files

- **`scripts/cartesia_live_check.py`**: the whole live-access to-do list of docs/24 in one command for a laptop that can reach Cartesia. It reuses `caption_probe.py` (manual and turns endpoints) and `cartesia_repro.py` (turns fast versus paced), times Sonic first audio, round-trips every entry of `assets/pronunciation/atc.json` through TTS then STT with and without the dictionary, and probes for a 429 with 1 to N sockets (default 4, never above 6). PASS, FAIL and INFO lines, JSON in `data/cartesia-live/`. `--dry-run` uses fakes and passes offline; without `CARTESIA_API_KEY` it prints "skipped" and exits 0; every socket is closed and a leftover socket fails the run. Tests: `tests/test_cartesia_live_check.py`. Not yet run against the real API.
- **429 evidence**: `unstep/cockpit/cartesia_errors.py` now logs every 429 (handshake or error event, TTS or STT) with status, response body (500 characters at most, key and Bearer tokens removed, never headers) and the number of sockets this process holds. `CartesiaTTS`, `CartesiaManualSTT` and `CartesiaTurnSTT` keep that count. `CartesiaRateLimited` carries `status`, `body` and `open_sockets`. A STT error event with status 429 now raises it too. `scripts/eval_bench.py` keeps every 429 in `rate_limits` in its result and prints the first. This settles "plan limit or our leak" the next time one happens; nothing about the cause is claimed yet.
- **Drafts, not applied**: `docs/cartesia-docs09-corrections.patch.md` (exact wording for the two stale lines in docs/09, Rishit's file) and `docs/cartesia-settle-caption-proposal.md` (the diff to wire `settle_caption` into `room.py`, a shared file, plus a test; checked on a scratch copy only).
- docs/24 to-do list now points at the command and says what each result settles.
- Unverified: the real 429 body, the plan tier of our key, the script's behaviour against the live API.

## Watchers: Tracking and Flow merged, and an Open-call watcher added

- The Tracking watcher (stuck key, repeated stepped-on aircraft) and the Flow watcher (busy frequency) are one **Frequency watcher**: they were all about who is blocking whom.
- New **Open-call watcher**: a stepped-on call with no decision after 15 s is flagged ("they may have missed part of the instruction") and clears when it is approved or rejected. It watches the core job, a lost instruction nobody has dealt with, which the other watchers did not. The 15 s is our own early warning.

## A freed seat deletes its on-board Moss copy

- The on-board snapshot (MM1) is deleted when a seat is freed (drop without `keep_snapshot`), so the next pilot who gets that callsign starts clean and never inherits the last pilot's clearances. A hub stop keeps it, because that plane is still flying and the point is that it restarts with its memory. Test added.
## Watchers connected to the live room (off by default)

- `UNSTEP_WATCHERS=1` starts the four watchers in the room: every gateway message goes to `team.feed`, key down and up to `team.note`, and their rows go to the console's feed (atc and observer). Off by default, so nothing changes until it is switched on; an unmet expectation (a demo pilot who never reads back) would otherwise show amber rows.
- Three small additions to `room.py`; agreed by Rishit's side (R46). The readback wait is `UNSTEP_READBACK_WAIT_S` (default 20; the QR demo uses 45).

## Four watchers side by side (module only)

- New `unstep/monitor/`: a Readback watcher, Runway watcher, Tracking watcher and Flow watcher, each with its own queue, timers and notices, posting `agent_action` rows in the agreed format. Fixed rules, microsecond answers, thresholds are our own early warnings. One failing watcher does not stop the others. `open_items()` feeds the shift briefing.
- Not yet connected to the live room: that needs three small additions to `room.py` (posted to Rishit's side first).

## Parallel agents: Intercept and Compliance as two workflows started together

- New `unstep-blocked-intercept` and `unstep-blocked-compliance` workflows with tool-less agents `unstep-intercept-lite` and `unstep-compliance-lite`. With `UNSTEP_BLOCKED_WORKFLOW=parallel` the hub starts both at once and waits for the slower one; each writes its own document so neither overwrites the other, and one missing half does not lose the other. Each branch's time goes into the audit record. Default stays the two-agent workflow that has run live; none of the new pieces has run live.

## Rules as data: the FAA rule for an instruction by stored query, in milliseconds

- Each rule is stored in Elastic (`unstep-rules`) as a percolator query, the same mechanism that checks readbacks. The hub percolates the proposed instruction and puts the matching rule on the card at once, with Elastic's own time, falling back to the same rules in process if Elastic is slow (`UNSTEP_RULES_WAIT_S`, 0.3 s) or down, and to the hybrid search when no rule matches.
- Rules live in `elastic/rules/rules.json` with a review status. Only `hold-short` has a paragraph, as a candidate (cited live by the agent, not yet read against the FAA text); the card says "Candidate rule, not yet reviewed" until a person marks it reviewed.
- `scripts/rule_latency.py` compares a dictionary, an in-process scan and Elastic as the rule count grows; the local part is measured (scan 0.02 ms at 7 rules to 9.6 ms at 5,000), the Elastic part needs a live run. Filler rules are synthetic and labelled.
- `docs/25-latency-ideas.md` records what is fast and why, what is not claimed (not "only Elastic"; the paragraph is not signed off), and ideas not built.

## Search-first citation, a one-agent workflow and a briefing workflow

- Rishit's live timings (R42) show the Elastic workflow takes about 24 s (intercept 12.7 s, compliance 10.0 s, store 0.3 s), with compliance looking capped at 10 s.
- The hub now runs a hybrid search (keyword plus semantic, fused, then reranked with `.jina-reranker-v3`) of the FAA order before sending the card, and shows the closest paragraph with its score and time, labelled as a search result. `UNSTEP_RERANK_ID`, `UNSTEP_CITE_WAIT_S` (1.5 s).
- New opt-in workflow `unstep-blocked-call-fast` and tool-less agent `unstep-ground`: one agent call given the paragraph the search found (`UNSTEP_BLOCKED_WORKFLOW`). The default stays the two-agent workflow that has run live.
- New `unstep-briefing` workflow and `unstep-briefings` index (with a timestamp pipeline). None of the three has run against a live cluster yet.

## Cartesia findings, and a 429 backoff

- New `docs/24-cartesia-findings.md`: five graded findings (manual STT tail latency and handshakes, ink-2 final-text deltas with no word timestamps, HTTP 429 with several clients, the "niner" dictionary entry, the turns endpoint report). Several turned out to be documented behaviour or our own doing, and the doc says so. Items taken from Cartesia's docs came from search snippets and must be re-read before quoting.
- A Cartesia HTTP 429 on the WebSocket handshake is retried with backoff (TTS and STT) and then raised as `CartesiaRateLimited`; a TTS error event with status 429 raises the same class.
- `settle_caption` in `stt.py` holds back a possibly split last word until the utterance is final. Not wired into the room yet (shared file).

## The Elastic agents' citation no longer blocks the card (3a)

- The stepped-on call's proposal card goes out at once from the local check; the Elastic agents' FAA citation is added to the open card when the workflow answers (up to 30 s, `UNSTEP_AGENTS_LATE_S`). The instruction never changes; confidence can only go lower; the trace gets an `agents_cited` step.
- The one case that still waits for the agents is a proposal the policy might auto-relay (restrictive, high confidence), because Intercept can veto it. Without this, an auto-relay could happen before the veto.
- `docs/20-agent-map.md` section 6 maps Agent Builder's capabilities (workflows both ways, MCP and A2A, permissions, model selection, skills) to what we use, and says why the agents should not chat with each other on the critical path.

## Idle pilots land: stale planes free themselves

- A walk-up pilot who is still connected but has sent nothing for `UNSTEP_IDLE_LAND_S` (default 600 s; 0 turns it off) is treated as landed: the seat is freed the same way a gone phone is (flight archived to the flight log, pushed once, cockpit agent and open events closed). Pings do not count, so a forgotten open tab lands too. Team planes are never freed.
- The pilot app says "Your flight has landed after a quiet spell" when it was freed this way.
- Touches `room.py` (an activity stamp and a sweeper task); agreed by Rishit's side (R36, R38). A landing also posts a Monitor row (`agent_action`, kind rule) into the console's Agents at work feed.
- README known limitations corrected to match the live runs (Elastic and the agents are deployed, Moss sessions have run live, the turns-endpoint report is not reproduced).

## Moss connection checklist and an agent map

- A plane's flight session is warmed at join (`MossMemory.warm`), so the first hint in a live room is not the slow one (Rishit measured 783 ms against 0.2 to 0.4 ms warm; the effect of warming is still to be measured).
- A Moss client that fails at creation now falls back to local memory instead of stopping the room.
- A failed flight-log push records the Moss error text, and the flight log status line says why the cloud copy is behind (for example a project usage limit).
- New `docs/20-agent-map.md`: one sentence end to end, which agent reads what, the widened jobs agreed in R34, and the ideas not agreed (triage ranker, routing between people), each tagged built, measured or proposed.

## README: why stretched-thin towers need a safety net

- New README section with cited public figures (staffing shortfall, training time, the NTSB finding on combined positions at DCA, the 2024 rest rules), framed as a safety net for a short-staffed controller. It states that Unstep does not reduce staffing and that no effect has been measured. Replaces the earlier fewer-controllers framing, which clashed with humans-stay-in-charge.

## Audit answers repaired, deploy order hint (from Rishit's first live Elastic run)

- `ask-audit` answers that came back as UTF-8 read as cp1252 (an em dash shown as three odd characters) are repaired when parsed. The cause is not yet found; the repair is a guard.
- `deploy_elastic.py` says the FAA index must exist first and prints a hint when the FAA tool is rejected for that reason.
- Merged Rishit's aa03e70 (ES|QL tool params are strings) and 932c3e4 (decision card shows the Elastic agents' FAA citation).

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

## 2026-10-24: No more speech connection per line from cues, recovery lines or freed seats

**Type:** Fixed
**Area:** Audio

- Rishit's benchmark hit HTTP 429 from Cartesia because a connection was opened per line and never closed (R29), and asked us to check the hub. Main's 76428c0 fixed the typed-line and controller paths. Two of our own paths had the same fault: the spoken eyes-free cues and the tower's "was blocked" recovery line each built a fresh live voice per call. Both now use the shared controller voice.
- A walk-up plane's own cockpit voice connection was never closed when its seat was freed or the hub stopped. It is now (`_close_engine`), so seat churn at the demo can't pile up sockets.
- Checked: 2 tests (cues and recovery share one connection; a freed seat closes its cockpit engine). The 429 itself needs a live run with six phones to be sure.

**Related:** agent mail R29

## 2026-10-24: Audit trail and benchmark in Elastic, "ask the audit trail", and a Moss live check (E-3, E-2, M-1)

**Type:** Added
**Area:** Audit

- **E-3, audit and benchmark in Elastic:** explicit mappings for `unstep-eval` and `unstep-sim-events` (and the events index), created by `scripts/deploy_elastic.py` with Kibana data views for Discover and Lens (a failed data view is a warning, not a failed deploy). Each benchmark or simulation run is stored in `unstep-eval` as flat headline numbers plus its summary, with `kind` and `simulated` fields (`unstep/evaluation.py`, `eval_bench.py --store`, `simulate_traffic.py --elastic`). `UNSTEP_STATS_INCLUDE_SIMULATED=1` makes `/live/stats` include simulated runs so the console's "Simulated traffic" badge (Rishit's a4e2033) lights; real counts exclude them otherwise. The console was not passing `include_simulated`, so the badge could never have shown before.
- **E-2, ask the audit trail:** a read-only Agent Builder agent `unstep-audit` with four ES|QL tools over the real events index (blocked per callsign, readback outcomes, blocked per minute, auto-resends; `STATS`, `BUCKET` and `CASE` only, no preview commands), `POST /live/ask-audit` (timeout, length limit, one question at a time, never on the radio path, off without Elastic), and a box under the console's safety panel that shows the ES|QL that answered.
- **M-1, Moss live proof script:** `scripts/moss_live_check.py` prints the fragment-search scores to tune the floor, the "last minute" and "whole exchange" answers, whether Moss's own sort and grouping behave, and the flight log restart (two flights, one push, a brand new client, what came back). It uses a throwaway `flightlog-check-<time>` index and deletes it. `--dry-run` proves the script's own flow only.
- Checked offline: 14 new tests (mapping fit, labels, fake and simulated runs never mixed in, mocked converse API and its failures, the route, the agent and tools as definitions, the script's dry run) and a headless browser run of the console box with a stub agent. **Nothing here has touched a real cluster or real Moss.** Step-by-step live commands are in [19-elastic-moss-plan.md](19-elastic-moss-plan.md) section 8.

**Related:** [19-elastic-moss-plan.md](19-elastic-moss-plan.md), agent mail R29

## 2026-10-24: M-2: the memory layer orders, groups and floors results itself

**Type:** Changed
**Area:** Edge device

- **Ordering:** `memory.fetch(..., sort_by, ascending, limit)` orders by a metadata field with numbers as numbers (Moss stores metadata as strings, so "ts" would sort as text otherwise). The Moss backend also asks Moss to sort, falling back if it refuses, but our ordering is the authority because Moss's behaviour on string metadata is unverified. "Newest clearance" and the hint now fetch newest first through this.
- **Grouping:** `fetch(..., group_by=(parent_field, order_field))` returns one doc per unit in order. Done in our code too, because the shape of Moss's own `ParentGrouping` result is unverified. First use: a new pilot question, "what was the whole exchange?", answered as one ordered unit (what the plane heard, what Unstep said, what was approved, what the pilot read back) for the newest blocked call. Clearances, advisories, heard calls and readbacks now carry an `exchange` field (the blocked call's event id).
- **Score floor:** Moss documents `min_score` for loaded indexes, not for session queries, so the floor is ours (`UNSTEP_MOSS_MIN_SCORE`, default 0.25, a placeholder to tune on real Moss). It gates only the hint's search evidence: when the best match is below the floor the trace says "best match 0.31 is below the 0.25 floor, so no hit is shown". The hint rule is unchanged (newest clearance; Moss search is evidence), so this adds no new spoken hint.
- Checked: 7 tests (numeric ordering, grouping, floor, evidence below the floor, the exchange answer, a room run, and a fake Moss session that refuses `sort_by`). Live: the floor value and whether Moss's own sort and grouping behave need a run on real Moss (steps in [19-elastic-moss-plan.md](19-elastic-moss-plan.md)).

**Related:** [19-elastic-moss-plan.md](19-elastic-moss-plan.md) M-2, agent mail R29

## 2026-10-24: Claim wording made truthful, live latency numbers recorded, smoke test no longer pushes

**Type:** Docs
**Area:** Docs

- Applied the wording agreed with Rishit's side (R29) in docs/12, 15, 16 and 17 and the social post: "Moss searches the plane's own memory; the newest clearance gives the hint" (the search is evidence beside the hint, as approved in R23), and "Elastic checks and remembers" (the percolator is advisory; the gateway and the human decide). No remaining "Moss recovers" or "Elastic decides" in the docs outside the plan that explains the change.
- Rishit's live numbers (R28) are now recorded as measured live in docs/17 and docs/18: tower transcript final 155 ms after release (was 2702 ms), cockpit 172 ms (was 2875 ms), call end to the pilot hearing the fix 2.9 s including the human approval (was 6.1 s), first audio 201 ms. Still slow: about 1.0 s from call end to the cockpit flagging the lost call. docs/18 comes from `scripts/benchmark_report.py`, so the table is edited there.
- `scripts/smoke_moss.py` pushes nothing by default (it used to push the per-aircraft `flight-N123AB` session, breaking the agreed rule). Pass `--push` to push once on purpose.

**Related:** [19-elastic-moss-plan.md](19-elastic-moss-plan.md) section 2, agent mail R28, R29

## 2026-10-24: Faster-feeling live captions, a Cartesia probe, and a leak fix

**Type:** Changed
**Area:** Audio

- Pilot app: new words of each Cartesia update fade in one after another (a whole burst within 240 ms), a caret follows the word being spoken, holding the button on a live hub shows "Listening..." at once, waiting text shows within 50 ms (was up to 250), and microphone audio goes to the hub every 50 ms from 1024-sample buffers (was 100 ms from 2048). Words are only ever shown after Cartesia returns them.
- `scripts/caption_probe.py`: streams a clip to Cartesia's manual and turns endpoints at real-time pace and reports updates while speaking, time to first text and the gap between updates. Needs a run where Cartesia is reachable; it decides whether the next item helps.
- `UNSTEP_CAPTION_SOURCE=turns` (default `manual`): also streams the audio to the turns endpoint and shows its `turn.update` text as captions, display only; the final text still comes from the manual stream. Tested with fakes only; not measured against Cartesia yet.
- Fix: the hub opened a new, never-closed Cartesia speech connection for every typed line and every controller prompt, which ends in HTTP 429 with several walk-up planes (Rishit's benchmark hit it). Typed lines now share one connection per voice, the controller prompts share one, and all close when the hub stops.
- Tests no longer read real Elastic or Moss keys from the shell or `.env` (set `UNSTEP_LIVE_ELASTIC=1` for the opt-in live test).

**Related:** [Live Demo](11-live-demo.md), [Sponsor Depth](16-sponsor-depth.md)

## 2026-10-24: Plan for how Elastic and Moss are used, and who owns what (proposal)

**Type:** Docs
**Area:** Docs

- [19-elastic-moss-plan.md](19-elastic-moss-plan.md): an honest inventory of what we use from each sponsor against what each offers, with evidence grades. Moss claims were read in the installed `moss` 1.21.0 and `inferedge-moss-core` 0.35.0 (read, not run); Elastic claims come from search result summaries because elastic.co pages could not be fetched, so they are marked as such.
- Per sponsor: ranked top 3 steps with owner, files, offline test plan, live needs, effort, risk and the stage moment with its number; a "not now" list; and a talk track where every claim is tagged BUILT, TESTED OFFLINE, NEEDS LIVE RUN or PLANNED.
- Findings worth acting on, all docs-only or tiny: our "Moss recovers the instruction" wording is stronger than the code (the hint comes from the newest-clearance rule; the search is evidence); "Elastic decides" is stronger than the code (the percolator is advisory); `scripts/smoke_moss.py` pushes a per-aircraft session by default; and the Moss SDK says `session()` auto-loads an existing cloud index, which may mean the flight log survives a restart (needs one live check).
- Proposes that Rishit's side owns the Elastic track end to end and ours keeps Moss. Nothing is built from the plan; it waits for a yes from both humans.

**Related:** agent mail D23

## 2026-10-24: Plane memory saved to Moss Cloud through one flight log

**Type:** Added
**Area:** Edge device

- When a flight ends (a walk-up seat is freed, the presenter resets the room, or the hub stops), the plane's session docs are copied into one shared session, `flightlog-<frequency>` (writer "archive"). Each doc carries `callsign`, `flight_id`, `ended_at` and `kind`. The flight log is then pushed to Moss Cloud once, in the background (one push per end event, never on the radio path).
- **Failures and memory:** a failed push stays local and is retried at the next end. The plane's session is dropped from the shared client, so its memory is freed (`drop()` added to both memory backends, and `MossMemory.push` now returns the SDK's push result for the log).
- **The agreed rule still holds:** per-aircraft sessions are never pushed; the flight log is the only session we push besides the airport index.
- **Limitation:** a push replaces the cloud index, and the session holds the flights since the hub started, so a hub restart starts a new log. Loading the old index back first depends on the Moss SDK (check).
- **Search:** `GET /live/flightlog?q=&callsign=&since_ms=` searches past flights and returns the status ("Flight log: N flights saved to Moss Cloud"), which also goes to every seat as a `flightlog` message.
- Checked: 4 tests with a fake shared client (copy on end, a single push, session dropped, no per-aircraft push, retry after a failed push, the route). The live push needs Moss keys.

**Related:** [16-sponsor-depth.md](16-sponsor-depth.md) M6, agent mail R3, R4

## 2026-10-25: Each plane's Moss memory is saved on board and restored from disk (MM1)

**Type:** Added
**Area:** Edge device

- `MossMemory` saves a plane's flight session with the SDK's `SessionIndex.save_to_disk(cache_path)` under `data/moss/` (gitignored; `UNSTEP_MOSS_DISK` names another folder or `off`). A save follows a new clearance, readback or advisory, at most once per second per plane, as a background task off the radio path; a failed save only logs. `CockpitEdge.start` calls `load_from_disk` before seeding when a snapshot exists, seeds only the documents that are missing, then warms. `stop` flushes the last save.
- `LocalMemory(disk_dir=...)` does the same with a JSON file, so tests and offline runs behave the same (off unless a folder is given).
- `scripts/moss_live_check.py` part 5 saves, drops and restores a session from disk and asks "what was my last clearance?", printing doc count and load ms. `--dry-run` uses the local stand-in. Tests: `tests/test_moss_disk.py`, with fakes.
- Limit: this is memory on board, from disk, with no index download. Opening a Moss session object still contacts Moss to check credentials, so a start with the service unreachable is not shown here.

**Related:** docs/23-moss-max.md (MM1), docs/19-elastic-moss-plan.md section 8.1

---

## 2026-10-24: Benchmark report against the status quo and published work

**Type:** Docs
**Area:** Docs

- [18-benchmark.md](18-benchmark.md), written by `scripts/benchmark_report.py` (docs/17 is the Devpost draft). Simulated traffic, synthetic speech, recorded sessions and ATCO2 each get their own heading; simulated numbers are only under "Simulated traffic (n=...)".
- **Status quo** is 0% automatic detection, with the sources already in our research (FAA CAMI 1.16% and "no alerting system", SKYbrary, the NTSB quote).
- **Simulated traffic** (500 calls, 157 stepped on), each with a Wilson 95% interval: 91.7% of step-ons detected by the audio detector, 0 false events on 343 clean calls, recovered instruction correct in 144 of 144, restrictive instruction delivered in 91 of 97. The report says these run on exact text and measure the pipeline's logic, not speech recognition.
- **Timing:** a modelled "say again" exchange (assumptions labelled) is set against Unstep's measured 6.1 s before the on-air fix and its offline-model 0.43 s after, with the live number left as [confirm live].
- **Still to run:** the speech, HAAWAII comparison, ATCO2 and recorded-session sections list the commands to run.

**Related:** agent mail D20, D21

## 2026-10-24: Traffic simulator, labelled simulated, and a fix it found

**Type:** Added
**Area:** Other

- `scripts/simulate_traffic.py`: scripted synthetic traffic through the real room code (offline voice, local memory).
  - **What it simulates:** several planes, restrictive and permissive instructions, step-ons at a set rate, a simulated controller deciding, and readbacks that are wrong on purpose at a set rate. The seed is fixed. Calls are back-dated so 500 calls run in about 10 minutes: counts and rates are meaningful, timings are not.
  - **Labelling:** every call row and every gateway record carries `simulated: true` and the `run_id`. With `--elastic`, records go to their own `unstep-sim-events` index, never the real events index.
- `/live/stats?include_simulated=1` adds that index and returns `simulated_runs`, so the console can show a "Simulated traffic" badge (asked from Rishit's side). Real stats never include simulated records unless asked.
- **Fixed, found by the simulator:** Rishit's cockpit voice now passes `speed` and `language` to the TTS engine (d711e89). The live room's TTS wrappers (`SerialTTS`, `StreamingTTS`) didn't accept them, so every wrong-readback correction crashed in the live room. They now pass the options through.
- Checked: 4 simulator and report tests, 1 test for the voice options, and a 500-call run with no errors (summary feeds docs/18).

**Related:** agent mail D20, D21

## 2026-10-24: Recording-session mode: a real dataset of us talking over each other

**Type:** Added
**Area:** Audio

- To record a real dataset in about an hour, the presenter opens `/live/record/`, names the session and the tower speaker, ticks consent and starts recording (controller seat only).
  - **Who is recorded:** pilots type a first name and tick "My voice is recorded for the Unstep dataset" when they join. Only people who ticked it are recorded.
  - **What is saved:** every push-to-talk becomes a 16 kHz WAV in `data/recordings/<session>/` (gitignored) with a manifest row: speaker, prompted line and its kind, live transcript, key times, overlaps from key timing, readback target, QC. Every stepped-on cluster is saved as the mix a cockpit heard, with its overlap windows.
- **Prompter (`unstep/live/recording.py`):** everyone sees their next line above the talk button, and the tower reads its lines on the record page. Pilot lines include some readbacks that are wrong on purpose. Every third tower call cues one plane: "Talk NOW, over the tower".
- **QC:** clips under 0.3 s are dropped; clipping and near silence are flagged. Live counts show on the record page and the phones.
- **Export:** `scripts/export_recordings.py` writes a datasets-style folder (train/test split by speaker, mixes, `DATASET_CARD.md` crediting the recorders by name; the licence is the recorders' decision, default "for evaluation only").
- **Evaluation:** `scripts/eval_unstep.py --recordings <folder>` scores the real set: WER against the prompted lines, callsign and runway agreement, readback precision and recall, and the audio-only overlap detector against key-timing ground truth.
- Checked: 3 tests (recorder, consent and key-timing overlaps in a room run, export plus eval). A headless browser run took a real fake-mic clip from join with consent through the prompter to the manifest. Vitest and build pass. Steps are in [15-pilot-app-and-sponsor-plan.md](15-pilot-app-and-sponsor-plan.md) section 6a.

**Related:** agent mail D21

## 2026-10-24: Devpost draft: lines we can prove filled in

**Type:** Docs
**Area:** Docs

- [17-devpost.md](17-devpost.md) (handed over by Rishit's side, R27 item 4): added live captions and the waveform, walk-up seats, transcribing while on air, word alignment, the benchmark harness, the ATCO2 loader and the test counts, each traceable to a commit. New numbers that need a live run are marked [confirm live]. The social post no longer calls stepped-on calls a "collision".

**Related:** agent mail R27 item 4

## 2026-10-24: Console fixes taken over from Rishit's side (R27)

**Type:** Fixed
**Area:** Other

- The Elastic readback step printed raw floats ("local, 0.07650000043213367 ms"); the room now rounds that time to 2 decimals.
- The hint step's sponsor read "Moss / local (backend unreported)". The room now puts the plane's memory backend on the hint step (`data.backend`) and the console names "Moss" only when the event says so, otherwise "Local memory". Rishit's side was going quiet, so this console change was ours by agreement (R27 item 4).
- Checked: 1 new room test; console tests pass.

**Related:** agent mail R27 items 3b and 4

## 2026-10-24: Transcribe while the call is on air, not after it (R27 3a)

**Type:** Changed
**Area:** Audio

- Rishit's live video: the tower transcript was final 2.7 s and the cockpit's 2.9 s after release, and the call end to the pilot hearing the fix took 6.1 s. The audio went to Cartesia only after the transmission, and Cartesia then needs time to work through it before `finalize` can answer.
- **Tower:** a typed tower line now streams to the tower transcriber at real-time pace from the moment it goes on air (push-to-talk already did, P3), so it is final about 100 ms after it ends.
- **Cockpits:** new `LiveMix` (`unstep/live/radio.py`) sums the transmissions as their audio arrives (typed lines at once, push-to-talk frame by frame), with the same receiver model as the cluster mix (half-gain voices plus a beat tone where two are keyed). Every cockpit's STT is fed from it during the call and finalized when the cluster ends; the overlap detector still runs on the full cluster mix. If the live mix also holds a newer call, or a stream fails, the old after-the-call path runs (W3 fast send).
- Offline model (Cartesia working at 1.5 times real time from when audio arrives, finalize 100 ms after catching up), one stepped-on call: tower final 2766 to 141 ms after release, cockpit 4810 to 101 ms, call end to proposal 5135 to 426 ms. The live number needs a run with keys.
- Checked: 3 new tests (live mix against the cluster mix, before and after on the model, a mix holding a newer call falls back).

**Related:** agent mail R27 item 3a

## 2026-10-24: Benchmark under radio conditions, with 95% intervals

**Type:** Added
**Area:** Audio

- The first eval (40 clean lines, Cartesia TTS heard by Cartesia STT, one voice, no noise) was circular and small. `scripts/eval_bench.py` adds:
  - **Radio conditions:** every line through our VHF voice channel at several noise levels (clean, radio, radio-20, radio-10, radio-5 dB SNR), with the room's three Cartesia voices round robin.
  - **Key terms A/B** on radio-10.
  - **Readbacks:** labelled wrong and right readbacks checked through radio-10.
  - **Stepped-on mixes:** made the way the live room mixes a cluster, scoring the cockpit's audio-only overlap detector (recall at IoU 0.5 or more, latency to the first active frame, false alarms on clean lines) and STT on the damaged audio.
  - **Real speech (optional):** the ATCO2 1-hour test set from Hugging Face. It only runs after `--atco2-licence-ok`, once the dataset card's licence has been read; its audio stays local.
- Every accuracy has a Wilson 95% interval, WER a bootstrap 95% interval, latency p50 and p95. Helpers are in `unstep/evaluation.py`. `--store` indexes the run summary in `unstep-eval` when Elastic is configured.
- `--fake` runs the harness with tone "speech" and a scripted STT; its output is marked fake, says its numbers mean nothing, and is never stored.
- Checked: 6 tests. No real numbers yet: Rishit's side runs `--live`.

**Related:** agent mail D20

## 2026-10-24: Pilot app redesign: one hold button that becomes a voice memo, and a lyrics-style caption card

**Type:** Changed
**Area:** Other

- Deekshith's design (reference: iOS Voice Memos and Spotify lyrics). The flying screen is now only a small header (plane, callsign, connection dot), the big HOLD TO TALK button and a caption card. Tap-to-say lines, Ask Unstep, timings and log moved behind one quiet "More" link (still needed for no-mic fallback and debugging).
- Hold to talk: the button turns in place into a Voice Memos style panel: dark, a time ruler (00:02, 00:04 ...), rounded warm orange bars from the live mic level scrolling right to left, a red playhead with dots at 60 percent, a dotted line ahead, elapsed time in the corner. Bars turn red while someone else is keyed (talked over). Release turns it back after the usual tail.
- Caption card (warm mustard, big bold white text): one line per transmission from the hub's `caption` messages, the current line bright and earlier ones dimmed, auto-scrolling. A line's text changes at most once per second; the final caption replaces the interim at once. Keywords are underlined, not coloured. Others' calls are prefixed ("Tower:", "Plane B:"); Unstep's private advisory shows as a calm "Only you" line in plain wording ("three", not "tree", without the spoken "Advisory."); a step-on adds a "Talked over" line. The label under the card shows "Cartesia live caption · N ms behind your voice" (or "TTS timing" for typed lines).
- "More" also has a multi-lane radio waveform (`Waveform.tsx`) from the hub's `level` and `caption` messages. Reduced motion is respected everywhere. Earcons, join, clock sync, streamed mic frames and language are unchanged.
- Checked: vitest (lines, throttling, readable advisories, waveform state; 25 pass), the app build, and a headless phone (390x844, fake mic) on the offline hub: idle, holding while another station keys (red bars), captions mid-line and after; no page errors.

**Related:** [16-sponsor-depth.md](16-sponsor-depth.md) C2, agent mail D17, D19

## 2026-10-24: Live captions use Cartesia's streamed text as checked live

**Type:** Changed
**Area:** Audio

- Rishit checked the real ink-2 manual endpoint (R26, 626a26b): no interim messages, but final-text deltas about every 0.5 to 0.7 s while audio streams, which can split a word. `CartesiaManualSTT(on_text=callback(delta, so_far))` now exposes them. The room sets `on_text` before the socket opens and captions show the whole utterance so far, never raw deltas; `TowerStream` passes it to its ink-2 stream.
- The caption tagger reads runway numbers as ink-2 writes them ("runway thirty three", "thirty-three").
- Checked: tests with a fake STT that streams deltas like Cartesia's.

**Related:** agent mail R26

## 2026-10-24: Live captions and waveform levels from the hub

**Type:** Added
**Area:** Audio

- To show how fast Cartesia is, every seat now gets `caption {station, id, text, final, source, lag_ms, words: [{text, kind, at_ms}], ts}` while someone talks: interim text while the key is held (`source: "stt"`, `lag_ms` = hub now minus the hub time of the end of the audio sent so far), the final text at release, and for typed lines each word at its spoken time from the TTS word timestamps (`source: "tts"`).
- `level {station, id, t_ms, step_ms: 50, rms: [...]}`: one loudness value per 50 ms of the audio already arriving (push-to-talk frames, or the TTS audio of a typed line), for a scrolling waveform. Numbers only, no audio; neither message goes to Elastic.
- `unstep/live/captions.py` tags words as callsign, action, runway or taxiway, for spoken and written forms ("Cessna one two three", "Runway 28L", "via Bravo", "cross runway two niner").
- Interim results need an `on_partial` callback in Rishit's `CartesiaManualSTT` (asked in D17); until then the room sets it and STT classes without it simply send no partials. `TowerStream` passes it to its ink-2 stream.
- Checked: 3 tagger tests and 2 room tests with a fake STT that emits partials.

**Related:** agent mail D17

## 2026-10-24: Recorder for a live-room demo video (R24)

**Type:** Added
**Area:** Other

- `scripts/record_live_video.py` starts the hub, opens one 1920x1080 page with the ATC console and two pilot phones (Plane A, Plane B) side by side, and drives only real clicks: auto-resend off, the tower's hold short while Plane B talks, TALKED OVER, Approve and send, "From Tower" on Plane A, the correct readback, the recovery line for Plane B, then the waterfall and Elastic panel. Each step must appear within 15 s or the run stops naming the step.
- Sound: the room's audio arrives over the socket, so a socket probe logs each clip's time in every frame and the same ffmpeg muxing as `record_demo_video.py` places it. Radio clips heard in several frames are kept once; streamed advisory chunks are joined.
- Checked here: the hub starts offline and serves the console and the pilot app; 2 tests for the layout and audio placement. The browser part can't run in our sandbox; Rishit's side runs it live.

**Related:** agent mail R24

## 2026-10-24: Render blueprint ready for going live, with a checklist

**Type:** Changed
**Area:** Other

- `render.yaml` now lists `UNSTEP_GATEWAY_TOKEN` (required once `UNSTEP_OFFLINE` is removed), `CARTESIA_PRONUNCIATION_DICT_ID` (the new `unstep-atc-v2` id with the niner fix) and `UNSTEP_ELASTIC_AGENTS`, all filled in the dashboard.
- [15-pilot-app-and-sponsor-plan.md](15-pilot-app-and-sponsor-plan.md) section 2: "Going live on Render", the steps only Deekshith can do in the Render and Vercel dashboards, the plan choice, and that pitch latency numbers come from laptop runs only.

**Related:** agent mail R25

## 2026-10-24: The Moss search step says why no hint came out

**Type:** Fixed
**Area:** Edge device

- Rishit's review of M3 (R23): the search runs before the age check, so the console could show "Moss searched... top hit X" followed by no hint, as if the hit were ignored. The evidence now carries `no_hint` (clearance too old, no restrictive instruction to guess, or runway not at this airport) and the trace step ends with "No hint: ...".
- Checked: 1 new test (stale clearance).

**Related:** agent mail R23

## 2026-10-24: Cartesia feedback: the "niner" respelling lesson

**Type:** Docs
**Area:** Audio

- [09-cartesia-feedback.md](09-cartesia-feedback.md) new section: our own pronunciation entry `niner -> NY-ner` made Sonic say "N-one-er" and broke ink-2 on every runway with a 9. Found by the TTS to STT eval; before and after numbers (runway 0.852 to 1.0, readback precision 0.882 to 1.0). Mild request to Cartesia: document the respelling format or validate entries.
- Action for Deekshith: upload the new dictionary (`python scripts/upload_pronunciation_dict.py --name unstep-atc-v2`) and set `CARTESIA_PRONUNCIATION_DICT_ID` to the printed id.

**Related:** agent mail R22

## 2026-10-24: Seats for walk-up pilots: freed when the phone is gone, presenter reset, full-room answer

**Type:** Added
**Area:** Other

- Judges may scan the console QR and become planes (R22). A walk-up plane's seat is now freed when its phone has been gone for 20 s: its key and stream end, open events for it are marked "cancelled" (nothing was sent), its cockpit agent stops, and it leaves `/live/stations`, so the plane goes back to the fleet. The team planes (N123AB, H456) are never freed.
- Presenter reset: the controller seat sends `{type: "reset"}`; every walk-up seat is freed (its phone gets `seat_freed` and is closed), traces, radio log, insights, reports and the key log are cleared, every seat gets `room_reset`, and `/live/stats` counts only from the reset.
- A full room answers "All 6 planes are taken. Watch on the projector." with `full: true`; the pilot app shows it as a message, not an error.
- Checked: 3 tests (freeing after a disconnect, reset only from the controller seat, full room through the real route); vitest and build pass.

**Related:** agent mail R22

## 2026-10-24: First live evaluation numbers, and per-line rows in the eval output

**Type:** Docs
**Area:** Audio

- Rishit ran `scripts/eval_unstep.py --live --n 40` on real Cartesia (R21): callsign 0.95, action 1.0, runway 0.852, readback-error precision 0.882 and recall 1.0, finalize p50 598.5 ms and p95 1514 ms. Recorded in [16-sponsor-depth.md](16-sponsor-depth.md) section 7 with Rishit's Moss numbers (0 to 1 ms over six sessions, no cloud indexes, Inference first token about 165 ms warm).
- The script now writes one row per line (`text, heard, callsign_ok, runway_ok, action_ok, flagged, labelled, reason`, plus audio length in live runs) and prints every miss, so runway misses can be turned into key terms or pronunciation fixes.

**Related:** agent mail R21

## 2026-10-24: STT finalize time per hop on the live trace (S1)

**Type:** Added
**Area:** Audit

- Two new trace timings so the console waterfall shows where speech-to-text time goes: `cockpit_stt_final` (the cockpit's own finalize on what it heard, from its `cockpit_stt` audit) and `tower_stt_final` (the tower's words final, ms after key release when streamed, or after the clip was sent on the fallback path).
- Checked: 1 room test covering both.

**Related:** [15-pilot-app-and-sponsor-plan.md](15-pilot-app-and-sponsor-plan.md) section 4, agent mail R14, D13

## 2026-10-24: Loader for FAA JO 7110.65 into Elastic (W2)

**Type:** Added
**Area:** Ground agents

- `scripts/ingest_faa.py` splits the Order's chapter pages (HTML or text downloaded from faa.gov; we don't ship the text) into one document per numbered paragraph and indexes them into `unstep-faa` with id = paragraph number, `text` as `semantic_text` for hybrid search and `body` for BM25. `--dry-run` shows what it found. `UNSTEP_FAA_INFERENCE_ID` pins the inference endpoint.
- The Compliance agent's `unstep_faa_search` tool searches this index, and the hub keeps a citation only if `unstep-faa/_doc/<paragraph>` exists (B5).
- Checked: 3 tests on a made-up fixture page. Needs Deekshith to download the chapters and run it against the cluster.

**Related:** [10-agentic-architecture.md](10-agentic-architecture.md) 4.4, agent mail R10 (W2)

## 2026-10-24: Eyes-free cues use the agreed wording and never talk over the pilot (C2)

**Type:** Changed
**Area:** Other

- Earcons now follow Rishit's side's wording (R20): two rising notes to join, a click on air, a low double buzz when busy, two clashing notes when you were talked over, one soft clash for others, a rising note for a correct readback, two falling notes for a wrong one, falling and rising tones for the link, a low note when the mic is off.
- Short spoken lines ("You are Plane A.", "Frequency busy.", "You were talked over.", "Back online.", "Tap a line to talk.") are spoken by the hub in Unstep's own voice, left ear only (`cue_audio`). The hub only speaks these fixed phrases; readback cues are not spoken because the cockpit already says them.
- Cues wait while the pilot's own key is down or an advisory is still playing, then play in order.
- Checked: 5 vitest tests (including the queue rule) and 1 room test (fixed phrases, left ear only); build passes. Not tried on a phone with AirPods yet.

**Related:** agent mail R20

## 2026-10-24: Evaluation script for speech and readback checks

**Type:** Added
**Area:** Audio

- `scripts/eval_unstep.py` (agreed in R19): a seeded synthetic set of instruction and readback pairs built from the fleet's callsigns and FAA-style phraseology, about 30 percent of readbacks carrying one labelled error (runway digit, callsign, action, missing callsign). No public ATC corpus is bundled.
- `--dry-run` scores the checkers on the exact words (the baseline: all 1.0); `--live` speaks every line with Cartesia TTS and transcribes it with Cartesia STT (ink-2 with key terms, sent fast), then scores callsign, action and runway accuracy, readback-error precision and recall, and STT finalize p50 and p95; `--sessions` summarises latency per stage and readback outcomes from a live-session event log. Results go to `data/eval/` (gitignored).
- Rishit's side runs `--live` where Cartesia is reachable; numbers go into docs/09 and the pitch only after that run.
- Checked: 5 tests with fake speech.

**Related:** [16-sponsor-depth.md](16-sponsor-depth.md) section 8, agent mail R19

## 2026-10-24: Eyes-free pilot mode: every screen cue also has an earcon (C2, placeholders)

**Type:** Added
**Area:** Other

- In the demo the pilot wears AirPods and doesn't look at the phone. `app/src/cues.ts` plays a short tone pattern in the left ear (Unstep's side; the radio plays in both ears) for: joined, frequency busy when you press, your call stepped on, others stepped on, readback correct, readback wrong, link lost and back, mic off. Rising means good, falling means bad, repeated means urgent; each is under 400 ms.
- The tones are placeholders until Rishit's side sends the earcon wording (D12 item 3). Not yet tested with AirPods: the AirPods mic may switch Bluetooth to call mode and break left-ear-only, which needs a real phone.
- Checked: 3 vitest tests (lengths, rising/falling, readback cue only on a status change); build passes.

**Related:** [16-sponsor-depth.md](16-sponsor-depth.md) C2, agent mail R18, D12

## 2026-10-24: Console data for each private advisory: waited, spoke, overlapped (C5)

**Type:** Added
**Area:** Audio

- After every private advisory the room sends `advisory_report {station, id, waited_ms, spoke_ms, overlapped_ms, overlapped_by, cancelled, ts}` to the ATC console, the observer and that pilot. `waited_ms` is how long the cockpit held it for a gap (Rishit's held/released audits), `spoke_ms` the chime plus speech, `overlapped_ms` how much of it ran while anyone was keyed on the frequency (should be 0: the voice is cut when someone keys).
- The room now keeps a short log of key presses for this. Drawing is Rishit's side.
- Checked: 2 tests (numbers from a scripted key overlap, and a real room run).

**Related:** [16-sponsor-depth.md](16-sponsor-depth.md) C5, agent mail R18

## 2026-10-24: A pilot whose call was stepped on is told to say again (C1, blocked caller)

**Type:** Added
**Area:** Edge device

- Merged Rishit's `CockpitEdge.notify_blocked()` (ab2f1db: busy hold, directives go first) and the "From Tower" prefix on directives (eca04b0).
- The room now calls `notify_blocked` for every aircraft whose own transmission was in a stepped-on overlap ("Your last call was blocked. Say again."), skipping anything older than 30 s, and audits each as stage `recovery`.
- Intercept agent wording fixed after Rishit's review: the stepped-on call is usually the controller's call to the pilot.
- [16-sponsor-depth.md](16-sponsor-depth.md) updated with R19's decisions.
- Checked: 1 new room test with fake edges.

**Related:** agent mail R19

## 2026-10-24: The controller hears who stepped on them (C1, tower side)

**Type:** Added
**Area:** Ground agents

- A controller who was transmitting never hears the call that stepped on them. After a stepped-on cluster, the room now tells the tower seat, in Unstep's own voice: "Advisory. Helicopter 4-5-6 was blocked: request transition." The words come from the blocked pilot's typed line or streamed transcript; with none, "Ask them to say again".
- Sent only to the `atc` seat as `recovery {to, from_station, kind: "blocked_caller", priority, text, tx_id, ts, audio}`, waits for the controller to stop talking (up to 10 s), and is dropped if older than 30 s. Each one is also an `AuditRecord` (stage `recovery`, with `delivered_ms`).
- No contract change. The ATC console needs to play `recovery.audio` (Rishit's side). The blocked caller's own notice waits for Rishit's answer on the cockpit entry point.
- Checked: 2 room tests (delivered to the controller only, with audio and an audit; stale ones dropped). Offline voice only.

**Related:** [16-sponsor-depth.md](16-sponsor-depth.md) C1, agent mail R18, D11 item 3

## 2026-10-24: Moss searches the plane's memory with what the cockpit heard (M3)

**Type:** Added
**Area:** Edge device

- The garbled fragment the cockpit heard (Rishit's live run: "Cessna 123, short runway 30") now runs as a hybrid Moss search (`alpha` 0.5) over this plane's own clearances, offline, in the same call that builds the hint (`unstep/cockpit/hint.py`).
- The safety rule is unchanged (agreed in R18): the hint still comes from the newest clearance, so a better-ranked older clearance can never revive. The search is evidence: query, top hit, score, search ms and whether it agrees with the newest clearance.
- The cockpit sends it as an `AuditRecord` (stage `hint_search`); the live trace shows "Moss searched this plane's session for ...: top hit ... (score ...), in ... ms" and a `moss_search` timing for the console.
- Checked: 4 tests (garbled fragment finds the taxi clearance, an older better match never wins, failures keep the hint path safe, full room run shows the step). Local memory only; not run against live Moss.

**Related:** [16-sponsor-depth.md](16-sponsor-depth.md) M3, agent mail R18

## 2026-10-24: Sponsor depth plan agreed

**Type:** Docs
**Area:** Docs

- [16-sponsor-depth.md](16-sponsor-depth.md): one real moment per sponsor with a measured number on the console, each item labelled built (with commit), agreed or proposed. The three demo moments picked with Rishit's side (R18): three-way recovery (Cartesia), Moss recovering the instruction from the garbled fragment, Elastic agents citing the FAA paragraph.

**Related:** agent mail D10, R18

## 2026-10-24: Pilots pick a language for Unstep's private repeat when they join

**Type:** Added
**Area:** Other

- Rishit's cockpit now repeats approved directives in the pilot's language after the English (d711e89; Spanish, Hindi, French, only if every number survives). The join side is ours.
- `POST /live/join?language=es` stores the language for that seat and calls `CockpitEdge.set_language()`; a `{type: "language", code}` socket message changes it later. Only `unstep.cockpit.translate.LANGUAGES` are kept, anything else means English only. `/live/stations` lists the offered languages.
- Pilot app: a small "English, then ..." picker on the join screen, remembered on the phone.
- Checked: 1 new test through the real routes and socket; vitest and build pass.

**Related:** agent mail R17 (a), R18 item 2

## 2026-10-24: Elastic ground agents as files, a deploy script and the hub client (B5)

**Type:** Added
**Area:** Ground agents

- `elastic/`: three Agent Builder tools, three agents (Intercept, Compliance, Readback Auditor) and two Workflows (`unstep-blocked-call`, `unstep-readback-audit`). `scripts/deploy_elastic.py` creates them (`--dry-run` prints every request).
- `unstep/ground/elastic_agents.py`: with `UNSTEP_ELASTIC_AGENTS=1` the live room runs the workflow per stepped-on call and reads the agents' answers back from `unstep-proposals`. The agents never write the instruction: they add the FAA citation (kept only if that paragraph exists in `unstep-faa`) and can lower the confidence. A wrong readback starts the Readback Auditor off the radio path. Slow or failing runs keep the local proposal.
- Two short runs instead of `waitForInput`, so the gateway stays the one enforcement point (see [10-agentic-architecture.md](10-agentic-architecture.md) 4.4).
- Checked: 8 tests with mocked Kibana and Elasticsearch, plus a consistency check of the definitions. Not deployed: our sandbox can't reach Elastic, so the live deploy runs on Deekshith's machine. `unstep-faa` (W2) is still to be filled.

**Related:** PRD FR-6, [10-agentic-architecture.md](10-agentic-architecture.md), agent mail R15, D9 item 4

## 2026-10-24: Transmissions sound like a radio; Unstep's voice stays clean (R17 e)

**Type:** Added
**Area:** Audio

- People in the room now hear every transmission the way an aircraft VHF radio sounds: band-limited to about 300 to 3400 Hz, mild clipping, a little hiss, a short squelch tail (`radio_voice()` in `unstep/live/radio.py`). Unstep's private advisory is never shaped, so the contrast itself says "this is not ATC".
- Only the audio sent to listeners (`onair`, now with `radio: true`) is shaped. Cartesia STT, the overlap detector and the tower transcript still get the clean mix.
- `UNSTEP_RADIO_SOUND=0` turns it off. This is local signal processing, not Cartesia's voice changer.
- Checked: 2 tests (band limits, tail, never louder, room sends shaped audio while the mix stays clean). Not listened to on real speakers yet.

**Related:** [15-pilot-app-and-sponsor-plan.md](15-pilot-app-and-sponsor-plan.md) section 5 (Cartesia), agent mail R17

## 2026-10-24: Every heard call goes into the plane's Moss session; "what did the tower tell me?" (P4, part 2)

**Type:** Added
**Area:** Edge device

- `CockpitEdge.index_heard()` (`unstep/cockpit/edge.py`, agreed with Rishit in R15): every transmission a cockpit hears goes into its own `flight-<callsign>` session the moment its STT finishes, with `callsign`, `speaker`, `speakers`, `ts`, `stepped_on` and the event id for blocked calls. It indexes what this cockpit actually heard, static and gaps included, never the tower's full text. The pilot's own readbacks are indexed too (`type: readback`). Written through the cockpit writer only; never pushed.
- `unstep/cockpit/queries.py` new intent "recent": "what did the tower tell me in the last minute?", "what did I miss?", "last 2 minutes". A Moss session query over heard docs filtered on `ts` (and `speaker: atc` when the question says tower); the answer reads the two newest matches, marks stepped-on ones, and cites the newest doc with the search time. Calls naming another aircraft are left out.
- The live room tells each cockpit who was keyed for the audio it hears. Pilot app: new Ask line, and the private panel shows "Found in your Moss session in X ms".
- Checked: 2 new tests (answer from local memory; a full stepped-on room run indexed and answered). Not run against live Moss here.

**Related:** PRD 6.4, [15-pilot-app-and-sponsor-plan.md](15-pilot-app-and-sponsor-plan.md) section 5, agent mail R15

## 2026-10-24: Private advisory streams to the pilot's phone as Cartesia speaks it

**Type:** Changed
**Area:** Audio

- Rishit's live run showed about 1.5 s from approval to sound while Cartesia's first audio was 131 ms (R14): the phone got the advisory only after the whole line was synthesized.
- `unstep/live/room.py` `StreamingTTS`: each TTS chunk goes to the pilot's phone at once as `advisory_chunk {id, seq, sample_rate, pcm}` (the first chunk starts with the advisory chime), then `advisory_end {id, chunks, cancelled}`. The full clip still follows as `advisory_audio` with `streamed: true`, for "Play again" and older pages.
- Pilot app (`app/src/audio.ts`): plays chunks back to back in the left ear, in `seq` order; a cut-off line (pilot keys, frequency busy) stops at once.
- Checked: 4 Python tests (chunk order, chime first, cut-off, full room run) and a vitest for PCM decoding; `npm run build` passes. Not heard on a real phone or with live Cartesia yet.

**Related:** PRD section 9, agent mail R14 item 2

## 2026-10-24: Moss session for every plane, and a Moss frequency session on the hub (P4, part 1)

**Type:** Changed
**Area:** Edge device

- `UNSTEP_MOSS_AIRCRAFT` now defaults to 6 (`config.moss_aircraft()`), so every plane that joins gets its own Moss session when live. Rishit checked six real sessions at once (agent mail R3): 0 to 1 ms searches, no new cloud indexes. Per-aircraft sessions are never pushed.
- The hub's Frequency Monitor now keeps `freq-<frequency>` in Moss when live (local memory offline). It stays the only writer; any other writer is refused. If Moss fails, the monitor switches to local memory and keeps raising insights.
- Next (needs Rishit's yes, his files): index every transmission a plane hears and every readback into its own session, and answer "what did the tower tell me in the last minute?" with a Moss search filtered on `ts`.
- Checked: 2 tests with local memory and a failing stand-in for Moss; not run against live Moss here.

**Related:** PRD 6.4, [15-pilot-app-and-sponsor-plan.md](15-pilot-app-and-sponsor-plan.md) section 5, agent mail R3, R4

## 2026-10-24: First call after the hub starts is no longer lost

**Type:** Fixed
**Area:** Other

- Rishit saw the tower's first line after a server start never go on air, with no error (R13 item 2).
- `python -m unstep.live` now starts the room (cockpit agents, Moss sessions, links) when the server starts (`create_live_app(warm_start=True)`), not on the first socket. Tests keep the lazy start, so the ATC password check still runs before the room starts there.
- A seat that connects while the room is still starting gets a `status` "Room is warming up" within 0.5 s; what it sends meanwhile waits in the socket and is handled once the room is ready (checked with a slow start in a test).
- A typed line whose speech fails or comes back with no audio is no longer dropped quietly: the seat and the console get a `status` "Not sent: ... Try again." and the server logs it.
- Checked: 3 new tests; not reproduced live here (no Cartesia), so the root cause of Rishit's case is not confirmed.

**Related:** agent mail R13

## 2026-10-24: Live Elastic stats per frequency for the console (W4)

**Type:** Added
**Area:** Audit

- `GET /live/stats?since_ms=<run start>` returns `{frequency, since_ms, window_s, backend, blocked_calls, readback_errors, auto_resends, per_callsign: [{callsign, blocked, readback_errors, auto_resends}], esql, took_ms}`. Answers are cached for 2 s, so many consoles polling every 5 s ask Elastic at most once per 2 s.
- With Elastic configured, two ES|QL queries run over the events index (`unstep/ground/stats.py`): blocked calls per event and callsign on this frequency, and readback errors and auto-relays per event. Readbacks and approvals carry no frequency or callsign, so they are joined to their blocked call by `event_id`. The query text goes back in `esql` so the console can show it. The frequency and time are checked and inlined, never free text.
- Without Elastic, or if the cluster fails, the same counts come from the room's traces (`backend: "local"`, plus `elastic_error`).
- `auto_resends` means directives the policy agent re-sent on its own (`approved_via: "auto"`).
- Checked: 6 tests, Elastic mocked with `httpx.MockTransport`; not run against a real cluster here.

**Related:** agent mail R10 (W4), R11 item 2

## 2026-10-24: Hub serves https for phone microphones on the LAN (W5)

**Type:** Added
**Area:** Other

- Phones only allow the microphone on https. `python -m unstep.live --https` makes a self-signed certificate for localhost, 127.0.0.1 and the laptop's LAN address (`unstep/live/certs.py`, stored in `data/certs/`, gitignored) and serves https and wss. `--cert` and `--key` use your own. Uses the `cryptography` package if installed, otherwise the `openssl` tool.
- The tunnel in docs/15 section 2 stays the main path; this is the no-internet fallback. Each phone accepts the certificate warning once.
- Checked: 3 tests, including a real hub process answering https and a wss socket with the generated certificate. Not yet tried on a real phone.

**Related:** [15-pilot-app-and-sponsor-plan.md](15-pilot-app-and-sponsor-plan.md) section 2, agent mail R10 (W5)

## 2026-10-24: Cockpit voices hold while the frequency is busy (P5 hook)

**Type:** Added
**Area:** Edge device

- Merged Rishit's `CockpitEdge.set_frequency_busy(busy)` (82ee93e): busy cuts the advisory being spoken and holds new ones, free releases them in order.
- `unstep/live/room.py` `_key()` now calls it on every aircraft's cockpit agent when the first key goes down and when the last key comes up. A plane that joins while someone is talking starts held. Failures are logged, never raised into the key path.
- Checked: 1 new room test with fake edges, Rishit's 8 `tests/test_edge_busy.py` tests pass here.

**Related:** PRD FR-10, agent mail R11, R12

## 2026-10-24: Live room sends replays to Cartesia fast, not at real time (W3)

**Type:** Changed
**Area:** Audio

- Rishit's 15-run re-test showed the manual endpoint (`/stt/websocket`) transcribes audio sent as fast as possible just as well, so waiting a clip's length before finalize was wasted time (about 3 s per call).
- The room no longer paces the tower clip fallback (`TowerTranscriber(realtime=False)`), the cockpit hearing the radio mix (`run_audio(realtime=False)`), or the readback clip fallback. Streamed push-to-talk (P3) is unchanged; the turns endpoint keeps real-time pacing.
- `UNSTEP_REALTIME_REPLAY=1` brings back real-time pacing if Cartesia ever starts returning empty transcripts again. `TowerTranscriber` still paces by default, so presenter mode is unchanged.
- The room now forwards the P7b word alignment report as an `AuditRecord` (stage `tower_word_alignment`) after each tower transcript.
- Checked with fake STT (3 new tests); not run against live Cartesia here.

**Related:** [09-cartesia-feedback.md](09-cartesia-feedback.md) "Measured re-test", agent mail R9, R10 (W3)

## 2026-10-24: Tower words from ink-2 now carry ink-whisper's times (P7b)

**Type:** Fixed
**Area:** Ground agents

- Cartesia gives key terms only on `ink-2` and word times only on `ink-whisper`, so the two tower texts could differ and the struck "blocked words" could be the wrong words.
- `unstep/ground/tower.py` `align_words()`: both texts are cut into comparison keys (lowercase, one digit per key, spoken digits as digits) and matched with difflib. Each `ink-2` word takes the time span of the keys it matched, so "1-2-3" gets the span of "one two three". Words with no match get times interpolated between their neighbours.
- `TowerTranscriber` and `TowerStream` both use it and keep the report in `last_alignment`; `alignment_audit()` turns it into an `AuditRecord` (stage `tower_word_alignment`) listing the interpolated words. No contract change.
- Checked with fake STT streams only (8 new tests); not run against live Cartesia.

**Related:** [09-cartesia-feedback.md](09-cartesia-feedback.md) item 2, agent mail D4, D7

## 2026-10-24: Cartesia re-test written up, repro script runs without PYTHONPATH

**Type:** Docs
**Area:** Audio

- [09-cartesia-feedback.md](09-cartesia-feedback.md): new "Measured re-test" section from Rishit's 15-run `scripts/cartesia_repro.py` results, only what reproduced: the manual endpoint accepts fast (not real-time) audio, word timestamps only on `ink-whisper`, handshake and finalize numbers. The hedged-finalize workaround (P7a) never won, so it is dropped.
- `scripts/cartesia_repro.py` adds the repo root to `sys.path`, so it runs from anywhere.
- Earlier today, not logged before: P1 per-stage `timings` on every live trace (e040a1a), P2 Elastic percolator readback check (453c396), P3 mic frames streamed to STT while the key is held (d3e183b), P7c the repro script itself (08ce979).

**Related:** agent mail R9, D7

## 2026-10-24: Pilot app, join on demand, and a sponsor plan

**Type:** Added
**Area:** Other

- `app/`: pilot phone app (React, TypeScript, Vite) that runs on Vercel or at `/pilot/` on the hub. One tap joins as the next free plane; hold-to-talk with live "someone is talking" and TALKED OVER states, private advisory panel, readback result, tap-to-say lines, Ask Unstep, timings.
- Hub: `POST /live/join` (six-plane fleet, cockpit agent per plane on demand), live `keyed` and `stepon_live` messages, ping/pong clock sync, `UNSTEP_ALLOWED_ORIGINS`, `/live/pilot-link` for the QR, `UNSTEP_MOSS_AIRCRAFT`.
- Seed data uses each plane's own spoken callsign, so H456 no longer gets Cessna clearances.
- [15-pilot-app-and-sponsor-plan.md](15-pilot-app-and-sponsor-plan.md): hosting, crowd demo flow, millisecond-level ideas, Moss in-session indexing, Cartesia and Elastic plans, dataset build and validation.
- CLAUDE.md: agent mail rules, no force pushes on shared branches, commit as the human.
- Our 5 commits from earlier today were re-authored from a tool identity to Dee-1862; Rishit was told in agent mail (D2).

**Related:** [Pilot App and Sponsor Plan](15-pilot-app-and-sponsor-plan.md), [Live Demo](11-live-demo.md)

## 2026-10-24: Projector-ready Control Tower console

**Type:** Added
**Area:** Other

- Added `/live/atc/` with an illustrative airport, evidence-driven aircraft states, plain-English event summary, decision cards with policy reasons and expiry, radio lanes, and numbered explanations with honest timing labels.
- Added a three-seat picker and password dialog. `UNSTEP_ATC_PASSWORD` protects the tower socket with constant-time comparison before joining; existing plane and observer protocols are unchanged.
- Added route, authentication, role isolation and policy wording tests in `tests/test_atc_console.py`. Tests were written but pytest was not run in this sandbox.
- Join URL is displayed prominently; QR generation remains a TODO. Ground-agent stand-ins and missing timing measurements are disclosed on screen.

**Related:** [ATC console spec](14-atc-console.md), [Live demo](11-live-demo.md)

## 2026-10-24: Live room built: pick a seat, agents in the middle, controller for edge cases

**Type:** Added
**Area:** Other

- `python -m unstep.live` serves the live room on the gateway. Each person picks a seat (tower controller, Cessna N123AB, Helicopter H456, observer) and talks on a shared virtual frequency by typing or with a hold-to-talk microphone.
- `unstep/live/radio.py`: overlap clusters, mixing with an AM beat tone on overlapped frames, keyed squelch from real push-to-talk timing, radio truth.
- `unstep/live/room.py`: tower transcriber, one cockpit agent per aircraft, ground agents (stand-in until B5), policy agent, frequency monitor and an observer, all in process but through the real gateway and its rules.
- Controller screen: live agent graph with message flows, "Needs you" queue with countdowns, auto-relay switch, and an evidence chain per blocked call (struck words, what the cockpit heard, Moss hint and source, policy checks, timed agent steps). Pilot screen: left-ear advisories, cockpit transcript, ask-Unstep box. Observer: read-only supervisor view.
- Live check with four browser seats on real Cartesia: an auto-relayed hold short with a wrong then right readback, and an escalated takeoff clearance that the controller rejected. Two bugs found and fixed on the way (M-016).
- 9 new tests for the radio, the room, the app and the speech queue.

## 2026-10-24: Policy agent: the controller is needed only for edge cases

**Type:** Added
**Area:** Ground agents

- Added `unstep/ground/policy.py`. The blocked instruction was already spoken by the controller, so when the agents can show they are re-delivering exactly those words, the policy agent relays them without asking again. Every other case goes to the controller with readable reasons.
- Auto-relay needs all of: the tower transcript exists, it was addressed to this aircraft, the instruction is restrictive, confidence is high, the cockpit hint does not disagree, the controller spoke within `UNSTEP_AUTO_MAX_AGE_S` (default 30 s), and auto-relay is switched on.
- Gateway: new `policy` role that may only send `ApprovedDirective` and `AuditRecord`, never a rejection. The gateway re-checks every auto approval (restrictive and high confidence) and rebuilds it from the stored proposal, so a forged or unsafe auto approval stays pending for the controller.
- Contract change, needs Rishit's agreement: `ApprovedDirective.approved_via` now allows `"auto"`, with `approved_by` set to `unstep-policy`.
- PRD rule change, needs Rishit's agreement: FR-6 ("no directive without explicit human approval") becomes "no directive without explicit human approval, except an auto-relay of the controller's own verified restrictive words, which the controller can switch off".
- 14 new tests.

## 2026-10-24: Proposed a live multi-person demo room

**Type:** Docs
**Area:** Other

- Added [11-live-demo.md](11-live-demo.md), a proposal to replace the scripted presenter with a live radio room: each person joins from their own browser, picks a role (tower, pilots, observer), and talks on a shared virtual frequency, so blocked transmissions happen for real.
- Covers roles for three or more people, a 3 minute flow plus free play, the per-event evidence chain for explainability, a controller queue with countdowns for several aircraft, a typed "say" box for noisy halls, and a build plan (L1 to L6).
- Notes from the presenter screenshots: "Scene failed (RuntimeError)" in the controller scene is most likely a proposal expiring after 60 s while scenes wait on "Next", and one live run took 5.4 s to finalize the cockpit transcript.

## 2026-10-24: Merged Rishit's presenter mode and demo work into the Dev B branch

**Type:** Changed
**Area:** Other

- Merged 19 commits from `rishit` (presenter mode and demo screen, live microphone push-to-talk, tower transcript and blocked-word plumbing, Cartesia reconnect and retry fixes, pre-flight check, pitch script). No conflicts.
- Two new TTS reconnect tests only passed where `CARTESIA_VOICE_ID` was set in `.env`. They now set a test voice id like they already set a test API key.
- `unstep/ground/tower.py` had the Cartesia models written in. They now come from config: `CARTESIA_STT_MODEL` (default `ink-2`) for text with key terms and the new `CARTESIA_STT_TIMESTAMP_MODEL` (default `ink-whisper`) for word timing.
- `scripts/preflight.py` crashed when `CARTESIA_VOICE_ID` was missing, so the Moss and Elastic checks never ran. It now reports the TTS check as FAIL and carries on.
- Checks: 259 tests pass, offline demo passes, pre-flight passes every live check (Cartesia STT, Moss, Moss Inference, Elastic) except TTS, which needs `CARTESIA_VOICE_ID` in `.env`.

## 2026-10-24: Live microphone for presenter mode

**Type:** Added
**Area:** Audio | Other

`python -m unstep.demo --live --mic` lets the presenter speak the controller's
"Approve", the pilot readbacks and the pilot questions live. Hold V in the
browser: it streams 16 kHz PCM16 over the new local-only `/demo/mic` socket,
`unstep/demo/mic.py` feeds each utterance to Cartesia ink-2 (manual endpoint,
finalized on V release) and exposes the result as a turn-STT source the scenes
use in place of the clips. 30 s of silence falls back to the recorded clip,
labeled. Audits carry `input` (live mic or recorded clip) and the screen no
longer says "recorded controller clip" after a live approval. `ApprovalLoop`
takes an optional `window_s` (default 10 s, 45 s in `--mic` mode); its strict
matching, repeat-back and retry are unchanged. Without `--mic` nothing changes.
Tests: `tests/test_demo_mic.py`.

**Related:** [Demo design section 6](11-demo-design.md#6-presenter-mode)

---

## 2026-10-24: Demo screen polish

**Type:** Changed
**Area:** Audit | Other

Speech audit payloads now carry `display_text` (readable, "Runway 33") next to
the phonetic `spoken_text`; the screen prefers it and maps word highlights onto
it by fraction of speech time. The controller prompt is built from the slots
("Blocked call to Cessna 1-2-3: hold short Runway 33. Approve?"). The demo page
shows every transmission per lane (older ones compact), the cockpit's received
text with a BLOCKED band, a per-attempt readback table, per-step latencies only
(labeled offline fakes in replay) and three analytics counts. `web/demo/` JS and
CSS rewritten in readable form.

**Related:** [Demo design](11-demo-design.md)

---

## 2026-10-24: Demo observer, speech artifacts and tower recovery

**Type:** Added
**Area:** Ground agents | Audio | Audit

Added a read-only observer with 200-message replay, `/demo/` static hosting and
optional `/demo/audio/` WAV artifacts. Speech audits include exact normalized
spoken text, heard text, party and available word times. Audio export is off
by default; `--demo-audio-dir` enables it on the edge, controller and demo runner.
Controller utterances stream individually with demo audio enabled; normal runs
retain the existing decision-then-audit sequence and include utterances inside
the final audit payload.

B2 now uses parallel, paced manual streams: ink-2 for keyed text and ink-whisper
for word offsets. B3 marks words with at least half their duration blocked.
Mock agents retain the latest tower transcript per frequency and use it when
PTT overlaps the cockpit event. The demo runner publishes the clean tower
transcript with the same epoch base as the received cockpit clip.

Added `tests/test_demo_plumbing.py`. Syntax checked without importing project
modules. Pytest and live vendor calls were not run in this sandbox. Contracts
are unchanged.

## 2026-10-24: Grounded pilot questions and persistent airport knowledge

**Type:** Added
**Area:** Edge device

Regex pilot intents remain the primary path. Unmatched questions retrieve the
three newest approved clearances for this callsign and up to three airport hits,
then use an injectable Moss Inference answerer with server retrieval disabled
(`indexes=[]`). Answers must be an exact no-record response or an attributable
quote of at least three words, with no extra claims. Unapproved hints are excluded.
Failures and a three-second deadline return the existing ask-controller response.
First-token latency goes into the pilot-query audit payload and edge latency
summary; shared contracts are unchanged. Hints, readbacks and approval remain
deterministic. The offline demo uses FakeAnswerer for its new free-form question.

Run `python scripts/ingest_airport.py` before starting a cockpit with Moss.
The script uses credentials from the process environment, skips without them,
creates `airport-KUNS` once, and upserts the stable seed ids on later runs.
The bundled data is for fictional KUNS only. Cockpit startup uses `load_index`
and cannot add or push airport records; flight and frequency stay sessions.
LocalMemory still seeds both indexes. The smoke script now pushes only flight.
Cloud lifecycle follows the [Moss Python API](https://docs.moss.dev/docs/reference/python/api)
and [indexing guidance](https://docs.moss.dev/docs/integrate/indexing-data).

Added `tests/test_inference.py` with fake inference and cloud clients. Python
syntax checks passed for all nine changed Python files. The requested Python312
pytest executable was absent in the execution environment, so the full suite
could not start. No live inference or ingestion calls were run.

**Related:** [PRD 6.2, 6.4 and FR-14](01-prd.md)

## 2026-10-24: Voice approval timeout could send nothing on Windows

**Type:** Fixed
**Area:** Ground agents

- `test_runner_silence_sends_only_unclear[True]` failed about once in four full runs. Cause: asyncio may fire a sleep or timeout up to its clock resolution early (about 15 ms on Windows), and `ApprovalLoop.timeout()` only acts once `clock() >= deadline`. An early wake meant controller silence produced no "unclear" and no retry, in the real 10 s window too.
- Fixed in parallel by both developers. Rishit's `timeout(force=True)` was kept when merging, and Dev B's `_until_deadline()` helper was dropped so there is one mechanism.
- Process note: master was fast-forwarded to `abbbb53` by a command that did not stop on a failed test run. Merges to master now run the suite first and stop on failure.

## 2026-10-24: Demo view added to the main architecture doc

**Type:** Docs
**Area:** Docs

- Added an "At a Glance (demo view)" section at the top of [05-architecture.md](05-architecture.md) with the same six-step, sponsor-colored picture as [10-agentic-architecture.md](10-agentic-architecture.md), so both architecture docs open with the simple flow.

## 2026-10-23: Controller voice approval (B10)

**Type:** Added
**Area:** Ground agents

Built by Dev A so Dev B can focus on B5. Code: `unstep/ground/voice_approval.py`, tests: `tests/test_voice_approval.py` (38 tests).

**How it works**

1. A `ProposedDirective` arrives on the `controller_voice` role. Proposals are queued and handled one at a time.
2. Chime, then Cartesia TTS in the controller's headset: "Blocked call to N123AB: hold short Runway 33. Approve?"
3. Cartesia turn STT listens only to the controller's Unstep key (the STT source passed in), never to radio audio.
4. The answer is matched exactly after cleanup: approve ("approve", "approved", "affirm", "send it", "yes approve") or reject ("reject", "negative", "cancel", "I'll reissue"). Anything else, or a mix like "approve, no, reject", is unclear.
5. Unclear: "Say again, approve or reject?" once. A second unclear answer, or no answer within 10 s, sends `VoiceApproval(decision="unclear")`, which the gateway ignores. Nothing is sent and the dashboard card stays for a click.
6. Approve: Unstep says "Approved, sending to N123AB." and only **after** that finishes sends `VoiceApproval(decision="approve")`. If the repeat-back is cut off, nothing is sent. Reject works the same with "Rejected. Reissue by voice."
7. If the event is decided elsewhere (a dashboard click), the loop stops speaking and sends nothing.
8. The gateway still builds the `ApprovedDirective` from its stored proposal (unchanged).

**Run:** `python -m unstep.ground.voice_approval` (scripted "Approve"), or `--live --answer-clip <wav>` for real Cartesia TTS and STT on a recorded answer. `scripts/run_demo.py` now uses this loop instead of the auto approver.

**Limits:** no live microphone input yet (recorded clip or scripted speech). Strict phrase matching may ask "say again" more often than a person would; that's the safe direction.

**Process note:** written by OpenAI Codex under Rishit's direction, then reviewed line by line against the PRD voice approval rules and tested with the full suite (168 passed).

**Related:** [PRD section 7, voice approval rules](01-prd.md#7-end-to-end-workflow), [Work Split B10](04-work-split.md#5-dev-b-gateway-tower-and-elastic)

## 2026-10-23: Simple demo view added to the agentic architecture

**Type:** Docs
**Area:** Docs

- Added section 2 "Demo View: One Picture" to [10-agentic-architecture.md](10-agentic-architecture.md): six boxes left to right, one color per sponsor, plus a table of what the audience sees or hears at each step.
- The detailed diagrams moved down one section number (3 to 7).

## 2026-10-23: One config for every connection, gateway token fixed

**Type:** Fixed
**Area:** Ground agents

- Accepted Rishit's latest commit by fast-forwarding master to `rishit`, then merged master into the Dev B branch (no conflicts).
- Connection bug: `UNSTEP_GATEWAY_URL` was in `.env.example` but nothing read it, and every client had `ws://127.0.0.1:8765` written in. All clients (edge, monitor, mock cockpit, mock agents, auto approver, demo runner) now take the address from `unstep/config.py`, with `--url` as an override.
- Token bug: when `UNSTEP_GATEWAY_TOKEN` was set the gateway rejected every client and the dashboard, because none of them sent it. Clients now add it through `ws_url()`, the gateway serves the dashboard page with it, and the gateway reads it on each connection.
- No more hardcoded Cartesia version, STT model, TTS model or Elastic index: each has a default in `unstep/config.py` and an override in `.env`. Cartesia endpoint URLs stay as constants because they are Cartesia's fixed API addresses.
- `.env` is now loaded when `unstep.config` is imported, so every entry point sees the keys.
- Live check on port 8766 with a token: clients without it are rejected, all roles connected from `UNSTEP_GATEWAY_URL` alone, real Moss and Cartesia, 12 documents in Elastic with 0 failed. 145 tests pass.
- Found, not fixed: the live Moss frequency index is `freq-118.300`, but the code and contracts use `118.700`, so the monitor would create a fourth index on a three-index plan. Needs Rishit's decision.

## 2026-10-23: Proposed agentic architecture for ground, cockpit and the link

**Type:** Docs
**Area:** Ground agents

- Added [10-agentic-architecture.md](10-agentic-architecture.md), a proposal for Dev A to review.
- Ground: no LLM supervisor agent. An Elastic Workflow orchestrates narrow Agent Builder agents (`ai.agent` steps) and pauses for the controller (`waitForInput`). The gateway stays the only place a directive is created (FR-6). Step types checked against the Elastic Workflows docs.
- Cockpit: the edge agent is a state machine with Cartesia and Moss on local compute, plus an optional "Unstep, why?" explanation built from a per-event evidence bundle.
- Link: radio stays the fallback, a live link carries only ATC-style messages, and Moss carries context handoff after the event. CPDLC (bounded at 120 s at 95%, RA-5) and Moss handoff (push replaces the index, 300 s polling) are both too slow for a live correction.
- Proposed dropping `gps` from `AnomalyEvent` (contract change, needs both developers).
- Noted from Rishit's handoff: B10 controller voice approval is being built by Rishit, and the stray Moss index was removed so `freq-118.300` is live.

## 2026-10-23: Cockpit edge and monitor load .env, live stack verified

**Type:** Fixed
**Area:** Edge device

- `python -m unstep.cockpit.edge` and `python -m unstep.cockpit.monitor` did not load `.env`, so run on their own they fell back to fake Cartesia and local memory even with keys set. Both now call `load_env()` at start. `scripts/run_demo.py` was not affected because it loads `.env` itself.
- Accepted Rishit's PR by fast-forwarding master to the `rishit` branch (130 tests passed on it), then merged master into the Dev B branch.
- Live check on the standalone stack: Moss memory on the real project, Cartesia STT final 384 ms, Cartesia TTS first audio 79 to 97 ms, 12 documents stored in Elastic with 0 failed.
- `CARTESIA_VOICE_ID` (the advisory voice, task A6) is still not chosen. Live runs used Zander (`aa2cafe9-97ba-4052-ac3c-875000f95212`, "measured and calm") as a stand-in.

## 2026-10-23: Dev A status on branch `rishit`

**Type:** Added
**Area:** Edge device

| Task | Status |
| --- | --- |
| A1 audio input, clips | Done: synthetic clips plus real Cartesia-voiced clips in `assets/clips/real/` |
| A2 overlap detector | Done, tuned on real speech. Only proven on clips we mixed (RA-4) |
| A3 cockpit STT | Done: Cartesia `ink-2` manual mode, finalize on squelch close, live tested |
| A4 Moss hint | Done and verified on real Moss: hint search 0.6 ms, pilot query 1.0 ms, numeric ts filters correct |
| A5 Frequency Monitor | Done |
| A6 advisory TTS | Done: `sonic-3.6`, pronunciation dictionary uploaded, chime, left ear, live tested |
| A7 readback check | Done: live tested on real readback clips |
| A8 offline | Done: pre-generated alert, outbox, memory fails safe |
| A9 latency | Measured live: TTS first audio about 100 ms, manual STT 143 ms, turn end about 650 ms |
| A10 pilot queries | Done: live tested on a real question clip |

- Red team found 18 issues across the gateway and cockpit. All fixed with regression tests (130 tests pass).
- `python scripts/run_demo.py` runs offline. `--live` runs on the real Cartesia API.
- Cartesia feedback logged in [09-cartesia-feedback.md](09-cartesia-feedback.md).
- **For Dev B:** tower STT must choose between `ink-2` (key terms) and `ink-whisper` (word timestamps), see Cartesia feedback item 2. The gateway now enforces per-role senders and rebuilds directives from the stored proposal.

**Related:** [README](../README.md), [Work Split](04-work-split.md)

## 2026-10-23: Blue-team fixes to the Moss layer, local hint and pilot queries

**Type:** Fixed
**Area:** Edge device

- `MossMemory` translates our filters into the Moss SDK form (`{"field", "condition"}`, string values, `$and`/`$or` lists) via `to_moss_filter`. Local filter semantics unchanged.
- New `fetch()` (filter-only, unranked) on both backends. The local hint and "last clearance" now use the newest record by `ts`, so a superseded clearance can't win on score. Hints need a clearance from the last 15 minutes.
- `likely_instruction` picks the runway the hold short applies to. A "go around" or "stop" fragment gets no hold short hint. Permissive fragment check normalizes case, hyphens and spacing and covers take off, cleared, clear, depart, cross, line up.
- "Say again" never reads back a "Likely" hint, and repeats the newer approved clearance once one exists. "Repeat the last clearance" is a last-clearance question.
- `record()` never overwrites an existing id (writes `<id>-v2`). Records naming another aircraft are ignored for this aircraft.
- Memory errors give no hint or "No record found" instead of crashing. The edge opens Moss sessions at startup.
- Regression tests in `tests/test_blue_team.py`.

**Related:** [PRD section 7, local hint rules](01-prd.md)

---

## 2026-10-23: Overlap detector retuned for real speech

**Type:** Fixed
**Area:** Audio

The old detector (peak share of in-band power over 3 frames) false-fired on Cartesia TTS speech. It now scores each bin's prominence over a local spectral median (500 to 3400 Hz), takes the minimum over the last 300 ms, and opens when a line stays 12 dB above its neighbours for 5 more frames; start is backdated 280 ms, windows under 300 ms are dropped. Real and synthetic clean clips give no window; both stepped-on clips give one window from 1.3 s to the end. About 0.07 ms per frame. Added real-clip tests (skipped when the files are missing). Limits: tones below 500 Hz are ignored, a second voice without a beat tone is not flagged, and a beat tone at level 0.07 or lower against this speech gives broken or late windows.

**Related:** tests/test_overlap.py, scripts/make_real_clips.py

## 2026-10-23: Elastic settings check and Kibana data view

**Type:** Added
**Area:** Audit

- Added `scripts/check_elastic.py`. It checks the Elasticsearch URL, the Kibana URL and the API key without printing secrets, and flags an Elasticsearch address (`.es.`) put in `KIBANA_URL`.
- Created the Kibana data view "Unstep events" on `unstep-events` with `@timestamp` as the time field, so events show in Discover.
- Live check: branch merges into master with no conflicts, 91 tests pass, 5 mock cockpit runs stored 20 documents in Elastic with 0 failed, and an ES\|QL count by type returns the expected rows.

## 2026-10-23: New Elastic API key checked, Kibana URL added

**Type:** Changed
**Area:** Ground agents

- Checked the new `ELASTIC_API_KEY` (name "lolo"): it authenticates on Elasticsearch and has create, write, read and manage rights on `unstep-*`.
- The same key works on Kibana, and the Agent Builder API answers, so task B5 is unblocked without a second key.
- Added `kibana_url()` to `unstep/config.py`. It uses `KIBANA_URL` if set, otherwise the Elasticsearch URL with `.es.` replaced by `.kb.`.
- `.env.example` now lists `KIBANA_URL` and notes that the key must work on both Elasticsearch and Kibana.
- Live Elastic round-trip test passes with the new key.

## 2026-10-23: Gateway stores every message in Elastic (task B1)

**Type:** Added
**Area:** Audit

- `ElasticSink` in `unstep/gateway/sink.py` writes every gateway message to the `unstep-events` index with the `_bulk` API.
- `write` never waits on the network. Documents go on a bounded queue and a background task sends them, retries a failed request once, and counts sent, failed and dropped documents (shown on `/health`).
- The index has a strict mapping. Query fields (`type`, `source`, `event_id`, `callsign`, `frequency`, `decision`, `approved_via`, `match`, `kind`, `stage`) are promoted to the top for ES\|QL (task B8). The full message is kept in `data` but not indexed, so no message type can cause a mapping conflict.
- The gateway loads `.env` through `unstep/config.py` and picks the Elastic sink when the URL and key are set, otherwise the JSONL file. It accepts `ELASTIC_API_KEY` or `ELASTIC_CLOUD_KEY`.
- Verified on the real Elastic Serverless project: 10 mock cockpit runs stored 40 documents, 0 failed.
- 8 new tests with a fake Elastic, plus a live round-trip test that runs with `UNSTEP_LIVE_ELASTIC=1`.

## 2026-10-23: Merged master into the Dev B branch and removed duplicate code

**Type:** Changed
**Area:** Ground agents

- Rishit's M0 and M2 work on master (`unstep/`) and Dev B's first draft (`contracts/models.py`, `ground/gateway/`) built the same contracts and gateway in parallel.
- Kept `unstep/` as the one codebase, since its gateway is further along (proposal TTL, replay on reconnect, token and origin checks). Removed Dev B's duplicate `contracts/models.py`, `ground/` and their tests.
- Dropped Dev B's proposed `ClickApproval` and `DirectiveRejected`. master already covers them: the dashboard sends `ApprovedDirective` or `RejectedDirective`, and the gateway rebuilds them from the stored proposal.
- The Elastic events sink is still open on task B1. It comes next on this branch.

**Related:** [Mistakes and Lessons, M-015](03-mistakes-and-lessons.md)

## 2026-10-23: M0 contracts and M2 first wire

**Type:** Added
**Area:** Other

- Python stack: FastAPI WebSocket gateway, Pydantic contracts, plain HTML dashboard.
- `unstep/contracts.py` implements every contract from Work Split section 3, plus `RejectedDirective` (the cockpit needs it to say "request say again"). Please confirm this addition.
- `contracts/examples/` has one JSON example per contract, generated from `unstep/scenario.py`.
- Gateway routes messages by role, stores every message (JSON lines for now, Elastic in B1), and turns voice or click decisions into one `ApprovedDirective` or `RejectedDirective`. A second decision on the same event is refused.
- Mock cockpit, mock agents, auto approver and mock dashboard. M2 passes 10 runs in a row live and in tests.

**Related:** [Work Split, milestones](04-work-split.md#6-milestones), [README](../README.md)

## 2026-10-23: Voice first in PRD v0.4

**Type:** Changed
**Area:** Audio

- PRD v0.4: voice first. The pilot asks Unstep questions on a separate Unstep key, answered from Moss. The controller hears each proposed correction and approves by voice, with the click as a fallback. A chime starts every Unstep message.
- Added voice approval rules: only the Unstep key counts, repeat back before sending, one retry, 10 second timeout to "nothing sent."
- Local hint is now restrictive instructions only, and always shows its source Moss record.
- Cockpit transcript finalizes on squelch close. One clock for all timestamps, tower word times as offsets from `ptt_start`.
- Architecture v0.4: controller voice loop, pilot query path, Frequency Monitor as the only writer to the frequency session. New contracts `VoiceApproval` and `PilotQuery`.
- Work split v0.4: new tasks A10 (pilot voice queries) and B10 (controller voice approval). Both developers now at 10 tasks and 20 points.
- Demo flow: nobody touches a screen until step 7.
- Mistakes: added M-013 and M-014. Advice: added section 10 with the reasoning.

**Related:** [PRD](01-prd.md), [Advice, section 10](08-advice.md#10-voice-first-added-after-v03-folded-into-v04)

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
