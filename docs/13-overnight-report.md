# Overnight Report: Demo Build (2026-10-24, about 00:15 to 03:45 PT)

What was built while Rishit slept, how to run it, what's left, and what needs a human decision. Everything is on branch `rishit` and in PR #2.

## 1. Run it

```bash
python -m unstep.demo --live    # real Cartesia, Moss, Moss Inference; ~30 s warm-up, then opens the browser
python -m unstep.demo           # same pipeline offline with labeled fakes
```

Space runs the next scene, A toggles audio mode and full view, ? shows the keys. Scripts and storyboard: [Demo Design](11-demo-design.md), [Pitch](12-pitch.md).

**Backup video:** `data/video/unstep-demo-live.mp4` (1:10, 1080p, real Cartesia audio, recorded from a live run at about 03:40). Re-record any time with `python scripts/record_demo_video.py` (or `--offline`). The folder is git-ignored; copy the MP4 to a phone too.

## 2. What was built

| Area | Result |
| --- | --- |
| Design | Research on winning demos and aviation display conventions, then a spec with a contrast-checked palette ([11-demo-design.md](11-demo-design.md)) |
| Plumbing | Read-only `observer` role with replay, spoken and heard text plus audio in every audit record, demo audio served under `/demo/` |
| Tower transcript (B2) and blocked words (B3) | `unstep/ground/tower.py` (ink-2 text plus ink-whisper word timestamps), `unstep/ground/blocked.py`. Verified live: blocked words "hold short runway 33" |
| Presenter mode | `python -m unstep.demo`: whole stack in-process, scenes paced by the presenter, every message still through the gateway's role rules, failed scenes say so and never fabricate |
| Demo screen | Audio mode with word-synced captions, four-lane timeline with the BLOCKED band and struck-out words, hint, readback and analytics cards, latency strip of measured values only |
| Pitch | Two-minute script, 30-second sponsor versions, honest judge Q&A ([12-pitch.md](12-pitch.md)) |
| Backup video | `scripts/record_demo_video.py` records the screen and places each real audio clip at its playback time with ffmpeg |
| README | Screenshots from a live run, presenter mode instructions |

**Latest live measurements** (03:40 run): cockpit STT finalize 101 ms, Moss search 2.08 ms, Cartesia TTS first audio 110 ms, Moss Inference first token 328 ms, readback verdict 0.13 ms. Live scenes take about 10 s (radio), 9 s (approval), 25 to 30 s (readbacks), 15 s (questions).

## 3. Bugs found and fixed tonight

Found by live runs and three red-team passes; all fixed with tests (254 passing).

- **A correct readback failed.** Cartesia heard the tower as "holds short", the directive inherited it, and "hold short runway 33" was flagged wrong. Proposals now use canonical wording from parsed slots.
- **DNS rebinding.** A malicious page in the controller's browser could reach the local gateway and approve. The gateway now only answers local hosts (plus configured ones).
- **A rejection was counted as an approval** in presenter mode. Fixed, and rejections are shown on screen.
- **The demo page carried the gateway token.** Removed; the read-only observer is local-only instead.
- **Live latency.** First Space press took 30+ s (now warmed at launch), tower and cockpit ran one after the other (now parallel), the cockpit waited for the full hint audio before telling the ground (now sends first).
- **Cartesia robustness.** Idle TTS connections are reopened, STT handshakes that hang are retried, empty turn transcripts get one retry, TTS never speaks a line twice.
- **Safety.** An empty pilot question gets "Say again" and never reaches the LLM. Airport records are labeled "not a clearance". The B10 voice approval loop could hang forever on Windows (fixed earlier tonight).
- **Honesty.** Recorded controller clip and offline stand-ins are labeled on screen; analytics are scoped to the current run.

## 4. Cartesia feedback

[09-cartesia-feedback.md](09-cartesia-feedback.md) now has a section "Observed intermittently": STT handshakes that hung, `finalize` latency from 76 ms to 7.4 s for the same clip, and occasional empty `turn.end` (about 2 in 25). Reported as numbers, no claimed cause. The two reproducible items are unchanged.

## 5. Needs a decision or a human

| # | Item | Who |
| --- | --- | --- |
| 1 | **Merge PR #2** into `master`. It touches `unstep/gateway/server.py` (host allowlist, observer role, `/demo` routes) and `unstep/ground/mock_agents.py`; Dev B should glance at those | Both |
| 2 | **Elastic is still the weak track.** The ground agents are mocks ("No rule citation supplied · mock ground agents" on screen). B5 (Workflow and agents), B4 (FAA index) and B8 (ES\|QL) are the critical path. The analytics card already runs real ES\|QL as soon as `ELASTIC_*` is configured | Dev B |
| 3 | **Cross-machine gateway.** The gateway now only answers local hosts. To run tower and cockpit on two laptops, set `UNSTEP_ALLOWED_HOSTS` to the gateway laptop's LAN IP | Dev B |
| 4 | **Controller voice is a recorded clip.** A live mic for the controller would make the voice-first story stronger; it's labeled honestly for now | Rishit |
| 5 | **Restore power settings** after the hackathon: run `restore-power.ps1` from the session scratchpad (sleep was disabled and a keep-awake helper runs until about 11:18) | Rishit |
| 6 | **Rotate the Cartesia and Moss keys** after the hackathon (both appeared in chat) | Rishit |
| 7 | **Codex usage** ran out at about 01:50 and resets at 04:19; the rest was built with Claude sub-agents | Info |

## 6. Known limits (say these honestly if asked)

- The overlap detector is proven on clips we mixed, not real VHF; the tower and cockpit transcript comparison is the real confirmation.
- Cartesia STT latency varied a lot overnight; the latency strip shows whatever this run measured.
- The ground agents are mocks until B5 lands.
