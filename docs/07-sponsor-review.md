# Sponsor Review and Benchmark

How well Unstep fits the Cartesia and Moss prize tracks (and the Elastic track), what the sponsors told us, how we compare with past winning projects, and what we should change.

| Field | Value |
| --- | --- |
| Status | Draft v0.1 |
| Last updated | 2026-10-23 |
| Related | [PRD](01-prd.md), [Mistakes and Lessons](03-mistakes-and-lessons.md), [Work Split](04-work-split.md), [Architecture](05-architecture.md), [Research](06-research.md) |

## 1. Prize Tracks

### Cartesia: Best Use of Cartesia

Voice must be core to the product, not a feature added for the demo. We must make clear what Cartesia contributes.

| Criterion (25% each) | What judges look for |
| --- | --- |
| Problem and originality | Useful, clearly scoped, thoughtfully designed |
| Use of Cartesia | Meaningfully integrated into the core experience. Voice is clear, responsive and natural |
| Execution | Main flow works. Likely edge cases handled |
| Impact and responsibility | Accessibility, privacy and responsible use considered |

They favor a strong working prototype over a large unfinished idea.

**Submission:** working demo, a 2-minute demo-first presentation (one complete user flow, then a brief problem and how we built it), a short README (setup, Cartesia features used, known limitations), and source access. No API keys or secrets in the repo.

### Moss: Best Use of Moss

Three example categories: Voice AI (agents that listen, respond and act in real time), Personal Agent, and Social Post. Unstep fits **Voice AI**.

## 2. Concerns With the Current Plan

| ID | Area | Concern | Suggested fix |
| --- | --- | --- | --- |
| S-1 | Cartesia | Cartesia only does one-way text-to-speech at the very end. Any TTS engine could replace it, so it fails "make clear what Cartesia contributes." | Use Cartesia in more of the loop. See S-2 to S-4 |
| S-2 | Cartesia | The tower transcript (task B2) is the source of truth for what was blocked (M-002), but it has no speech-to-text engine chosen. | Use Cartesia speech-to-text with key terms (callsigns, runway and taxiway names, "hold short") |
| S-3 | Cartesia | The product has no back-and-forth voice exchange. | Add a pilot readback check: the pilot reads the instruction back, Cartesia transcribes it, and the system compares it with the approved directive. On a mismatch it says "Readback incorrect" and repeats the instruction |
| S-4 | Cartesia | A synthetic voice in the headset could be mistaken for real ATC. | Pick a distinct "advisory" voice and tone, and use ATC number pronunciation ("niner", "tree", "fife") |
| S-5 | Moss | The PRD uses Moss to map GPS to a taxiway node. That is a coordinate lookup, not search, and won't impress the Moss judges. | Use Moss as shared agent memory and for local semantic search (see section 3) |
| S-6 | Moss | The PRD says Moss runs "through WebAssembly/Rust." | Check this against the Moss docs before the pitch (same lesson as M-007) |
| S-7 | Scope | Three sponsors, two developers, a ground system and an edge system, and no code yet. Judges favor a working prototype. | One flow must work every time before anything else is added (see section 6) |
| S-8 | Responsibility | No note on privacy (recording tower audio) or accessibility. | Add both to the README and the pitch |
| S-9 | Evidence | The February 2026 NTSB claim is still unsourced (M-005). | Don't lead the pitch with it until we have the report number |
| S-10 | Deliverables | No README, an empty `.gitignore`, no demo. | Add a README with the required sections, and ignore `.env` and key files |

## 3. Notes From Sponsor Conversations

From handwritten notes. Two items were hard to read and are marked.

### Moss

- Monitor the system based on what we send from the start, and give insights.
- "Take over ATC with human in loop." This matches our approval gate.
- Shared storage between agents, including the edge agents in the plane.
- "Ingestion indexing (stops cloud and replaces it)." The plane indexes data locally, so Moss keeps working when the cloud link is gone. This answers M-003. (First word unclear, read as "ingestion".)
- Context handoff and a shared space in Moss, **but no conversation between agents**. Agents share context through Moss, not by messaging each other.

### Cartesia

- Text-to-speech, with fine-tuning for numbers (ATC pronunciation).
- "ATC practice": a possible pilot radio-practice mode, which fits the "live coach" idea in the track.
- Judging: original, use of it, impact, execution.
- Speech-to-text: add key terms so unusual words transcribe correctly.
- Cut-off time is understood by Cartesia (end-of-speech detection). This could help detect a blocked transmission, not just transcribe it.
- Try different voices.

### Elastic

- Depth of implementation matters.
- Write up the implementation.
- Workflows (endpoint, trigger, action) are a good starting point.

### Other

- "Slack (Grant)": meaning unclear. To confirm.

### What the notes change

| Area | PRD today | After the notes |
| --- | --- | --- |
| Moss | GPS to taxiway node lookup | Shared agent memory and context handoff, local indexing that replaces the cloud when offline, monitoring and insights |
| Agent messaging | WebSocket messages between halves | Agents hand context through a shared Moss space, with no agent-to-agent conversation |
| Cartesia | TTS at the end only | Speech-to-text with key terms, cut-off detection, ATC number pronunciation, voice choice, readback check or practice mode |
| Elastic | Hybrid search plus audit | Same, run as an Elastic Workflow, with a written explanation of the implementation |

## 4. Past Winners

Public data is thin, especially for Moss. These are the winners we could confirm.

| Sponsor | Event | Winner | What it did | Why it won |
| --- | --- | --- | --- | --- |
| Cartesia | Cal Hacks 11.0 (1st) | SpeakEasy | Language learning that keeps the learner's own voice and intonation | Clear problem, distinctive use of voice |
| Cartesia | AGI House SF (1st) | Form Wizard Pro | Turns any web form into a voice-guided experience | Accessibility |
| Cartesia | AGI House SF (3rd) | SheBeTalking | Uses Sonic for different speaking styles and tones | Practical and culturally sensitive |
| Cartesia | Daily hackathon (1st) | Stella | Voice shopping assistant with browsing and virtual try-on | Integrated several services well |
| Cartesia | Daily hackathon (2nd) | Foul-mouthed Robot Chef | Raspberry Pi robot arm with a sassy voice | Physical hardware and a memorable personality |
| Elastic | Cal Hacks 12.0 (1st) | AgentOverflow | Hybrid search over validated fixes, exposed to LLMs through Agent Builder and MCP | Elastic is the core memory layer, not an add-on |
| Elastic | Cal Hacks 12.0 (2nd) | MarketMind | Six Agent Builder agents, one per index, with complex ES\|QL | Depth of Elastic use |
| Moss | YC Halloween hackathon (1st) | Intella | AI browser assistant built on Moss | No details published |
| Voice (general) | SF Voice Agent Hackathon | Voxy, Podweaver | Zero-code voice agents ("the platform just works"); voice cloning with 250 ms timing precision | Reliability, and a measured latency number |

We found no winning ATC or aviation voice project. The nearest were a university ATC simulator and a conference workshop talk.

## 5. Unstep Against the Winners

| Criterion | What winners did | Unstep today | Gap |
| --- | --- | --- | --- |
| Originality | Language learning, forms, shopping, a cooking robot | Blocked ATC radio calls, with no prior project found | **Strong advantage** |
| Voice is the product (Cartesia) | In every Cartesia winner, the product is the voice interaction | Cartesia only speaks the final directive | **Big gap.** Fix with S-2 to S-4 |
| Distinctive voice use | SpeakEasy kept the user's voice; SheBeTalking varied tone | Not planned | Distinct advisory voice and ATC number pronunciation |
| Moss in a live loop | Moss sprint projects use in-process retrieval at about 5 ms during a voice conversation | GPS lookup, or shared memory per the notes | Shared memory is more original, but show a measured Moss latency on screen |
| Elastic depth | AgentOverflow made Elastic the memory layer; MarketMind ran six agents with ES\|QL | Hybrid search over FAA JO 7110.65 plus an ES\|QL audit trail | **Good fit.** Build agents in Agent Builder, run them as a Workflow, show live ES\|QL |
| "It just works" | Judges praised reliability and measured numbers | No code yet | **Biggest risk.** Get M2 working first |
| Memorable demo | The robot chef had hardware and personality | Pi is on hold | A real headset playing only in the left ear, with a squeal sound effect |
| Responsibility | Accessibility, cultural sensitivity | Human approval gate, no autonomous action | **Advantage.** Add privacy and accessibility notes (S-8) |

## 6. Recommendations

1. **Make the Cartesia part a two-way voice exchange.** Transcribe tower audio with key terms, detect cut-offs, speak the directive, then check the pilot's spoken readback.
2. **Show numbers on screen during the demo:** Moss lookup time, Cartesia time to first audio, and end-to-end time without the human.
3. **Use Elastic like the Cal Hacks 12.0 winners:** Agent Builder agents run as a Workflow, hybrid search for the rule citation, and live ES\|QL audit queries.
4. **Cut scope to one flow that works every time:** blocked clip, transcript, directive card, Approve, spoken in the left ear, readback verified.
5. **Lead the pitch with originality and responsibility,** which past winners had less of.

## 7. Open Items

- Confirm what "Slack (Grant)" means.
- Decide whether "ATC practice" is a feature or just an idea someone mentioned.
- Fold the accepted changes into the PRD, architecture and work split.

## Sources

- [Cartesia blog: Hacktober winners](https://www.cartesia.ai/blog/hacktober)
- [Elastic: Agent Builder Cal Hacks 12.0 projects and learnings](https://www.elastic.co/search-labs/blog/agent-builder-projects-learnings-cal-hacks-12-0)
- [AssemblyAI: SF Voice Agent Hackathon highlights](https://www.assemblyai.com/blog/voice-agent-hackathon-sept-19)
- [Moss on X](https://x.com/usemoss)
- [Garry Tan on the Moss hackathon](https://x.com/garrytan/status/2060354064056201707)
- [ryan-voice-agent (Moss sprint project)](https://github.com/ryanebenezer01-sketch/ryan-voice-agent)
- [MHacks 2024 Devpost](https://mhacks-2024.devpost.com/)
- [Cal Hacks 11.0 Devpost](https://cal-hacks-11-0.devpost.com/)
- [Cal Hacks 12.0 Devpost](https://cal-hacks-12-0.devpost.com/)
- [KFUPM ATC simulator](https://teamdesign.kfupm.edu.sa/projects/2582/)
- [DevFest SF 2025](https://gdg.community.dev/events/details/google-gdg-san-francisco-presents-devfest-san-francisco-x-fremont-2025/)
