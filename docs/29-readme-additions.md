# README additions: pictures, and the three sponsors

Ready to paste into `README.md`. Two parts: **A. Unstep in pictures** (after "One complete flow") and **B. For the sponsors** (before "Measured results"). The README is Rishit's file, so nothing here has been applied to it; see "How to apply" at the end.

| Field | Value |
| --- | --- |
| Status | Draft v0.1, 2026-10-25 |
| Written for | Judges and sponsor representatives reading the README |
| Images | `docs/img/readme/`, real screenshots from our own runs (offline build, fake speech) |
| Numbers | All from the README, our docs, or git timestamps. Nothing new was invented. Grades: LIVE (measured on the real service), SIMULATED (scripted traffic, labelled), SOURCED |

---

## A. Unstep in pictures

*Paste after "3. One complete flow (the demo)".*

All screenshots are from our offline demo build (fake speech, so no API calls). The flow, the agents and the screens are the real code; the speech and timing numbers are in section 9.

### The tower console

![The ATC console: a 3D airport, the join QR code, and the agents panel](docs/img/readme/console-idle.png)

The controller's screen. The 3D airport shows every plane. The **QR code** (bottom left) is the one way in: a judge or customer scans it and their phone becomes a plane. The panel on the right is "Agents at work".

### A call gets stepped on

![A blocked call: the tower and a plane talk at once, and the console shows what the agents did](docs/img/readme/console-call-2.png)

The tower and Plane A talked at the same time, so both lanes at the bottom say **TALKED OVER**. The headline says what happened in plain English. The card on the right is the part that needs a person: **Approve and send** or **Reject**. Below it, the agents list what they did: the Elastic geo lookup (where the plane was), the Cartesia recovery agent (told Plane A its call was blocked), the policy agent (asked the controller to decide), the ground agents (drafted the fix) and the cockpit agent.

### The team of agents

![The team strip: the controller, the orchestrator and five agents](docs/img/readme/console-team.png)

One person, one fixed workflow, five agents. The orchestrator is an Elastic Workflow with written-down steps: it sequences the agents and decides nothing. Only the controller approves anything that moves a plane.

### A phone is a plane

| Join | In the air |
| --- | --- |
| ![The pilot app join screen](docs/img/readme/pilot-join.png) | ![The pilot app with the hold to talk button](docs/img/readme/pilot-flying.png) |

Scan the QR, tap once, hold the big button to talk. The card says what to say, so a judge who has never heard a radio call can do it.

### A Raspberry Pi is a plane too

![The Raspberry Pi microphone test: a live level bar, and a warning when it clips](docs/img/readme/pi-mic-test.png)

A Raspberry Pi 4 with a Logitech webcam microphone joins the same room as a pilot (`scripts/pi_plane.py`). The level bar shows the microphone is on and working, and the tool warns when the signal is too loud. This capture is from before the client began setting the microphone level itself, which is why it reports clipping. Only the Pi's microphone and network are in use today; the plane's decisions still run on the hub.

---

## B. For the sponsors

*Paste before "9. Measured results".*

### Built in a day

Every dataset and index below was created from scratch during the hackathon. First commit: **2026-10-23 21:00 PDT**.

| What landed | When (PDT) | Hours after the first commit |
| --- | --- | --- |
| Airport index script (Moss reference data, 8 documents) | 2026-10-24 00:12 | 3.2 |
| Elastic deploy script (agents, tools, workflows) | 2026-10-24 20:36 | 23.6 |
| FAA rulebook ingest (52 JO 7110.65 paragraphs) | 2026-10-24 21:07 | 24.1 |
| Traffic simulator: 500 labelled calls, 157 stepped on (simulated) | 2026-10-24 23:15 | 26.3 |
| **State at 2026-10-25 06:38** | 339 commits, 618 tests | 33.6 |

By then: **8 Elastic agents, 9 tools and 7 Workflows**, **14 named Elastic indexes** (listed in section 7), **7 stored rules** as percolator queries (one, paragraph 3-7-2, reviewed by a person; the others are marked candidate or needs review), **6 per-aircraft Moss sessions** plus an airport index and a flight-log index. The rulebook is 52 paragraphs, not all of JO 7110.65, and only one stored rule has been reviewed by a person so far.

---

### Cartesia: the ears and the voice

**What they are.** A real-time voice AI company: Sonic (text to speech) and Ink (speech to text), built for low-latency agents. [Cartesia changelog 2026](https://docs.cartesia.ai/changelog/2026).

**What would impress them** (our reading of their feedback in [docs/21](docs/21-sponsor-features.md); they asked for a list of the features they are proud of and how we use each):
- Their models working under a hard condition: shared-radio noise, callsigns, runway numbers, and a person's safety riding on the words.
- Measured gains from their own features, not just "we used it".
- Honest findings handed back to their team ([docs/09](docs/09-cartesia-feedback.md), [docs/24](docs/24-cartesia-findings.md)), including bugs that turned out to be ours.

**What we use:** Ink-2 streaming speech to text, key-term prompting, streaming captions, Sonic streaming speech, the same voice across languages, speed control, pronunciation dictionaries, and interrupting speech when the pilot keys the mic.

| Number | Value | Grade |
| --- | --- | --- |
| Tower transcript final after release | **155 ms** (was 2,702 ms) | LIVE |
| Cockpit transcript final after release | **172 ms** | LIVE |
| Sonic first audio | **85 to 201 ms** | LIVE |
| Key terms in heavy radio noise (200 lines) | callsign **62.5% to 95.5%**, runway **81.6% to 98.5%**, word error **0.191 to 0.009** | LIVE |
| Speech to text and back, 40 ATC lines | **100%** callsign, action and runway; every wrong readback caught | LIVE |
| Languages checked for the private advisory | Spanish, Hindi, French | LIVE |

**Limits we state.** Ink-2 sends no word timestamps and no interim results. Cartesia has an on-device Sonic in private beta ([Cartesia on-device](https://cartesia.ai/blog/on-device)); we use the cloud API and are not on it yet.

---

### Moss: each aircraft's memory

**What they are.** Real-time semantic search that runs inside an agent's own process, built for the speech, retrieval, language model, speech loop of voice agents. [Moss voice agents](https://www.moss.dev/use-cases/voice-agents).

**What would impress them** (from their feedback in [docs/21](docs/21-sponsor-features.md): they liked the startup angle, "a whole ecosystem", and wanted Moss-specific features and how Moss helps the voice side made explicit):
- An agent per aircraft with a memory per agent: a real ecosystem, not one demo query.
- Moss sitting inside every voice turn: Ink hears, Moss searches the plane's memory, Sonic speaks, with no audible delay.
- Many Moss features used for real reasons, each with a number.

**What we use:** one local session per aircraft, hybrid search, metadata filters and sorting, save to disk and load on restart, a cloud flight log pushed once when a plane lands, an airport reference index, and Moss Inference for translating the advisory.

| Number | Value | Grade |
| --- | --- | --- |
| A plane's last tower call | **0.29 to 0.56 ms** | LIVE |
| Search over 6 sessions | **0 to 1 ms** | LIVE |
| Right clearance vs unrelated speech (hybrid score) | **1.0** vs **0.0** | LIVE |
| Restart from disk | **21.1 ms** (4 documents, no duplicates) | LIVE |
| Flight log read back from Moss Cloud | about **1.2 to 1.5 s** (2 documents) | LIVE |
| Moss Inference, first token | about **165 ms** warm | LIVE |

**Limits we state.** The first lookup on a cold session was 783 ms against 0.2 to 0.4 ms warm, so we warm the planes before a demo. Opening a session contacts Moss's cloud, and we have not confirmed search keeps working with the network cut after the index loads.

---

### Elastic: the agent platform

**What they are.** The Elasticsearch company; Elastic Agent Builder, Workflows and ES|QL turn a search index into agents and automations. [Agent Builder](https://www.elastic.co/elasticsearch/agent-builder), [ES|QL for search](https://www.elastic.co/docs/solutions/search/esql-for-search).

**What would impress them** (from their feedback in [docs/21](docs/21-sponsor-features.md): ingesting a rulebook is "okay", but "not the greatest use of their products"; they want flagship features):
- Agent Builder used for real jobs with limits: each agent can only call its own fixed queries, so "least privilege by tool".
- Workflows doing the sequencing, including scheduled ones, so the agents are not a black box.
- ES|QL, percolator, geo and hybrid search each solving a tower task, not a document dump.
- A person approving every decision, with every event in the audit trail.

**What we use:** 8 Agent Builder agents and 9 tools; 7 Workflows (event-driven and scheduled); ES|QL with `INLINESTATS`; the percolator for readback matching; `geo_shape` and `geo_point` for where each plane is; hybrid search with a Jina reranker for the FAA citation; an MCP server for our tools; 14 indexes.

| Number | Value | Grade |
| --- | --- | --- |
| Percolator readback match | **3.0 ms** | LIVE |
| `geo_shape` area lookup | **0 to 1 ms** | LIVE |
| Reranked FAA citation | about **1.1 s** | LIVE |
| ES|QL safety panel | **1.1 to 1.5 s** | LIVE |
| End-to-end taxi and readback suite | **28 of 28** live checks | LIVE |
| FAA JO 7110.65 paragraphs indexed | **52** | LIVE |

**Limits we state.** An Agent Builder call takes about 5 to 10 s whatever the answer, so agents stay off the pilot's critical path: the decision card goes out at once and the citation is added when it arrives.

---

### Why this is credible

- Every number carries a grade, and simulated traffic is always labelled as simulated.
- Detection on the 500-call simulated run ([docs/18](docs/18-benchmark.md)) is 91.7% of 157 stepped-on calls with 0 false events on 343 clean calls, against 0% today (the FAA found no alerting system for stepped-on calls). That compares us with having no detection at all; it is not a claim about real-world safety.
- We say what is not built or not measured: recorded sessions with real people, real air traffic recordings, and the camera-cover push to talk on the Pi.

---

## How to apply

1. **A** goes into `README.md` after section 3; copy `docs/img/readme/` with it (already in the repo).
2. **B** goes before section 9, "Measured results".
3. Since the README is Rishit's file, either he applies it, or the owner of this repo decides to apply it here.
