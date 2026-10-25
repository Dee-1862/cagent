# Unstep and a human air traffic controller, job by job

Different jobs take different amounts of time, so this compares job by job. It does not average them into one "faster than a human" number. Every figure carries its grade: MEASURED (by us, here or live), SOURCED (a published figure), MODELLED (our arithmetic from stated assumptions) or NOT MEASURED (no figure found, so no comparison is made). `scripts/task_latency_report.py` prints this table from the measurements; the human figures are in `assets/human_baselines.json` with their sources.

| Job | Human ATC | Unstep | Where Unstep stands |
| --- | --- | --- | --- |
| Notice a stepped-on call | No automatic detection. FAA CAMI (2005) found blocked calls in 1.16% of sampled transmissions at the five busiest TRACONs and no alerting system; at the 2025 NTSB hearing the tower operations manager said "There's nothing." Time to notice: NOT MEASURED | Known from key timing within one network hop; call end to "cockpit flagged" about 1.0 s (Rishit, live). Detection 91.7% on simulated calls | Faster, and the only one that detects it. The rate is simulated; the time is live |
| Recover the lost instruction | Say again and retransmit: about 5.85 s, MODELLED (1.5 s pilot reaction and 250 ms per word, both assumptions), and only if someone noticed | 2.9 s from call end to the pilot hearing the fix, including the controller's approval (Rishit, live, R28) | Faster, but most of Unstep's 2.9 s is the human approving |
| Check a readback | Pilot starts the readback about 0.6 s after the instruction (NASA 2022, SOURCED). How often the controller catches an error, and how fast, is NOT MEASURED; readback and hearback errors are the most common communication problem | 3.0 ms in Elastic (live); 0.007 ms in process (measured here) | Faster at the check. People stay the decision |
| Find the FAA paragraph that governs an instruction | NOT MEASURED (memory and training) | 0.02 ms from the hub's stored rules (measured here); about 700 ms by hybrid search when no rule is stored (measured here) | No human figure, so no comparison |
| Speak a clearance | About 2.5 s for 10 words, MODELLED at 250 ms per word (an assumption) | First audio 141 ms; the phrase takes 3.9 s at the default speed (Cartesia, measured here, 6 calls) | Unstep starts quickly but the phrase runs longer than the modelled person. Speed 1.5 trims it to 3.2 s of speech but one test phrase came back as "holds short"; 1.3 was clean on two phrases. Not a win |
| Explain why, or write a handoff briefing | A person writes or says it: NOT MEASURED | 5 to 12 s through an Elastic agent (live, R47); 0 to 6 s when the Intercept step is skipped or the answer is cached | Slower. It runs after the card is on screen, off the path a pilot waits on |

## What can honestly be said

- "Unstep notices a stepped-on call, checks a readback and finds the governing rule in milliseconds; today nothing in the system does the first at all." Detection rate is simulated.
- "The machine part of recovering a lost instruction is tens to hundreds of milliseconds; the 2.9 s end to end is dominated by the controller deciding." Not "Unstep recovers calls faster than a controller" without that.
- "A synthetic voice starts speaking within about 140 ms." Not "speaks faster than a controller": it does not.

## What not to say

- That agents are faster than humans at everything, or an average over the jobs.
- Any human figure marked NOT MEASURED: there is no number to put against Unstep's.
- That the 5.85 s say-again time is measured. It is arithmetic from two assumptions.
- That this shows safety or workload effects. It is timing only, in a simulator and a lab.

## Where Unstep could get closer to a person, and the limits

- Speaking: Sonic's speed setting (documented range 0.6 to 1.5) trims at most about 8% and risks mishearing; the better lever is shorter phrases.
- Explanations: any Agent Builder call took about 5 or 10 s whatever the answer length or model (docs/25 section 11), so explanations stay late.
- The human-approval step is not something to speed up; it is the safeguard.
