# What pilots and controllers think about Unstep-style ATC assistants

**Coverage.** Reddit (r/ATC, r/flying and the others) blocks our fetcher, so **no Reddit opinions are verified here**. I opened Hacker News, PPRuNe, Pilots of America (POA), AIN, Flying, Scientific American, CORDIS and vendor pages. Quotes are copied from the fetched pages. Self-reported roles are given where posters stated them.

## 1. Prior art

- **Rohde & Schwarz DSiT** is a ground radio feature that detects simultaneous transmissions with up to a 20 dB level difference. It gives the controller an acoustic or visual warning and is being adopted at Singapore Changi, which plans more than 240 radios ([R&S](https://rohde-schwarz.com/_232848.html)). It only alerts the controller. It does not recover the lost words or tell the pilot. All performance claims are the vendor's own.
- **US status, from the NTSB DCA midair hearing.** Asked whether a controller can tell a call was stepped on, Clark Allen, the KDCA tower operations manager, said: "There's nothing." He said such systems existed "20 years ago or so" but "That is not the system that we currently have." ([AIN](https://backend.ainonline.com/aviation-news/air-transport/2025-08-04/ntsb-dc-midair-hearing-panel-3-covers-frequency-issues)). This is the strongest hook for the pitch.
- **HAAWAII (SESAR, DLR/Idiap/Isavia/NATS)** built a readback error detector. It caught about 80% of readback errors with 11% false alarms in controller trials. The project found word-level comparison "very ineffective" and switched to comparing semantic concepts ([Idiap](https://publications.idiap.ch/publications/show/4728), [CORDIS](https://cordis.europa.eu/article/id/442201-better-automatic-speech-recognition-for-safer-air-traffic-control)). Five Icelandic controllers evaluated it in a lab. CORDIS quotes none of them.
- **MITRE/FAA (2021)** lists real-time readback/hearback error detection as a goal of ATC speech recognition ([FAA ATIEC slides](https://www.faa.gov/air_traffic/flight_info/aeronav/atiec/media/Presentations/2021/ATIEC_2021_ATC_Speech_Rec-MITRE-2021-09-16.pdf)).
- **Enhanced Radar (YC W25)** builds ATC speech-to-text with ADS-B context and checks readbacks. It sells post-operational review first and plans real-time advisories later ([HN launch](https://news.ycombinator.com/item?id=43257323)).
- **Products that transcribe ATC in the cockpit:**
  - Appareo Stratus Insight, with an on-device model.
  - AvNav.
  - ATC Copilot, whose listing says it is "not certified" for real-time operations ([App Store](https://apps.apple.com/bj/app/atc-copilot/id6760933953)).
  - Airbus DragonFly flight-tested speech recognition that drew taxi instructions on the cockpit display ([The Air Current](https://theaircurrent.com/technology/natural-language-processing-aviation-atc-cockpit/), paywalled; summary only).
  - Garmin and ForeFlight: I found no ATC transcription product.
- **Honeywell RAAS** is the closest precedent for an aural advice voice in the cockpit. Honeywell deliberately called its callouts "advisories, not alerts" to avoid heavier certification, and built it to keep nuisance callouts rare ([AIN 2008](https://backend.ainonline.com/aviation-news/air-transport/2008-01-16/egpws-software-add-improves-airport-safety)).

## 2. Opinions

### (a) Enthusiasm
- POA, Stratus user: transcription helped "understand my read back clearance without getting flustered" (paraphrased by the search tool; I did not see the exact wording).
- POA, AerialsSoUpHigh, wanting replay: "handy if they throw in an extra thing I wasn't expecting like an altimeter setting" ([POA](https://www.pilotsofamerica.com/community/threads/instant-replay-atc-audio-tx.138926/)).
- HN, someguydave: "the blocking problem is very real and could be addressed potentially." HN, ibejoeb: "it would be handy to have it as a check" ([HN](https://news.ycombinator.com/item?id=43257323)).
- PPRuNe, CayleysCoachman (former controller, also a pilot): supports voice recognition cross-checking readbacks, but only "IF IT CAN BE DONE SO THERE IS NO ADDITIONAL JEOPARDY" ([PPRuNe](https://www.pprune.org/tech-log/671137-ai-no-brainer-atc.html)).

### (b) Objections and fears
- **Accuracy, especially numbers.** POA, dfw11411: "Misinterpreting altitudes, headings, etc. was the deal breaker for me." POA, Racerx: "A drunk monkey could make more sense." ([POA](https://www.pilotsofamerica.com/community/threads/stratus-horizon-pro-radio-transcription.133205/)). HN, ryandrake: "This is not the place to guess or AI-hallucinate."
- **False alarms make people tune it out.** PPRuNe, A346Dude (ATCO, Canada): "If it gives false/spurious warnings 5 times a day, it will quickly be silenced and/or ignored." Enhanced Radar's founder, relaying what controllers told him: "each alert triggers a bunch of paperwork."
- **Liability.** PPRuNe, ATC Watcher (ATCO, Europe): "At the moment controllers are taking the responsibilities." He asked whether engineers would accept responsibility if a machine gets it wrong; his answer so far was "a big NO."
- **Missed alarms.** HN, btown: "not just false positive alerts but false negatives as well."
- **Distraction and missed calls.** POA, Gary Ward, passing on his CFI's warning about replay: "I could miss a ATC tramission using it." POA, Daleandee, on text-based ATC: "puts the pilots eyes inside the plane at perhaps the wrong time."
- **Who is talking to whom.** HN, tjohns: "Clearance isn't something that can just be broadcast. You need to have a conversation with the pilot" ([HN](https://news.ycombinator.com/item?id=49748387)). Airliners.net pilots value the "party line" for building a picture of nearby traffic ([thread](http://www.airliners.net/forum/viewtopic.php?t=739105)).
- **Automation complacency.** Shem Malmquist (777 pilot): "If you start depending on automation, you lower your guard." John Leahy (former BA chief pilot): automation "can actually make things worse" ([SciAm](https://www.scientificamerican.com/article/can-ai-replace-air-traffic-controllers-to-reduce-airline-accidents)).
- **Union.** NATCA says it "has not been involved in the design, testing, or implementation" of the FAA's SMART AI program, and holds that technology should complement controllers, not replace them ([Flying, Sept 2026](https://www.flyingmag.com/faa-smart-ai-rollout-natca-atc-union/)).
- **Adding layers.** PPRuNe, EEngr: "The more layers of cruft you add to a critical protocol, the more chance something will be overlooked."
- **Privacy and recording of ATC:** I found no specific forum objection. Not verified either way.

### (c) What would make it acceptable
- **Advisory only.** Zionstrat2 (GA pilot) proposes AI with "only alert advisory authority." ATC Watcher describes current tools that make suggestions the controller must validate.
- **Show the source and avoid guessing.** Pilots who liked transcription valued replaying the original audio. EasyATC, a sim tool, leaves an unsure number blank rather than guessing (vendor page).
- **Involve controllers in design** (NATCA). Enhanced Radar started with after-the-fact review before real-time use.
- **GA first.** Most enthusiasm comes from GA pilots at POA. Airline pilots and controllers are the most skeptical.

## 3. Bottom line

**Pilots** (mainly GA, likely the warmest audience): they are likely to like the "what was my last clearance?" recall and the readback check. They will ask right away how often it gets numbers wrong and whether it talks over the frequency. **Airline pilots** will raise certification and SOP concerns. **Controllers** are likely to be the hardest audience. They want to know who is liable, whether the approval is one more task during the busiest moment, and whether there is a private channel into the cockpit that the rest of the frequency cannot hear.

**Three objections to pre-empt in the pitch:**
1. **"AI will hallucinate a number into my headset."**
   - Already addressed: controller approval before any directive; "Likely" hints only for restrictive instructions and only with a source record; answers validated as exact quotes; a clean-call run that shows no false alarm.
   - Changes needed: show measured false-alarm and miss rates; say "unable to verify" instead of guessing a number; spell out runway digits in the readback check.
2. **"Who is liable, and does this add controller workload?"**
   - Already addressed: one-word voice approval with repeat-back, or a click; the controller stays the authority.
   - Changes needed: **the auto-relay policy agent contradicts the README's "Human approval for every directive."** Controllers like ATC Watcher will seize on that. Make auto-relay off by default, or limit it to repeating the controller's own exact words. Also show how long an approval takes compared with re-keying the radio.
3. **"Another voice in my head, off the party line."**
   - Already addressed: chime plus the "Advisory" prefix, a distinct synthetic voice, no voice cloning, left ear only, and the voice stops when the pilot speaks.
   - Changes needed: hold advisories while the frequency is active (the README only mentions stopping on pilot speech); require the pilot's readback to go out on the frequency so everyone still hears the clearance; label the cockpit side as an advisory aid, not avionics.

**One extra risk:** a pre-approval "Likely go around" hint that turns out wrong could cause an unneeded go-around. Restrictive does not mean zero risk.
