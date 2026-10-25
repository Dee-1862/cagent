# Sponsor Features: What Each Sponsor Is Proud Of, and How Unstep Uses It

Sponsor feedback after our first pitches (2026-10-24):
- **Moss** liked the startup angle (a whole ecosystem people would line up for) and wants Moss-specific features, and how Moss helps the voice side, made explicit.
- **Elastic** said ingesting a rulebook is an okay use, "not the greatest use of their products". They want flagship features.
- **Cartesia** needs its own document listing the features it is proud of and how we use each one.

| Field | Value |
| --- | --- |
| Status | Draft v0.1 |
| Last updated | 2026-10-24 |
| Owners | Cartesia and console: Rishit's side. Moss and Elastic: Deekshith's side, reviewed by Rishit's |

Tags: **LIVE** (run on the real service by us, with the number), **BUILT** (code and offline tests), **NEXT** (proposed here, not built).

---

## 1. Cartesia: the ears and voice of every agent

What Cartesia shipped and pushed in 2026, from its changelog ([docs.cartesia.ai/changelog/2026](https://docs.cartesia.ai/changelog/2026)) and launch coverage ([Sonic-3.5 + Ink-2](https://runtimewire.com/article/cartesia-sonic-35-ink-2-voice-agent-benchmarks), [Sonic-3.6](https://slator.com/cartesia-launches-text-to-speech-model/)).

| Cartesia feature (what they push) | How Unstep uses it | Status |
| --- | --- | --- |
| **Ink-2 streaming STT** (May 2026; noise robustness) | Every transmission is transcribed while the key is held, for the tower and for what each cockpit hears. Final text arrives about 150 ms after release | LIVE: tower 155 ms, cockpit 172 ms after release |
| **Keyterm prompting** (July 2026) | Callsigns, runways and "hold short" are sent as key terms | LIVE, 200-line benchmark in radio noise: callsign 62.5% → 95.5%, runway 81.6% → 98.5%, WER 0.191 → 0.009 |
| **Streaming text during speech** | Live captions on the projector and the phones, with the lag shown | LIVE: 4 captions before release, final 97 ms after |
| **Sonic-3.6** (Aug 2026; natural prosody, 44 languages) | Private advisory in the pilot's left ear, streamed from the first chunk | LIVE: first audio 86–201 ms |
| **Multilingual voices, same voice across languages** | The advisory is repeated in Spanish, Hindi or French in the same voice | LIVE (es, hi, fr checked) |
| **Speed control** (May 2026) | "Readback incorrect" corrections are spoken slower (0.85) | BUILT |
| **Pronunciation dictionaries** | ATC words ("tree", "fife") | LIVE. Lesson: our "niner" respelling broke recognition, and a TTS → STT test caught it (runway 85% → 100%) |
| **Context cancel / interruption** | The advisory stops the moment the pilot keys the mic, and replays cleanly from the start | BUILT |
| **Ink-2 multilingual** (Sept 2026: es, fr, hi, ja) | Pilots who joined in Spanish, Hindi or French can ask Unstep questions in that language | NEXT (small: pass `language` to Ink-2 for the "Ask Unstep" button) |
| **Turn detection controls, eager-end** (June 2026) | Detect the end of a call early and pre-render the advisory; cancel if the speaker resumes | NEXT |
| **`locale` / `normalization` fields, native alphanumeric readouts** (Aug 2026) | Let Sonic-3.6 read callsigns and runways natively instead of our digit spelling; A/B it with the eval loop | NEXT (measure first) |
| **Volume control** (May 2026) | A slightly louder advisory over a noisy cockpit | NEXT |
| **Managed Agents + knowledge bases + tools** (Aug 2026) | The pilot's "Ask Unstep" as a Cartesia Managed Agent, with a tool that queries the plane's Moss memory | NEXT (would put a Cartesia agent inside the loop) |
| **Zero data retention, call redaction, self-hosted Sonic** | The aviation story: cockpit audio not stored by the vendor; an on-board, air-gapped deployment | Pitch only (we say it's possible, not that we did it) |

**The one line for Cartesia:** "Cartesia is the ears and voice of every agent: it hears the whole frequency in real time and speaks privately to exactly the right person, in their language."

---

## 2. Moss: each plane's on-board memory, inside the voice loop

What Moss pushes ([moss.dev](https://www.moss.dev/use-cases/voice-agents), [YC launch](https://www.ycombinator.com/launches/Oiq-moss-real-time-semantic-search-for-conversational-ai), [docs](https://www.moss.dev/llms-full.txt)):
- sub-10 ms search **inside the agent's own process**, built for the **speech-to-text → retrieval → LLM → speech** loop;
- runs on device and offline, then **syncs when connected**;
- hybrid search, metadata filters, built-in embedding models, and live index refresh.

**How Moss helps the voice side (the Cartesia link):** each cockpit agent's loop is **Cartesia Ink hears → Moss searches the plane's memory → Cartesia Sonic speaks**. Moss sits in the middle of every voice turn, and at about 1 ms it adds no audible delay. That is exactly the loop Moss is designed for.

| Moss feature | How Unstep uses it | Status |
| --- | --- | --- |
| **Local in-process sessions, one per plane** | Each aircraft's agent keeps its own private memory: clearances, calls heard, readbacks | LIVE: 6 sessions, fetch 0.2–0.4 ms warm |
| **Hybrid search (`alpha`)** | The garbled fragment ("Cessna 123, short runway 30") is searched half by meaning, half by exact words | LIVE: right clearance scores 1.0, unrelated speech 0.0 |
| **Metadata filters** | Only this plane, only clearances, only the last N minutes | LIVE |
| **Sorting and grouping** | Newest clearance first; "the whole exchange" grouped | LIVE (native sort numeric) |
| **Answers from memory in the voice loop** | "What did the tower tell me in the last minute?" is answered from Moss and spoken by Sonic | LIVE: under 1 ms |
| **Moss Inference** | Translates the private advisory (digits must survive) | LIVE (Spanish correct) |
| **Works offline, syncs when connected** | The plane's memory works with no link to the ground; each finished flight is pushed to Moss Cloud as a flight log | BUILT; push blocked by the project usage limit |
| **`loadIndex` with auto-refresh** | The tower publishes the frequency's clearances as one cloud index; every plane loads it with auto-refresh, so a plane that just tuned in already knows recent clearances | NEXT (strong Moss-native feature; needs billing fixed) |
| **Embedding models (`moss-minilm` vs `moss-mediumlm`)** | A/B on garbled radio fragments: on-board speed vs accuracy | NEXT (measure) |

**The one line for Moss:** "Every plane runs an agent, and Moss is its memory, on board, in the middle of every voice turn, in about a millisecond."

**The startup line Moss liked:** Unstep isn't one feature, it's the ecosystem: an agent per aircraft, a memory per agent, a team of agents on the ground, and the controller supervising.

---

## 3. Elastic: from "a rulebook in a search index" to the tower's agent platform

Elastic's feedback: ingesting manuals is fine but not their best use. What Elastic pushes in 2026:
- **Agent Builder** (GA, Jan 2026) and **Workflows** (YAML, event-driven, exposable over MCP) ([Agent Builder GA](https://www.elastic.co/search-labs/blog/agent-builder-elastic-ga), [Elastic Agent Builder](https://www.elastic.co/elasticsearch/agent-builder));
- **Agent Builder generating Kibana dashboards from ES|QL**;
- **ES|QL search commands:** `COMPLETION`, `RERANK` (GA 9.4) and `FUSE` (hybrid) ([ES|QL for search](https://www.elastic.co/docs/solutions/search/esql-for-search), [RERANK](https://www.elastic.co/docs/reference/query-languages/esql/commands/rerank));
- **`LOOKUP JOIN`**;
- **Jina embeddings and rerankers on the Elastic Inference Service** ([Jina rerankers on EIS](https://www.elastic.co/search-labs/blog/jina-rerankers-elastic-inference-service)).

**What we already use (LIVE on our Elastic Cloud project, 2026-10-24):**
- 4 Agent Builder agents, 7 ES|QL / index-search tools and 2 Workflows;
- the Compliance agent cited FAA ¶3-7-4 on real stepped-on calls;
- the percolator matched a readback in 3.0 ms;
- the ES|QL safety panel answers in 1.1–1.5 s;
- the "ask the audit trail" agent answered correctly with its query shown.

**Going deeper (NEXT, ranked by demo value).** Every item uses a flagship feature, and each is a real tower job, not a document dump.

| # | Flagship feature | Tower job it does | Demo moment |
| --- | --- | --- | --- |
| E1 | **Workflows, event-driven** | Every blocked call, wrong readback and missing readback triggers a workflow automatically (today only the blocked call does). The workflow is the "ground crew" | The feed fills with Elastic rows without anyone asking |
| E2 | **Agent Builder → Kibana dashboard** | "Build me a safety dashboard for this shift": the audit agent writes the ES\|QL and saves a real Kibana dashboard | One sentence, then a real dashboard opens |
| E3 | **ES\|QL `COMPLETION`** | The shift handoff briefing written by ES\|QL itself from the last hour's events, every line linked to its events | The "Shift briefing" button above the feed |
| E4 | **`RERANK` + `FUSE` with Jina on EIS** | FAA rule retrieval: hybrid (BM25 + Jina embeddings), reranked by jina-reranker-v3. The citation gets more precise, and the score is shown | The decision card shows the rule with its rerank score |
| E5 | **Multilingual semantic search (Jina embeddings)** | Transcripts in Spanish, Hindi and French (our pilots' languages) are searchable in the same index | "Show me every blocked call" also finds the Hindi ones |
| E6 | **`LOOKUP JOIN`** | Every event is enriched with a lookup index of aircraft (type, operator) and runways (status, hold-short points) | The panel says "blocked calls by runway", not just by callsign |
| E7 | **Machine learning anomaly detection** (check availability on Serverless) | Flags a frequency whose blocked-call rate spikes, for example a stuck mic or overload | A red "Anomaly" row in the feed |
| E8 | **Workflows exposed over MCP** | Any MCP client (an IDE, Claude) can ask the tower's audit trail. A safety officer works from their own tools | One question from Claude Desktop answered from Elastic |

**Already rejected and why (unchanged):**
- CHANGE_POINT: needs a higher license on our tier.
- `waitForInput`: the gateway stays the only enforcement point.
- E-4 automatic "say again": Rishit's decision.

**The one line for Elastic:** "Elastic is the tower's agent platform: every event triggers a workflow, agents cite the rule and write the shift briefing, and the safety office gets dashboards from one sentence, while the controller decides."

---

## 4. How the three fit (for any judge)

```
pilot speaks ──► Cartesia Ink (hears, live captions) ──► Moss (plane's memory, ~1 ms) ──► Cartesia Sonic (speaks privately)
                         │
                         └──► every event ──► Elastic (stores, triggers workflows, agents cite rules, briefings, dashboards)
                                                         │
                                                         └──► "Agents at work" feed ──► the controller supervises and decides
```

Sources: [Cartesia changelog 2026](https://docs.cartesia.ai/changelog/2026), [Cartesia Sonic-3.5 + Ink-2](https://runtimewire.com/article/cartesia-sonic-35-ink-2-voice-agent-benchmarks), [Sonic-3.6](https://slator.com/cartesia-launches-text-to-speech-model/), [Moss voice agents](https://www.moss.dev/use-cases/voice-agents), [Moss docs](https://www.moss.dev/llms-full.txt), [Moss YC launch](https://www.ycombinator.com/launches/Oiq-moss-real-time-semantic-search-for-conversational-ai), [Elastic Agent Builder GA](https://www.elastic.co/search-labs/blog/agent-builder-elastic-ga), [Elastic Agent Builder](https://www.elastic.co/elasticsearch/agent-builder), [ES|QL for search](https://www.elastic.co/docs/solutions/search/esql-for-search), [ES|QL RERANK](https://www.elastic.co/docs/reference/query-languages/esql/commands/rerank), [Jina rerankers on EIS](https://www.elastic.co/search-labs/blog/jina-rerankers-elastic-inference-service).
