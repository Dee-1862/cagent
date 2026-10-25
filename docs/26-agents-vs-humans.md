# Unstep and a human air traffic controller, job by job

Different jobs take different amounts of time, so this compares job by job. It does not average them into one "faster than a human" number. Every figure carries its grade: MEASURED (by us, here or live), SOURCED (a published figure for this task), DERIVED (arithmetic on sourced figures), CROSS-DOMAIN (a published figure from another field, used as a stand-in and labelled so), MODELLED (our assumptions) or NOT MEASURED (no figure found, so no comparison is made). `scripts/task_latency_report.py` prints this table from the measurements; the human figures are in `assets/human_baselines.json` with their sources.

| Job | Human ATC | Human source (link; blank = none found) | Unstep (our own measurement) | Where Unstep stands |
| --- | --- | --- | --- | --- |
| Notice a stepped-on call | A fully blocked call usually raises an audible alarm and the controller repeats it (94.74% of those cases). For a stepped-on call "no alerting system was detected"; at the 2025 NTSB hearing the DCA tower operations manager said "There's nothing." Time to notice: NOT MEASURED | [FAA CAMI AM-05/19](https://rosap.ntl.bts.gov/view/dot/58248); [AIN, 4 Aug 2025](https://www.ainonline.com/aviation-news/air-transport/2025-08-04/ntsb-dc-midair-hearing-panel-3-covers-frequency-issues) | Known from key timing within one network hop; call end to "cockpit flagged" about 1.0 s (Rishit, live). Detection 91.7% on simulated calls | Faster for stepped-on calls, which have no alert today. The rate is simulated; the time is live |
| Recover the lost instruction | Say again and retransmit: about 5.6 s, DERIVED: 1.5 s reaction to an unexpected event (a driving study, not aviation) + 1.6 s to ask + 2.1 s to repeat a 13-syllable clearance at the median controller rate + 0.3 s of gaps we assumed. Only if someone noticed | [Green 2000, driving reaction times](https://doi.org/10.1207/STHF0203_1) (abstract only); [Nitta, Okazaki and Klinger 2011](https://www.usp.ac.jp/user/usp/english/kenkyusha/ronbun/2011/2011-I-Klinger.pdf) (speech rate) | 2.9 s from call end to the pilot hearing the fix, including the controller's approval (Rishit, live, R28) | Faster, but most of Unstep's 2.9 s is the human approving |
| Check a readback | The pilot starts the readback about 0.64 s after the instruction ends (average 0.639 s, LA-area approach, center and tower recordings, one day). How often or how fast the controller catches an error: NOT MEASURED | [NASA NTRS 20220007116](https://ntrs.nasa.gov/citations/20220007116) (pilot readback delay only) | 3.0 ms in Elastic (live); 0.007 ms in process (measured here) | Faster at the check. People stay the decision |
| Find the FAA paragraph that governs an instruction | NOT MEASURED (memory and training) |  | 0.02 ms from the hub's stored rules (measured here); about 700 ms by hybrid search when no rule is stored (measured here) | No human figure, so no comparison |
| Speak a clearance | About 2.1 s for a 13-syllable clearance: DERIVED from the median controller rate of 6.1 syllables per second at three US airports. Context: an average transmission at the five busiest TRACONs lasted 2.57 s of voice, over all messages | [Nitta, Okazaki and Klinger 2011](https://www.usp.ac.jp/user/usp/english/kenkyusha/ronbun/2011/2011-I-Klinger.pdf) (abstract read); [FAA CAMI AM-05/19](https://rosap.ntl.bts.gov/view/dot/58248) | First audio 141 ms; the phrase takes about 3.7 to 3.9 s at the default speed, about 3.5 syllables per second (Cartesia, measured here) | Not a win: Unstep starts quickly but speaks about 40% slower than a median controller. Speed 1.5 trims it to 3.2 s but one test phrase came back as "holds short"; 1.3 was clean on two phrases. Slower speech is easier for non-native listeners |
| Explain why, or write a handoff briefing | No aviation figure. Cross-domain bracket for a 60-word note: about 70 s typed (51.56 wpm average, 168,000 typists) or about 18 s spoken (196 wpm English conversation). Not a controller measurement | [Dhakal et al. 2018](https://doi.org/10.1145/3173574.3174220); [Yuan, Liberman and Cieri 2006](https://www.ldc.upenn.edu/sites/default/files/interspeech2006-towards-integrated-understanding.pdf) | 5 to 12 s through an Elastic agent (live, R47); 0 to 6 s when the Intercept step is skipped or the answer is cached | Faster than writing the note by hand, comparable to saying it; the figures are not a controller's. It runs after the card is on screen, off the path a pilot waits on |
| Controller catches a wrong readback (hearback) | NOT MEASURED; no source was read in full |  | Readback matched in 3.0 ms in Elastic (live) | No human figure, so no comparison |

## Sources, and how far each was checked

Read in full on 2026-10-25 (the numbers and quotes above were checked against the text):
- Lutz, M., Chatterji, G. and Idris, H. (2022). *Characterization of Response Times based on Voice Communication and Traffic Surveillance Data.* NASA Ames Research Center and Crown Consulting, AIAA Aviation 2022. NASA NTRS 20220007116. Average pilot readback latency 0.639 s. One day of recordings, Los Angeles area, a few hundred clearances.
- Prinzo, O. V. and McClellan, M. (2005). *Terminal Radar Approach Control: Measures of Voice Communications System Performance.* FAA Civil Aerospace Medical Institute, DOT/FAA/AM-05/19. Blocked, stepped-on or clipped transmissions in 1.16% of sampled transmissions at five of the busiest TRACONs; the alerting finding; average transmission 2568 ms of voice.
- Airline Industry News (AIN), 4 August 2025, NTSB DC midair hearing, panel 3: "There's nothing," said Clark Allen, who was operations manager at the KDCA tower at the time of the accident.

Checked only in part: SKYbrary (EUROCONTROL) defines undetected simultaneous transmissions as overlapping so that "the controller is not aware that more than one transmission has occurred"; that is a definition, not a timing.

Read in full for the cross-domain figures: Dhakal et al. (2018), 168,000 typists, average 51.56 wpm; Yuan, Liberman and Cieri (2006), English conversation 196 wpm. Read at abstract level only: Nitta, Okazaki and Klinger (2011), median controller speech 6.1 syllables per second; Green (2000), driving reaction about 0.7 s expected, 1.25 s unexpected, 1.5 s surprise (the publisher page refused a full fetch). Stivers et al. 2009 was not used: the full text was not reachable.

No citation, and labelled so: the 0.3 s of gaps in the say-again sum, and the 13-syllable length of our test clearance. The old 250 ms per word model was dropped. A claim about how often controllers catch readback errors was dropped: only search snippets supported it and nothing was read in full.

All machine figures are our own measurements (here or on Rishit's laptop) and are not citations.

## What can honestly be said

- "Unstep notices a stepped-on call, checks a readback and finds the governing rule in milliseconds; today nothing in the system does the first at all." Detection rate is simulated.
- "The machine part of recovering a lost instruction is tens to hundreds of milliseconds; the 2.9 s end to end is dominated by the controller deciding." Not "Unstep recovers calls faster than a controller" without that.
- "A synthetic voice starts speaking within about 140 ms." Not "speaks faster than a controller": it does not.

## What not to say

- That agents are faster than humans at everything, or an average over the jobs.
- Any human figure marked NOT MEASURED: there is no number to put against Unstep's.
- That the 5.6 s say-again time is measured. It is arithmetic on sourced figures plus a driving-study reaction time, and the explain bracket is typing and talking rates, not controller data.
- That this shows safety or workload effects. It is timing only, in a simulator and a lab.

## Where Unstep could get closer to a person, and the limits

- Speaking: Sonic is slower than a median controller (about 3.5 against 6.1 syllables per second). Its speed setting (documented range 0.6 to 1.5) trims some and risks mishearing; the better lever is shorter phrases.
- Explanations: any Agent Builder call took about 5 or 10 s whatever the answer length or model (docs/25 section 11), so explanations stay late.
- The human-approval step is not something to speed up; it is the safeguard.
