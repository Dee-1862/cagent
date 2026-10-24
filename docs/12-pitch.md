# Pitch Script and Judge Q&A

The 2-minute demo-first pitch, a 30-second version per sponsor, and answers to the questions judges are likely to ask. The screen and scene keys are in [Demo Design](11-demo-design.md).

| Field | Value |
| --- | --- |
| Status | Draft v0.1 |
| Last updated | 2026-10-24 |
| Run with | `python -m unstep.demo --live` (Space advances each scene) |

## 1. Rules for whoever presents

- **Let the squeal play first.** Don't introduce yourself or the project before it. Silence, sound, then one sentence.
- **Say only what the screen and audio can't.** No reading captions aloud.
- **Every number you say must be on screen**, measured in that run. Never quote a vendor figure as ours.
- **If anything fails, say "here's the recording" and play the backup video.** Don't debug on stage.
- **Name the sponsor at the moment its tech acts**, not in a list at the end.

## 1a. The hook, with a source

At the NTSB hearing on the 2025 Washington DC midair collision, the DCA tower operations manager was asked whether a controller can tell that a call was stepped on. His answer: **"There's nothing."** ([AIN, 2025-08-04](https://backend.ainonline.com/aviation-news/air-transport/2025-08-04/ntsb-dc-midair-hearing-panel-3-covers-frequency-issues)). Use this line, not the unsourced February 2026 story.

**Prior art to name if asked** (it shows we did our homework): Rohde & Schwarz DSiT warns the *ground* that calls overlapped, but doesn't recover the words or tell the pilot. The EU HAAWAII project detected readback errors in controller trials (about 80% caught, 11% false alarms) and found meaning-based comparison works better than word by word. Enhanced Radar (YC W25) does ATC transcription and after-the-fact readback review. Unstep's difference: it recovers what was lost, a human approves, and the pilot hears it privately within seconds. Details: [research-pilots-and-controllers.md](research-pilots-and-controllers.md).

**Objections real pilots and controllers raised, and our answer:**

| They said | Our answer |
| --- | --- |
| "This is not the place to guess or AI-hallucinate." | It never guesses an instruction: the words come from the controller's own transmission, the pilot's answers must quote a real record, and anything uncertain says "Say again" |
| "If it gives false warnings 5 times a day, it will be ignored." | We measure it: the clean call raises nothing. Next step is false-alarm rates on real recordings |
| "Who is liable? More work for the controller?" | The controller decides edge cases in one click or one word; routine stop/wait calls repeat the controller's own words |
| "Another voice in my head." | Chime plus "Advisory", distinct voice, left ear only, stops when the pilot speaks |

## 2. Two-minute pitch

| Time | Key | Screen | Say |
| --- | --- | --- | --- |
| 0:00 | Space | Audio mode | *(say nothing; the tower call and the squeal play)* |
| 0:07 | | | "That was a controller telling a pilot to stop before a runway. Another radio stepped on it. The pilot heard only noise, and nobody knows it was lost." |
| 0:15 | | Hint caption | "Unstep heard the squeal. **Moss** searched the cockpit's own memory in under a millisecond and found the likely instruction. It only ever guesses the safe kind: stop or wait." |
| 0:28 | Space | Controller caption | "The controller gets it in their ear and approves by voice. A human approves every directive." |
| 0:40 | Space | Directive, then readbacks | "**Cartesia** speaks it into the pilot's left ear, then listens to the readback." *(pause while 23 is caught and corrected)* |
| 1:00 | Space | Pilot questions | "And the pilot can just ask. Hands stay on the yoke." |
| 1:12 | A | Full view | "Here's what happened underneath. The words that were blocked, the hint and its source, the wrong readback, and every latency, measured live in this run." |
| 1:35 | Space | Analytics card | "**Elastic** keeps every event, so a safety office can see which frequencies keep losing calls." |
| 1:50 | Space | Close card | "In a busy US approach facility, about one in a hundred transmissions is blocked or clipped, and nothing alerts anyone. Unstep makes sure no instruction is lost or misheard, and humans stay in charge." |

The 1.16% figure is from the FAA CAMI study DOT/FAA/AM-05/19 (research RB-1). Say "about one in a hundred", not a rounder number.

## 3. Thirty-second versions

**Cartesia (lead with voice):**
"Listen." *(squeal)* "That instruction was lost. Unstep caught it, and now Cartesia speaks the fix in the pilot's left ear, then checks the readback." *(23 caught, corrected)* "Voice in and voice out for every person in the loop: Ink with ATC key terms, Sonic with our pronunciation dictionary for 'niner' and 'tree', barge-in with context cancel. First audio in about a hundred milliseconds, measured right here."

**Moss (lead with speed and memory):**
"Listen." *(squeal)* "The cockpit only heard noise. Moss searched the aircraft's own clearance history locally, under a millisecond, and found the likely instruction, with its source record on screen. Then the pilot asks 'what runway was I told to stop at?' and Moss plus Moss Inference answer with an exact quote of the approved clearance. Nothing it says can be invented: every answer must quote a real record."

**Elastic (lead with agents and analytics):**
"Listen." *(squeal)* "Every message lands in Elastic. A Workflow runs narrow agents: one matches the tower transcript, one cites the FAA rule, and the controller approves. Then ES|QL turns it into safety analytics: blocked calls and readback errors per frequency, live." *(Only claim the agents once B5 is built; until then lead with the event store and ES|QL.)*

## 4. Likely questions and honest answers

| Question | Answer |
| --- | --- |
| Does this work on real radio? | "The audio detector is proven on clips we mixed, not real VHF. The stronger signal is comparing what the tower said with what the cockpit heard. That's the confirmation, and it's what highlights the blocked words." |
| Isn't AI in the cockpit dangerous? | "Nothing reaches the pilot as an instruction without a human approving it. Before approval the pilot only hears 'Likely' for stop-or-wait instructions, never a clearance to move. Every message starts with a chime and 'Advisory', in a voice that can't be mistaken for ATC. We don't clone controllers' voices." |
| Why not just say "say again"? | "Today often nobody notices the call was lost. Unstep notices, and the readback check catches the misheard case too." |
| How does the pilot's question avoid hallucination? | "The model only sees records we retrieved, and its answer must be a word-for-word quote of an approved clearance. Otherwise the pilot hears 'No record found, ask the controller'." |
| What's the latency? | Point at the strip. Only quote what it shows. |
| How would this reach a real aircraft? | "As a portable device first, not wired into certified avionics. The live link carries only what ATC already says. Certification is future work." |
| What did you learn about Cartesia? | "Two things we reproduced and reported to the team: turn transcripts come back empty if audio is sent faster than real time, and word timestamps depend on the model. Both are in our feedback doc." |
| Why Moss instead of a vector database? | "The search runs in the cockpit process, under a millisecond, and keeps working offline. A network round trip would land in the silence after the squeal." |

## 5. Before judging

- Run `python scripts/preflight.py` at the table: it checks keys, clips, the port, Cartesia, Moss, Moss Inference and Elastic, and plays a left-channel test tone. It ends with READY or lists what's missing.
- Run `python -m unstep.demo --live` once at the table to warm up Cartesia and Moss Inference (first calls are slower).
- Sound check the squeal volume. Say "in the left ear" aloud, since a hall can't hear stereo.
- If presenting with `--live --mic`: do a mic check at the table (run scenes 1 to 2 once, hold V, say "Approve", confirm the transcript on screen), allow the browser mic permission then, and speak close to the mic. If the hall is loud or the transcript is wrong in the check, present without `--mic`: the recorded clips are the default, and in `--mic` mode a turn falls back to its clip after 30 s of silence anyway.
- Backup video on the laptop and a phone.
