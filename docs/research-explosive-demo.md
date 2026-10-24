# Unstep live demo: making it explosive

## What the research says

**Multi-device demos.** Audience-phone demos work when joining takes one scan, needs no app and no account, and the QR code stays on screen from the start ([AhaSlides](https://ahaslides.com/blog/how-to-run-live-quiz-large-audience/)). That same source warns that a room full of phones loading at once overloads the network, so test on the venue network itself. Demo veterans give the same advice: assume the wifi will fail, have a version that needs no internet plus a recorded video, give up on live fixes after about 45 seconds, and avoid typing on stage ([Berkun](https://scottberkun.com/2011/how-to-give-a-perfect-demo/)). PostHog adds: build around one main point, bookmark the demo URL, cache slow steps, use real data, and close on a clear ending ([PostHog](https://posthog.com/newsletter/how-to-demo.md)). I could not open any write-ups of Cal Hacks or TreeHacks voice demos (Devpost returned 403), so treat the "winners" angle as unverified.

**The domain fact that powers the demo.** SkyBrary defines a blocked transmission as two stations talking at once without the controller realising it. Modern radios give **no audible feedback** when calls collide, so the people talking don't know they were blocked ([SkyBrary](https://skybrary.aero/articles/blocked-transmissions-undetected-simultaneous-transmissions-usit)). The same page lists real incidents, including the 2020 Toronto rejected takeoff and the 2026 LaGuardia collision, where a blocked call was a contributing factor. Bystanders hear the collision as a squeal or garble ([Salon](https://www.salon.com/technology/feature/2002/03/28/heterodyne)). Some patented "step-off" devices stop a radio from transmitting while the channel is busy, but ordinary radios don't do this. **So the phone app must NOT block the second talker.** Letting the collision happen is the whole point.

**Push-to-talk UX.** Zello's default is press and hold, with an optional toggle mode. The button outline shows the state: orange when idle, red while you transmit, green while you receive ([Zello](https://support.zello.com/zw/using-the-ptt-button)). Apple Walkie-Talkie is "touch and hold, speak, release", shows "connecting" before you can talk, and plays chimes even in silent mode ([Apple](https://support.apple.com/en-gb/HT208917)). Discord adds a release delay so the last word isn't clipped (described by [How-To Geek](https://www.howtogeek.com/662101/how-to-enable-push-to-talk-in-discord/), which I did not open).

**Web platform limits:**
- `getUserMedia` works only over HTTPS or on localhost. Elsewhere `navigator.mediaDevices` is undefined, and an ignored permission prompt can leave the call hanging forever ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)).
- An AudioContext starts suspended until the user touches the page. iOS plays no Web Audio while the ringer switch is on silent, and one commenter reports iOS 18.5 locking the audio again ([Montag](https://www.mattmontag.com/web/unlock-web-audio-in-safari-for-ios-and-macos)).
- `navigator.vibrate` needs a prior user tap, and Safari on iOS does not support it ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/vibrate)).
- Screen Wake Lock is Baseline 2025, needs HTTPS, and is released whenever the tab is hidden, so request it again on `visibilitychange` ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API)).

**Explaining an unfamiliar domain.** Flight trackers make the map the main visual: clicking a plane turns it red and opens a side panel with plain fields ([GLOBE guide to FR24](https://www.globe.gov/web/s-cool/home/contrail-investigation/how-to-participate/how-to-use-flightradar24/flight-radar-24-website)). Sports broadcasts follow the same pattern (big picture, one lower-third caption, replay), though that point is my own observation; I found no source to cite.

## Recommendation

### (a) Laptop / projector (16:9, dark, readable from 10 m)
- **Top bar:** "UNSTEP · shared radio 118.7" · a QR code with a short URL · connection dots ("Plane A ✓ Plane B ✓").
- **Left 55%, the main visual:** a stylised airport (one runway labelled "Runway 33", a taxiway) with two large plane icons. Each icon is colour-coded (teal and orange) and labelled with its plain name first, callsign second: "Plane A · Cessna 123". When someone talks, rings pulse from their plane. On a collision, a red lightning bolt joins the two transmitters and the plane that missed its call gets a grey "?" bubble saying "didn't hear it".
- **Right 45%, the radio timeline:** one swim lane per station (Tower, Plane A, Plane B), with live waveforms scrolling left. Any overlap fills red and is labelled **"STEPPED ON — 2 people talked at once."** Under the timeline: what the tower actually said, with the lost words struck through.
- **Bottom strip, "What just happened":** one plain sentence at a time, in large type, written in present tense. For example: "Plane A and Plane B talked at the same time. Plane A never heard 'hold short Runway 33' — and neither talker knows." The jargon sits in small grey text after it ("blocked transmission").
- **Approval card:** it slides up over the timeline and shows the proposed correction, the evidence (overlap ms, Moss hint in 2 ms), a countdown, and a huge **APPROVE (A) / REJECT (R)** pair. Read it aloud.
- **After the readback:** a before/after pair. "Without Unstep: Cessna rolls onto the runway" next to "With Unstep: corrected in 4.1 s", using the measured latency.

### (b) Phone (portrait, full screen, no scrolling)
- **Top 15%:** the plane's identity in its colour ("You are PLANE A — Cessna 123") and a radio status dot.
- **Middle 60%, the PTT button:** at least 220 px, ideally edge to edge, held with the thumb. Use `pointerdown`/`pointerup` plus `touch-action:none` and suppress the context menu so a long press doesn't select text. States:
  - Idle: dark ring, "HOLD TO TALK".
  - Holding: solid red fill, **"ON AIR"**, a mic level meter, an elapsed-time counter, a short press chirp, `vibrate(30)` on Android, and a 250 ms release tail.
  - Someone else talking: amber ring and "Tower is talking…" with the speaker's name. **The button stays pressable.**
  - Disconnected: grey, "Reconnecting".
- **Unstep takeover:** a purple full-screen panel, "Only you can hear this 🔒", with the correction in 32 px text, spoken through Cartesia, then "Now read it back — hold to talk."
- **Readback result:** a full-screen tick or cross.
- **Bottom 25%:** two or three "say this" chips with the scripted line. Tapping one sends it through Cartesia TTS as a real transmission.

### (c) Join flow (three taps)
QR code → `https://<tunnel>/live/` → a "Pick your plane" screen with two large colour cards (taken seats greyed out) → **one "Turn on my radio" tap.** That single gesture handler calls `getUserMedia`, resumes the AudioContext, plays a test chirp and requests the wake lock. Then the screen says "Ready — hold to talk".

**Opinion:** for the judged run, hand judges *your two phones*, already joined, with mic permission granted, ringer on and auto-lock off. Leave the QR code on screen as a "join as a listener" bonus. Judges' own phones are a risk you don't need.

### (d) 3-minute script
- **0:00–0:20 Hook.** The squeal plays on the speakers. "Pilots and controllers share one radio channel. When two people talk at once, this is what everyone hears, and nobody who was talking knows. About 1 in 86 calls at the busiest US approach facilities." (That is the README's 1.16%.)
- **0:20–0:40 Setup.** "This laptop is the control tower. These two phones are airplanes." Hand Plane A to judge 1 and Plane B to judge 2. "When I count three, you both hold and say the line on screen."
- **0:40–1:10 THE MOMENT.** The tower (a teammate) keys "Cessna 123, hold short Runway 33". Judge 2 talks over it on the count. The squeal comes out of the room speakers, the projector flashes red **STEPPED ON**, and the strip reads "Plane A never heard 'hold short'. Neither talker knows." Pause for two seconds and let the room react.
- **1:10–1:40 The agents.** The Cessna's agent hears the squeal and the Moss hint appears. The approval card slides up and the presenter says "Approve" aloud. Judge 1's phone turns purple and speaks the correction privately. Say: "Only they heard that."
- **1:40–2:10 The second catch.** Judge 1 reads back (the chip says "Runway 23", which is wrong). Unstep answers "Readback incorrect", the judge corrects it, and the big tick appears.
- **2:10–2:40 Proof it's real.** "Your turn, talk over each other however you like," and a second collision happens unscripted. Show the Elastic count.
- **2:40–3:00 Close.** The before/after card and the latency numbers, then "No ATC instruction lost or misheard."

### (e) Fallbacks
- **No mic or permission denied:** the say-this chips (Cartesia TTS) still go on air for real, so a collision still happens if both judges tap at the same moment.
- **Noisy hall:** use the chips by default, and plug the laptop into the room PA so the squeal is loud. Phone audio is a bonus.
- **Venue wifi down:** run everything on a phone hotspot. Have a mkcert or self-signed HTTPS certificate on the LAN IP ready, already trusted on both demo phones, so you don't depend on a tunnel.
- **Phone dies:** open a second browser window on the laptop as Plane B and use keyboard push-to-talk.
- **Everything else fails:** after 45 seconds, switch to `python -m unstep.demo --live` presenter mode, and keep a recorded video in reserve.
- **Pre-flight:** set ringer on, brightness to maximum, auto-lock off, and run `preflight.py`.

### (f) Five things that make it explosive rather than good
1. **A judge causes the failure with their own voice.** The collision is something they did, not a clip they watched.
2. **The squeal fills the room.** Play it loud on the PA. Sound gets a gut reaction that a screen can't.
3. **The reveal that "neither of you knows".** Both phones looked normal while they talked, and the projector exposes the lost call. That is the SkyBrary insight shown on stage.
4. **The private message that only one phone gets.** A purple takeover in one judge's hand, read aloud by Cartesia, makes "only this pilot hears it" physical.
5. **An unscripted second round.** "Talk over each other however you like" proves nothing is canned, which is the first thing voice-AI engineers want to know.
