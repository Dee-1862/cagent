# Advice: What Unstep Is, How to Win the Tracks, and How to Use Moss and Cartesia

Rishit's recommendations after reviewing PRD v0.2, the sponsor notes and the Moss and Cartesia docs. Each section says what we think and why. Nothing here changes the PRD yet. We agree on it first, then fold it in.

| Field | Value |
| --- | --- |
| Status | Proposal v0.1 |
| Last updated | 2026-10-23 |
| Related | [PRD](01-prd.md), [Architecture](05-architecture.md), [Work Split](04-work-split.md), [Sponsor Review](07-sponsor-review.md), [Mistakes and Lessons](03-mistakes-and-lessons.md) |

## Summary

1. **The idea:** Unstep makes sure no ATC instruction is lost or misheard. It is not collision avoidance and not an AI that runs ATC.
2. **The scope:** blocked transmission recovery (A), plus readback checking (B), plus a thin monitoring agent. A + B is the product. The monitoring agent is there because the Moss and Elastic judges reward multi-agent depth.
3. **Moss is not a message bus.** Use it as fast local memory for each agent, with handoff at clear points. Send live messages over WebSocket.
4. **Cartesia's best features for us** are word timestamps (to highlight exactly which words were blocked), key terms, PTT-driven finalize, turn events for interruption, and pronunciation dictionaries.
5. **Fix three claims:** "collision" for radio overlap, "under 90 ms" as our latency, and Cartesia "cut-off detection" as a collision detector.

## 1. What Unstep Actually Is

### 1.1 Why the idea feels hazy

The docs use **"collision" for two different things.** Most of the time it means two radio transmissions overlapping. The opening story is about a fatal **aircraft** collision. A reader can't tell which one we are solving, and neither can a judge.

The docs also carry four different ideas at once:

| # | Idea | What it means | Where it comes from |
| --- | --- | --- | --- |
| A | Blocked transmission recovery | An instruction was wiped out by radio overlap. Recover it, get approval, deliver it | PRD core since v0.1 |
| B | Readback checking | The pilot heard it but read it back wrong. Catch that | Added from the sponsor review |
| C | Agentic ATC co-controller | Agents monitor all traffic and draft instructions, a human approves | Moss sponsor note: "take over ATC with human in loop" |
| D | Collision avoidance | Stop aircraft hitting each other | Only the NTSB story |

### 1.2 What we think the product is

**Unstep makes sure every ATC instruction is heard, and heard correctly.**

Voice communication between tower and pilot fails in two ways:

1. **Not heard.** The call is stepped on (A).
2. **Misheard.** The pilot reads back something different from what was said (B).

A and B use the same pipeline: transcribe the tower, transcribe the cockpit, compare, get human approval, speak the correction. So they are one product, not two features. Agents, Elastic and Moss are how it works, not what it is.

### 1.3 What it is not

- **Not collision avoidance (D).** That is radar, TCAS and runway incursion detection, a different and much harder product. We prevent the communication failure that can lead to a collision. We should say exactly that and nothing more.
- **Not an AI that runs ATC (C).** It sounds unsafe, contradicts our own "no autonomous action" rule, and can't be built in a weekend. C is the vision slide, not the demo.

### 1.4 Wording fixes

- Use "stepped-on" or "blocked transmission" for radio overlap. Use "collision" only for aircraft.
- One-line pitch: **"Unstep: no ATC instruction lost or misheard."**
- Vision line: "The first step toward an AI co-controller that keeps humans in charge."

## 2. Benchmark Against the Tracks

We are going for track wins, not the overall prize. Track judges are sponsor engineers. They ask whether their tool is the core of the product and whether we used it in depth. Polish and broad appeal matter less than for the overall prize.

### 2.1 Cartesia

**Criteria (25% each):** problem and originality, use of Cartesia, execution, impact and responsibility.

**Past Cartesia track winners:** SpeakEasy (Cal Hacks 11.0, keep your voice in another language), Form Wizard Pro (voice-guided forms, accessibility), SheBeTalking (speaking styles and tones), Stella (voice shopping assistant). In every one, **the voice interaction is the product**, not a feature on top.

| Criterion | A: Blocked | B: Readback | **A + B** | C: Agentic ATC | D: Collision |
| --- | --- | --- | --- | --- | --- |
| Problem and originality | Strong | Strong | **Strong** | Vague | Misleading |
| Use of Cartesia | TTS plus tower STT | Two-way voice: listen, compare, respond | **STT on both sides, word timestamps, key terms, TTS, interruption** | Mostly TTS | Minimal |
| Execution | Easy | Easy | **Doable** | Hard | Not buildable |
| Impact and responsibility | Human approval | Accessibility | **Both, plus no voice cloning and a distinct advisory voice** | Judges worry about safety | Over-claims |
| **Rank** | 2 | 3 | **1** | 4 | n/a |

**Why A + B wins here:** without B we are "just TTS at the end," and every past winner beat that. B turns the product into a real back-and-forth voice exchange.

**Must show the Cartesia judges:** a wrong readback caught live and corrected by voice, and the blocked words highlighted on screen using STT word timestamps.

### 2.2 Moss (Voice AI category)

**Criteria:** voice agents that listen, respond and act in real time. Moss's own pitch is in-process search inside the voice loop. Its docs also push shared context between agents and live-call sessions.

**Past Moss winners:** Intella (YC Halloween hackathon, AI browser assistant, no details published) and Moss sprint projects using in-process retrieval at about 5 ms. Public data is thin, so we lean on what Moss's docs emphasize.

| Criterion | A | B | A + B | **A + B + monitoring** | C |
| --- | --- | --- | --- | --- | --- |
| Search inside the voice loop | Yes, guess the blocked instruction | Weak, readback is a comparison | Yes | **Yes** | Yes |
| Live session context | Flight session | Flight session | Yes | **Flight and frequency sessions** | Yes |
| Shared memory between agents | Thin | Thin | Thin | **Cockpit, ground and monitor agents** | Strong |
| Visible speed on screen | Yes | No | Yes | **Yes** | Yes |
| **Rank** | 3 | 5 | 2 | **1** | Strong but unbuildable |

**Why we add a monitoring agent:** A + B alone uses Moss for one search, which is thin for a Moss judge. A small slice of C fixes it: an agent indexes every transmission on the frequency into a Moss session and raises insights, for example "N123AB has had 2 blocked calls in 5 minutes" or "readback errors on this frequency are climbing." This is exactly the sponsor note "monitor systems based on stuff we send from start, and give insights." It only reads data the pipeline already produces and never touches the live path, so it is cheap and safe.

### 2.3 Elastic

**What the sponsor told us:** depth of implementation, a written explanation, and start from Workflows (endpoint, trigger, action).

**Past Elastic track winners (Cal Hacks 12.0):** AgentOverflow (1st) made Elastic the memory layer with hybrid search and Agent Builder over MCP. MarketMind (2nd) ran six Agent Builder agents with complex ES|QL.

| Criterion | A | B | **A + B + monitoring** | C |
| --- | --- | --- | --- | --- |
| Agent Builder depth | 2 agents | 1 agent | **3 to 4: intercept, compliance, readback auditor, frequency monitor** | Many |
| Hybrid search as the core | FAA rule citation | FAA readback rules | **Both** | Yes |
| Workflow orchestration | Yes | Yes | **Yes** | Yes |
| ES\|QL depth | Audit trail | Audit trail | **Audit plus live stats: error rate by frequency, blocked calls per hour** | Strong |
| **Rank** | 3 | 4 | **1** | Best on paper, too big |

### 2.4 Result

| Track | Best version | Must-have demo moment |
| --- | --- | --- |
| Cartesia | A + B | Wrong readback caught by voice; blocked words highlighted |
| Moss | A + B + monitoring | Blocked instruction guessed locally with search time on screen; agents sharing context through Moss |
| Elastic | A + B + monitoring | Workflow runs 3 to 4 agents; FAA paragraph cited; live ES\|QL stats |

**Build A + B plus a thin monitoring agent.** One 2-minute demo covers all three. Also prepare a 30-second version per track that leads with that sponsor's moment.

## 3. Moss: What It Does Well and How We Should Use It

### 3.1 What Moss is good at (from its docs)

| Strength | Detail |
| --- | --- |
| In-process search | The index is pulled into memory and queried locally, with no network hop. Vendor benchmark: about 3 ms median, 5 ms p99 on 100k docs on an M4 MacBook, embedding included. Every result has `time_taken_ms` |
| Hybrid search | `alpha` blends meaning and keyword. 1.0 is meaning only, 0.0 is keyword only, default 0.8 |
| Metadata filters | `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`, `$nin`, `$near`, combined with `$and` and `$or` |
| Sessions | `client.session(name)` returns a local `SessionIndex`. `add_docs`, `query`, `delete_docs` and `get_docs` run on the device, including embedding, in about 1 to 10 ms. `save_to_disk` and `load_from_disk` keep a local copy |
| Long-term plus short-term context | Moss's recommended live-call pattern: a permanent index loaded once with `load_index`, plus a session per call that collects the live transcript. Query both each turn |
| Cross-agent handoff | One agent calls `push_index()`. Another opens `session(same_name)` and continues with the full history, on any machine |

### 3.2 Limits that change our design

| Limit | Why it matters for us |
| --- | --- |
| Handoff goes through Moss Cloud | Readers only see the last *completed* push. It is not instant |
| `push_index()` creates or **replaces** the whole cloud index | If the cockpit and the ground push to the same index, the last writer wins and the other's data is lost |
| `load_index(auto_refresh=True)` polls every **300 seconds** by default | Far too slow to deliver an approved directive |
| `session()` validates credentials with the cloud when it opens | Open sessions before going offline. Local operations work after that |

**Conclusion:** PRD v0.2 uses the shared Moss space as the delivery path for messages like `ApprovedDirective`. That doesn't fit how Moss works. Use Moss as each agent's fast local memory, with handoff at clear points (end of an event, end of a flight), **one writer per index**. Send live messages over WebSocket. This still matches the sponsor note "context handoff and shared space, but no convo between," and it is how Moss's own docs describe handoff.

### 3.3 Proposed Moss indexes

| Index | Kind | Contents | Writer | Readers |
| --- | --- | --- | --- | --- |
| `airport-<ICAO>` | Long-term, `load_index` before flight | Runways, taxiways, NOTAMs, local procedures, standard phraseology, key paragraphs of FAA JO 7110.65 | Pre-flight setup | Cockpit, ground |
| `flight-<callsign>` | Session on the cockpit | Every clearance this aircraft received, its readbacks and events | Cockpit only | Ground and audit, after `push_index()` |
| `freq-<frequency>` | Session on the ground | Every tower transcript on the frequency, with callsign and timestamp metadata | Ground only | Ground agents, monitoring agent |

### 3.4 Main use 1: guess the blocked instruction locally

When a transmission is stepped on, the cockpit searches with the fragment it did hear against its flight session and the airport index:

```python
hint = await flight.query("short three", QueryOptions(
    top_k=3, alpha=0.4,  # lean on keywords, numbers matter
    filter={"$and": [{"callsign": {"$eq": "N123AB"}}, {"type": {"$eq": "clearance"}}]}))
airport = await client.query("airport-KXXX", "hold short runway 33", QueryOptions(top_k=3))
```

The pilot immediately hears: "Advisory. Transmission blocked. Likely hold short Runway 33. Awaiting controller." The approved version still comes from the ground.

**Why this is the right Moss use:** it is search inside the voice loop, it takes a few milliseconds, it works without a network (answers M-003), and the time can be shown on screen.

### 3.5 Main use 2: match the tower transcript on the ground

The intercept agent filters the frequency session by callsign and time window:

```python
await freq.query("instruction to N123AB", QueryOptions(top_k=1,
    filter={"$and": [{"callsign": {"$eq": "N123AB"}}, {"ts": {"$gte": event_ts - 5}}]}))
```

### 3.6 Monitoring agent

Reads `freq-<frequency>` and the pushed `flight-<callsign>` sessions and raises insights such as repeated blocked calls or rising readback errors. Insights go to the dashboard and Elastic. It never sends anything to the cockpit.

### 3.7 What Moss should not do

- Deliver live messages. Use WebSocket.
- Compare a readback with a directive. That is a slot comparison (callsign, action, runway), not search.

### 3.8 Still to verify

- Exact syntax of the `$near` filter.
- Whether Elastic Agent Builder can call Moss's MCP server. If not, the ground agents read events from an Elastic index and Moss stays on our own services.

## 4. Cartesia: How to Use It

### 4.1 Speech-to-text (Ink-2)

Two endpoints, used for different jobs:

| Endpoint | How a turn ends | Our use | Why |
| --- | --- | --- | --- |
| `wss://api.cartesia.ai/stt/websocket` (manual) | We send `finalize` | **Tower audio** | Radio already has an exact end of turn: PTT release. Send audio while PTT is held and `finalize` on release. More reliable than guessing pauses |
| `wss://api.cartesia.ai/stt/turns/websocket` (auto) | Model emits `turn.start`, `turn.update`, `turn.eager_end`, `turn.end` | **Pilot readback** | `turn.end` gives the readback text. `turn.start` lets the pilot interrupt the advisory voice |

**Key terms.** Query parameter `keyterm`, up to 100 terms and 1200 characters, set at connect time and not changeable mid-stream (reconnect when the callsign list changes). Most important first: callsigns (`N123AB`, `Cessna 1-2-3`), `hold short`, runway designators (`Runway 33`, `Runway 28L`), taxiway names, `line up and wait`, `cleared for takeoff`, `niner`, `tree`, `fife`. Cartesia reports 93.8% keyword recall on its own benchmark and names airline vocabulary as a target. Ink-2 is English only, which suits ATC.

**Turn tuning for readbacks.** `turn_end_threshold` (0.05 to 0.5) and `turn_end_timeout_ms` (640 to 11200). Readbacks are short, so close turns quickly. These can be changed mid-stream with `{"type": "config", "turn": {...}}`.

**Word timestamps.** Manual-mode transcripts include `words` with `start` and `end`. The detector knows when the overlap happened, so we can highlight exactly which words were lost: "Cessna 1-2-3, ~~hold short Runway 33~~". This is the clearest on-screen proof of what Cartesia contributes.

### 4.2 Replace "cut-off detection" with transcript comparison

Turn detection finds pauses, not overlaps. During a stepped-on call the cockpit hears a squeal, not speech, so we should not present Cartesia as a collision detector.

Instead, transcribe both sides and compare:

| Side | Transcript |
| --- | --- |
| Tower | "Cessna 1-2-3 hold short Runway 33" |
| Cockpit | "Cessna 1-2-3 [static]" |
| Difference | "hold short Runway 33" was blocked |

This is a real, defensible use of Cartesia STT and it drives both A and B.

### 4.3 Text-to-speech (Sonic)

`wss://api.cartesia.ai/tts/websocket`, `model_id: "sonic-3.6"`, `cartesia_version: 2026-08-14`. API key in the `X-API-Key` header on the server only. The browser dashboard gets short-lived `access_token`s.

```json
{
  "model_id": "sonic-3.6",
  "context_id": "evt-123",
  "transcript": "Advisory. Cessna one two tree, transmission blocked. Hold short runway tree tree. Read back.",
  "voice": { "id": "<advisory voice id>" },
  "output_format": { "container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000 },
  "continue": false,
  "add_timestamps": true,
  "pronunciation_dict_id": "<atc dictionary id>",
  "generation_config": { "speed": 1.1, "volume": 1.2, "emotion": "calm" }
}
```

| Feature | How we use it | Why |
| --- | --- | --- |
| ATC numbers | Convert in our code first ("33" to "tree tree", "9" to "niner"). Then a pronunciation dictionary (JSON list of `{text, pronunciation}`, sounds-like or IPA in `<<k\|ɑ\|...>>` form, passed as `pronunciation_dict_id`, Sonic 3 only) so "niner" and "tree" sound right | Our own conversion is predictable. The dictionary fixes how the words are said |
| Advisory voice | A stock voice clearly different from the tower clip. `emotion` only offers `neutral`, `calm`, `angry`, `content`, `sad`, so use `calm` with slightly higher `speed` and `volume` | Real ATC is calm, not alarmed. The voice must never pass as ATC |
| Left ear only | Sonic outputs mono. We write it to the left channel and silence the right | Keeps the advisory separate from the radio |
| Interruption | On readback `turn.start`, send `{"context_id": "evt-123", "cancel": true}` | Responsiveness is a Cartesia judging point |
| Word timestamps | `add_timestamps: true` drives word-by-word highlighting on screen | Accessibility for pilots with hearing difficulty, and a visible demo moment |
| Offline fallback | Pre-generate "Advisory. Transmission blocked, request say again" with Cartesia and store the file | Answers M-004 |

### 4.4 Latency claim

Cartesia states under 90 ms time to first audio for the model. Third-party measurements of Sonic 3 including network are about 166 to 190 ms. **Change "under 90 ms" in the PRD to our own measured number** and show it on screen. Quoting the vendor figure as ours is the same mistake as M-001.

### 4.5 Responsibility point

Cartesia can clone voices. **We deliberately do not clone the controller's voice.** A synthetic voice must never pass as real ATC. Say this in the pitch, because it scores on the responsibility criterion.

## 5. Concerns With PRD v0.2

| # | Concern | Why | Fix |
| --- | --- | --- | --- |
| 1 | Moss shared space used as the message path | Handoff is cloud-based, push replaces the index, auto-refresh polls every 300 s | WebSocket for live messages, Moss for memory and handoff (section 3) |
| 2 | M2 depends on task A5 (Moss shared space) | An unconfirmed vendor behavior blocks the first milestone | Build M2 on WebSocket, add Moss after |
| 3 | Elastic agents "reading context from Moss" | Agent Builder agents run inside Elastic. Reading Moss needs a custom or MCP tool we haven't confirmed | Also write each event to an Elastic index |
| 4 | Cartesia "cut-off detection" | Turn detection finds pauses, not overlaps, and the cockpit hears static | Replace with transcript comparison (section 4.2) |
| 5 | "Under 90 ms" | Vendor model figure, not our system | Measure and show our own number |
| 6 | "Collision" used for radio overlap | Confuses the idea with collision avoidance | Wording fixes (section 1.4) |
| 7 | Scope | Dev A has 10 tasks, Dev B has 9, plus shared work | Cut list below |
| 8 | Leftovers | Owner names still `_name_`, "Slack (Grant)" unknown, confidence method and FAA paragraph still TBD (M-008) | Fill in |

## 6. Cut List

In priority order, cut these first if time runs short:

1. Raspberry Pi (already on hold)
2. ATC practice mode
3. Cartesia cut-off detection (replaced by transcript comparison anyway)
4. Offline mode beyond the pre-generated alert
5. Elastic Workflow, falling back to direct agent calls (last resort, it costs Elastic points)

Never cut: the readback check, the blocked-word highlight, the Moss search time on screen, the human approval step.

## 7. Demo Flow (2 minutes)

1. **Play the squeal for 5 seconds.** "That was an instruction to stop before a runway, and the pilot just lost it." Sound explains the problem faster than slides.
2. Dashboard: tower transcript with the blocked words highlighted (Cartesia word timestamps).
3. Cockpit: "Likely hold short Runway 33," with Moss search time on screen.
4. Controller approves. The Workflow ran the agents and the card cites the FAA paragraph (Elastic).
5. Advisory voice in the left ear, words highlighted as spoken, first audio time on screen (Cartesia).
6. Pilot reads back wrong. Caught, corrected by voice. Reads back right. Confirmed.
7. Monitoring panel and a live ES|QL query: blocked calls and readback errors on this frequency.
8. Closing: "No instruction lost or misheard. Humans stay in charge."

## 8. Next Steps

| # | Step | Owner |
| --- | --- | --- |
| 1 | Agree on A + B + monitoring as the scope | Both |
| 2 | Fold sections 1, 3 and 4 into the PRD, architecture and work split | Both |
| 3 | Switch M2 transport to WebSocket | Both |
| 4 | Add the monitoring agent task and the readback auditor agent | Dev B |
| 5 | Verify `$near` syntax and Agent Builder to Moss access | Dev A, Dev B |
| 6 | Build the ATC key term list and pronunciation dictionary | Dev A |
| 7 | Replace "under 90 ms" with measured numbers once we have them | Both |

## Sources

**Moss**
- [Moss GitHub README](https://github.com/usemoss/moss)
- [Moss: voice agents use case](https://www.moss.dev/use-cases/voice-agents)
- [Moss docs index](https://docs.moss.dev/llms.txt)
- [Core concepts](https://docs.moss.dev/docs/start/core-concepts.md)
- [Python API](https://docs.moss.dev/docs/reference/python/api.md)
- [Sessions](https://docs.moss.dev/docs/integrate/sessions.md)
- [Real-time local indexing](https://docs.moss.dev/docs/build/real-time-local-indexing.md)
- [Live-call context](https://docs.moss.dev/docs/build/live-call-context.md)
- [Cross-agent handoff](https://docs.moss.dev/docs/build/cross-agent-handoff.md)

**Cartesia**
- [Keyterm prompting docs](https://docs.cartesia.ai/use-the-api/stt/keyterms)
- [Blog: keyterm prompting and turn detection](https://www.cartesia.ai/blog/keyterm-prompting)
- [STT WebSocket (manual)](https://docs.cartesia.ai/api-reference/stt/websocket)
- [STT turns WebSocket (auto)](https://docs.cartesia.ai/api-reference/stt/turns/websocket)
- [TTS WebSocket](https://docs.cartesia.ai/api-reference/tts/websocket)
- [Custom pronunciations](https://docs.cartesia.ai/build-with-cartesia/sonic-3/custom-pronunciations)
- [Pricing](https://docs.cartesia.ai/pricing)
- [invideo: Sonic 3 measured latency](https://invideo.io/blog/cartesia-sonic-ai-voice/)

**Past winners**
- [Cartesia blog: Hacktober winners](https://www.cartesia.ai/blog/hacktober)
- [Elastic: Agent Builder Cal Hacks 12.0 projects](https://www.elastic.co/search-labs/blog/agent-builder-projects-learnings-cal-hacks-12-0)
- [Moss on X (Intella)](https://x.com/usemoss)
- [Dylan's blog: 1st place at Cal Hacks 12.0](https://blog.dylanlu.com/cal-hacks-12/)
