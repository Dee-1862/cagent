# Submission copy: YouTube and Devpost

Ready to paste. Numbers are ours or Rishit's live runs, labelled as such; things that are stand-ins say so. Check the lines marked [fill] after the video is edited. Written from Devpost and demo-video advice (short, specific, tied to the sponsors, a story first and a feature list second) and then edited to sound like people wrote it.

## YouTube

**Title (68 characters)**
Unstep: when two pilots talk at once, nobody notices. Now someone does.

**Description**

On a shared radio, two people pressing the button at the same time turns both calls into a squeal, and nobody is told. The pilot heard noise. The controller thinks the instruction went out.

At the 2025 NTSB hearing on the Washington midair collision, a tower manager was asked whether a controller can tell that a call was stepped on. He said: "There's nothing."

Unstep is a team of AI agents that works the radio next to the controller. In this demo the laptop is the control tower and the phones are the planes. Hold to talk, step on someone, and watch Unstep catch it, recover the lost words, and speak the fix privately into the pilot's ear once the controller approves. A person decides every time. The agents never grant permission.

What is real: live speech to text and speech from Cartesia, a separate memory for every plane in Moss, and Elastic checking readbacks, the FAA rulebook and the airport map. What is a stand-in: the radio noise and traffic are simulated, and the airport map is a demo map, not a survey. This is a simulator, not avionics, and nothing here is certified.

Built for the Cartesia, Moss and Elastic tracks.
Code: https://github.com/Dee-1862/cagent
Devpost: [fill the link]
Chapters: [fill after the edit]

**Tags**
unstep, air traffic control, ATC, aviation safety, voice AI, Cartesia, Sonic, Moss, Elastic, Elasticsearch, Agent Builder, multi-agent, speech to text, text to speech, hackathon, FastAPI, React

## Devpost

**Project name:** Unstep

**Tagline (50 characters):** Catches the air traffic call nobody knew was lost.

**Built with:** cartesia, sonic, ink-2, moss, moss-inference, elastic, elasticsearch, es-ql, agent-builder, elastic-workflows, mcp, python, fastapi, websockets, react, typescript, three.js, playwright

**Tracks:** Cartesia, Moss, Elastic

**Description**

### The problem
On a shared radio frequency only one person can talk at a time. When two press the button together, both calls turn into a squeal and nobody is told. The pilot heard noise, and the controller thinks the instruction went out. At the NTSB hearing on the 2025 Washington midair collision, the tower operations manager was asked if a controller can tell a call was stepped on. His answer was "There's nothing." An FAA study (CAMI, DOT/FAA/AM-05/19) found about 1 in 100 transmissions at busy approach facilities blocked or clipped.

### What Unstep does
Unstep is a team of agents on the radio with the controller. Each plane has its own cockpit agent with its own memory, and on the ground other agents check every call against the FAA rulebook. The controller stops doing the busywork and supervises.

When a call is stepped on, Unstep notices, recovers the lost words, and puts a plain-English card in front of the controller with the FAA paragraph behind it. One click approves. The fix is then spoken privately into the pilot's left ear, the readback is checked, and a wrong readback is corrected. Nothing is ever sent without the controller, except the controller's own stop and wait words under visible rules with an off switch.

Try it: the laptop is the tower on the projector and your phone is the plane. Scan the QR code, hold to talk, step on someone, and watch.

### Cartesia: the voice of everyone in the loop
- Live captions while people talk, with callsigns and runways as key terms. On our simulated noisy radio, callsign accuracy went from 62.5% to 95.5% with the key terms on (Rishit's laptop, 200-line benchmark).
- Sonic speaks the private advisory, first audio in about 130 to 140 ms, cancels the moment the pilot speaks, and repeats it in the pilot's language in the same voice.
- Every line we generate is played back through speech to text in a test. That loop caught our own pronunciation dictionary breaking "niner".

### Moss: every plane remembers
- Each plane has its own on-board memory. A garbled call is searched against what that plane actually heard, at 0 to 1 ms, with no cloud round trip.
- That memory is saved to the plane's disk and restored after a restart; the Moss SDK's restore took about 1.5 ms (21 ms for the whole restart, Rishit's live run).
- When a plane lands, its flight log goes to Moss Cloud and survives a restart. The Clearance agent reads the plane's last tower call in 0.3 to 0.6 ms.

### Elastic: it watches the whole airport
- A percolator holds every instruction as a stored query, so a readback is matched in about 3 ms. Rules sit in Elastic and a person reviews each one.
- Eight Agent Builder agents and seven workflows run the explaining: which FAA paragraph governs a call, why a readback did not match, a coach that reads how controllers decided, a shift briefing every 8 hours. They are configured over our data, not trained.
- Geo queries put every plane on the airport map, check runway occupancy in 4 to 5 ms and flag an incursion. Our tools are also open over MCP.

### How a person stays in charge
No model ever writes an instruction. The words come from the controller's own transmission, hints only say stop or wait, translations must keep every number, and anything unsure becomes "say again". The controller sees why in one sentence at every step.

### What we measured, and what we did not
- About 3 s from the end of a stepped-on call to the pilot hearing the fix, most of it the controller deciding (live, Rishit).
- Detection on simulated calls: 91.7%, and 100% caught with no false alarm on clean audio in the benchmark. Simulated radio, not a real facility.
- The Elastic agents take about 10 s, so they explain after the card is already on screen. We do not claim they are fast.
- Sonic speaks about 40% slower than a median controller (about 3.5 against 6.1 syllables per second), and three pronunciation entries were heard worse than none, so we left them out.
- The airport is a demo map. Nothing here is certified or tested in a real tower. We have two days of controller decisions, which is too few to claim the system improves over time.

### What's next
False-alarm rates on real recorded ATC audio, a small recorded set of people talking over each other on purpose, and a Raspberry Pi box for real radios.

## One-line versions

- Moss: the plane remembers on its own, and restores in milliseconds.
- Elastic: it watches the whole airport with reverse search and geo, and explains with agents.
- Cartesia: it hears the radio through noise and answers in a voice.
