# Moss Max: Using Every Moss Feature That Fits

Moss told us they like Unstep as a startup ("the whole ecosystem") and want **Moss-specific features made explicit**. This plan uses as much of the Moss SDK as genuinely helps a pilot. Every feature below was read from the installed `moss` 1.21.0 SDK (signatures checked with `inspect` on 2026-10-24), not from marketing.

| Field | Value |
| --- | --- |
| Status | Proposal v0.1 |
| Owner | Moss: Deekshith's side builds, Rishit's side reviews; console drawing: Rishit's side |
| Needs cloud billing | marked ☁ (Rishit's Moss project hit its usage limit; local items work today) |

## 1. What we already use (LIVE)

| Moss feature | Unstep use | Measured |
| --- | --- | --- |
| `session()`: local, in-process, one per plane | Each plane agent's own memory | 6 sessions; fetch 0.2–0.4 ms warm |
| `query(alpha=…)` hybrid search | The garbled fragment → the right clearance | 1.0 vs 0.0 for unrelated speech |
| `filter` on metadata | This plane, clearances only, last N minutes | live |
| `get_docs(sort_by=…, group_by=ParentGrouping)` | Newest clearance; "the whole exchange" | native sort numeric, 4 groups |
| Moss Inference | Advisory translation (es, hi, fr) | Spanish correct, ~1.9 s cold |

## 2. The Moss-max list (ranked)

| # | Moss feature (exact API) | What it does for the pilot | Demo moment | Cloud? |
| --- | --- | --- | --- | --- |
| **MM1** | `SessionIndex.save_to_disk()` / `load_from_disk()` | **The plane's memory survives a restart on board, with no network.** Save after every new clearance; reload when the agent starts | Kill and restart the hub: Plane A still answers "what was my last clearance?" | No, works today |
| **MM2** | `query_multi_index([...])` | "Ask Unstep" searches the plane's memory, the frequency's recent calls and airport knowledge in **one** query, with a global top-K | "Where am I supposed to stop?" answered from three sources at once, each labelled | Loaded indexes |
| **MM3** | `create_web_source(root_url, refresh_cadence=…)` | Moss crawls the **FAA Pilot/Controller Glossary** on faa.gov and keeps it fresh. A non-native or student pilot asks "what does hold short mean?" and gets the official definition | Ask on the phone; the answer cites the faa.gov page | ☁ |
| **MM4** | `load_index(name, auto_refresh=True, cache_path=…)` + `was_served_stale(name)` | The tower publishes the frequency's clearances as one cloud index; every plane loads it with auto-refresh, so a plane that just tuned in already knows recent clearances. **When offline, the plane is served from its disk snapshot and says so** ("memory from 4 min ago, no link") | Turn off Wi-Fi on a phone: it keeps answering, with a "stale" badge | ☁ |
| **MM5** | `create_index_from_files(files, parse_options=ParseOptions(ocr_mode=…, merge_tables=True))` | The airport's chart supplement / diagram PDF becomes searchable on board ("which taxiway goes to runway 33?") | Upload one FAA airport PDF; ask about it | ☁ |
| **MM6** | `QueryOptions(min_score=…, candidate_depth=…)` | Moss's own score floor and candidate depth for the hint search (today we apply our own floor) | The console shows "below Moss's floor: no hint" | No |
| **MM7** | `ModelRef` / `model_id` (`moss-minilm` vs `moss-mediumlm`) | A/B the embedding model on garbled radio fragments: speed vs accuracy, measured | One line in the benchmark: "minilm 0.4 ms / mediumlm 0.9 ms, accuracy X vs Y" | No |
| **MM8** | Moss in the voice loop, timed | Every cockpit voice turn shows its budget: **Ink 150 ms → Moss 0.8 ms → Sonic 90 ms**. That makes "Moss adds nothing you can hear" visible | A voice-turn bar on the console and the phone | No (console: ours) |

**Order:** MM1 first (it fixes "survives a restart" without billing), then MM8 (console, ours), MM6, MM2. MM3–MM5 the moment billing is fixed. MM7 if time.

## 3. Rules that stay

- Moss search is **evidence**: the hint comes from the newest clearance, restrictive only, and a human approves.
- Never quote a Moss number that wasn't measured live.
- Web sources and files cite their source on screen; nothing is presented as an instruction.

## 4. How to say it

> "Every plane runs an agent, and Moss is its memory. It lives on board, survives a restart, works offline and tells you when it's stale. It searches the plane's memory, the frequency and the FAA glossary in one query, all in about a millisecond, right in the middle of every Cartesia voice turn."
