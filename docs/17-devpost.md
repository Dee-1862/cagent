# Devpost Draft

Draft text for the Devpost submission and the Moss social post. Every number here was measured in our own runs; lines marked **[confirm live]** must be checked on demo day before submitting.

| Field | Value |
| --- | --- |
| Status | Draft v0.2 (Deekshith's side finished the lines that commits and tests prove; [confirm live] lines still need a run with keys) |
| Last updated | 2026-10-24 |
| Tracks | Cartesia, Moss, Elastic |

---

## Tagline

No air traffic instruction lost or misheard.

## Inspiration

On a shared radio frequency, only one person can talk at a time. When two press the button at once, both calls turn into a squeal, and **nobody is told**. The pilot heard noise; the controller thinks the instruction went out.

At the NTSB hearing on the 2025 Washington DC midair collision, the DCA tower operations manager was asked whether a controller can tell that a call was stepped on. His answer: "There's nothing." ([AIN, 2025-08-04](https://backend.ainonline.com/aviation-news/air-transport/2025-08-04/ntsb-dc-midair-hearing-panel-3-covers-frequency-issues))

An FAA study (CAMI, DOT/FAA/AM-05/19) found about 1 in 100 transmissions in a busy US approach facility blocked or clipped. We wanted a system that notices, recovers the lost words, and gets them to the right ear, with a human in charge.

## What it does

- **Detects a stepped-on call** in the cockpit, from what the radio actually delivered.
- **Recovers the lost instruction** from the controller's own transmission, and from the plane's own memory of recent clearances.
- **A human decides.** The controller sees a plain-English decision card and approves in one click. Only the controller's own stop/wait words can be re-sent automatically, under visible policy rules, with an off switch.
- **Speaks the fix privately into the pilot's left ear**: "Advisory. From Tower: Cessna 1-2-3, hold short Runway 33. Read back." Optionally repeated in the pilot's own language (Spanish, Hindi, French).
- **Checks the readback** and corrects a wrong one, more slowly.
- **Tells the pilot whose call was blocked** to say again, and tells the controller who was blocked.
- **Never talks over anyone.** Advisories wait for a gap in the frequency, and the console proves it: "waited 1.2 s for a gap, overlapped nobody: 0 ms".
- **Live captions while people talk:** the words appear as Cartesia recognises them, on the projector and on the phone (lyrics-style card), with key words (callsign, action, runway) marked and the measured lag shown. The hold button turns into a scrolling waveform while you talk, red where you were talked over.
- **Walk-up pilots:** a full room answers "All 6 planes are taken. Watch on the projector."; a seat frees itself when its phone leaves, and the presenter can reset the room.

The demo: the laptop is the control tower on the projector, and phones are the planes. **Scan the QR code and you're a pilot.** Hold to talk, step on someone, and watch Unstep catch it.

## How we built it

**Cartesia: the voice of everyone in the loop**
- **Ink-2 streaming speech-to-text** while the key is held, with ATC key terms (callsigns, runways, "hold short"). Streamed text drives the live captions.
- **Transcribing while the call is still on air:** the tower's and every cockpit's speech-to-text are fed during the transmission (each cockpit hears a live mix of the frequency) and finalized when it ends. **Measured live on Rishit's laptop (R28):** the tower transcript is final 155 ms after release (was 2702 ms) and the cockpit's 172 ms after (was 2875 ms). From the call ending to the pilot hearing the fix: 2.9 s including the human approval (was 6.1 s). First audio 201 ms.
- **Tower and cockpit words aligned:** ink-2's words (with key terms) get ink-whisper's word times, so the console strikes exactly the words lost in the overlap.
- **Sonic-3.6** for the private advisory, streamed to the phone from the first chunk:
  - first audio in roughly 100 ms (measured 85–131 ms in our live runs);
  - context cancel when the pilot starts talking;
  - a pronunciation dictionary;
  - speed control (0.85) for corrections;
  - **multilingual output in the same voice.**
- A TTS → STT evaluation loop over 40 ATC lines. **Live: callsign, action and runway 100%, every wrong readback caught, zero false alarms.**
- A larger benchmark harness: 200 lines through our VHF radio channel at several noise levels, three voices, a key-terms A/B, stepped-on mixes, and 95% confidence intervals. **[confirm live: numbers come from `scripts/eval_bench.py --live`]**

**Moss: the plane's own memory, on board**
- **One local Moss session per plane:** every clearance it hears is indexed live, with no cloud index.
  - Search over 6 plane sessions measured at 0–1 ms.
  - The garbled fragment the cockpit heard ("Cessna 123, short runway 30") is run as a hybrid search over the plane's own memory, and the result, with its source record and search time, is shown on the console beside the hint. **The newest clearance gives the hint ("hold short Runway 33"); Moss's search is the evidence.**
  - **Safety rule:** a hint only ever says stop or wait, and an older clearance can never come back ahead of a newer one.
- **Moss Inference** translates the private advisory, about 165 ms to first token warm. A translation is used only if every digit survives; otherwise the pilot gets English only.

**Elastic: checks and remembers**
- **Every message is stored**, and readbacks are matched with a percolator: each directive is stored as a query.
- **Live safety analytics** on the console via ES|QL: blocked calls, readback errors caught, auto-resent calls.
- **Agent Builder agents and Workflows:**
  - **Intercept** matches the lost words to the controller's transcript.
  - **Compliance** cites the FAA JO 7110.65 paragraph.
  - **Readback Auditor** explains a mismatch.
  - Agents never write the instruction; they cite and can only lower confidence. **[confirm live]**

**Stack**
- **Hub:** Python 3.12, FastAPI WebSocket hub with role-based routing; Pydantic contracts.
- **Interfaces:** a React pilot app, and a plain HTML/JS ATC console.
- **Tests:** about 430 Python tests and 25 pilot-app tests passing (offline, with fakes for the vendor services).

## Challenges we ran into

- **Our own pronunciation dictionary broke our speech recognition.** We'd respelled "niner" (ATC for 9) as "NY-ner". Sonic then said something like "N-one-er", and Ink-2 heard "N1er" and "and liner".
  - Runway accuracy was 85%, and two correct readbacks were flagged as wrong.
  - An A/B test pinned it on the dictionary: Sonic says "niner" correctly on its own.
  - Removing one entry took runway accuracy to 100%.
  - **Lesson:** close the loop. Every voice line we generate goes back through speech-to-text in a test.
- **Talking in the gaps.** A radio frequency is shared, and an advisory that talks over a controller is worse than none. Advisories are held while anyone is keyed, restart cleanly from the beginning, and a stop instruction always goes ahead of lower-priority notices.
- **Not hallucinating instructions.** Controllers told us plainly: "This is not the place to guess." So no model ever writes an instruction:
  - the words come from the controller's own transmission;
  - hints only ever say stop or wait;
  - translations must keep every number;
  - anything uncertain becomes "say again".

## Accomplishments we're proud of

- **A real, live loop:** a stepped-on call is detected, recovered, approved, spoken privately and checked by readback, end to end in the live room. **[confirm live on real phones]**
- **A console built for a non-pilot to follow in 10 seconds:** an airport map, plain-English "what just happened", numbered explainability steps, and a timing waterfall from "call ended" to "pilot heard the fix".
- **Measured, not claimed:** 40/40 on our live voice evaluation after the niner fix.

## What we learned

- Voice systems need voice-level tests: text that looks right can sound wrong.
- In safety systems, the best AI step is often the one that refuses to guess.
- Two coding agents, one per teammate, coordinated through Markdown files in a Git branch, with a shell watcher (not a model) checking for replies.

## What's next

- False-alarm rates on real recorded ATC audio (ATCO2, UWB-ATCC), licence permitting. The benchmark already has an ATCO2 loader behind a licence check.
- A small recorded dataset of our own team and friends talking over each other on purpose, with key presses as ground truth.
- Replaying the controller's own recorded words, cut by word timestamps, instead of a synthesized voice, once a slot-match safety check exists.
- Integration with real radios (a Raspberry Pi edge box).

## Built with

cartesia, sonic, ink, moss, elastic, elasticsearch, es-ql, agent-builder, python, fastapi, websockets, react, playwright

---

## Moss social post (draft)

> We gave every airplane its own memory. ✈️
>
> At #CalHacks we built Unstep. When two radio calls step on each other and a pilot only hears a squeal, the plane's own @Moss session searches what it was told, using the garbled fragment it heard, in under a millisecond, locally, no cloud. The newest clearance gives the hint; Moss's search is the evidence on screen.
>
> A human controller approves, and @Cartesia speaks it privately into the pilot's left ear.
>
> No instruction lost or misheard. [demo link]

**[confirm live]** Check the Moss handle and the sub-millisecond number in the final demo run before posting.
