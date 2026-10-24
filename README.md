# Unstep

**No ATC instruction lost or misheard.** Unstep catches radio calls that were stepped on or read back wrong, has a human controller approve the correction, and speaks it into the pilot's headset with Cartesia voice.

Pilots and controllers share one half-duplex VHF channel, so when two stations transmit at once the call turns into a squeal and is lost. An FAA CAMI study (DOT/FAA/AM-05/19, 2005) found blocked, stepped-on or clipped calls in 1.16% of transmissions sampled at the five busiest US TRACONs, and no alerting system for stepped-on or clipped calls ([source](https://rosap.ntl.bts.gov/view/dot/58248/dot_58248_DS1.pdf)). Today recovery depends on someone noticing and asking "say again", and a misheard readback is only caught if the controller happens to hear it.

Full spec: [docs/01-prd.md](docs/01-prd.md). We logged API feedback for Cartesia: [docs/09-cartesia-feedback.md](docs/09-cartesia-feedback.md).

## Demo

```bash
python scripts/run_demo.py           # full flow, offline, no keys needed
python scripts/run_demo.py --clean   # a clean call: proves no false alarm fires
```

One command starts the gateway, mock ground agents, the controller voice approval loop and the real cockpit pipeline on `assets/clips/stepped_on_call.wav`, with fake STT and TTS. It prints what each party heard, with measured latencies:

1. The overlap detector finds the squeal on the stepped-on call.
2. Pilot hears a chime, then "Advisory. Transmission blocked. Likely hold short runway tree tree. Awaiting controller." The hint comes from local memory search, with its source record.
3. The controller hears "Blocked call to N123AB: hold short Runway 33. Approve?", says "Approve" on the Unstep key, hears the repeat-back, and only then is the directive sent (`unstep/ground/voice_approval.py`).
4. The directive plays in the left ear only, ending "Read back."
5. Pilot reads back "runway two three". Unstep: "Readback incorrect", pilot corrects, confirmed.
6. Pilot asks "Unstep, what was my last clearance?" and gets an answer from the flight session.

Audio is written to `data/cockpit_audio.wav`, events to `data/events.jsonl`.

**Live, with keys:** fill `.env` (below), then run the gateway and the real cockpit edge. With `CARTESIA_API_KEY` and `CARTESIA_VOICE_ID` set, the edge uses Cartesia STT and TTS; with `MOSS_*` set it uses Moss.

```bash
uvicorn unstep.gateway.server:app --port 8765               # gateway, dashboard at http://127.0.0.1:8765
python -m unstep.ground.mock_agents                          # ground agents (Elastic replaces this, task B5)
python -m unstep.cockpit.monitor --url ws://127.0.0.1:8765   # Frequency Monitor
python -m unstep.cockpit.edge assets/clips/stepped_on_call.wav --play
```

Approve by voice with `python -m unstep.ground.voice_approval` (add `--live --answer-clip <wav>` for Cartesia), or click Approve or Reject on the dashboard. `python -m unstep.ground.auto_approver` approves everything instantly for load tests. `python -m unstep.cockpit.mock_cockpit --runs 10` is a lightweight stand-in for the edge.

## Browser demo plumbing

Open `/demo/` on the gateway for a read-only message list. `/ws/observer` receives
all routed contracts, including audits and gateway decisions, and replays the
last 200 messages on reconnect. It uses the same token and origin checks as
other roles and rejects all incoming messages. Part B replaces the placeholder
page.

Add `--demo-audio-dir` to the edge, controller voice loop or `scripts/run_demo.py`
to save WAV artifacts under `data/demo/audio/`. An explicit directory is also
accepted; use the same directory in `create_app(demo_audio_dir=...)` when running
a custom gateway. The one-command demo passes it through automatically. Audio
export is off by default. The standalone gateway serves the default directory
at `/demo/audio/`. Files remain until manually removed.

Speech audits carry `party`, `spoken_text` or `heard_text`, available `words`
with seconds relative to the WAV (including the chime), and optional `audio_url`.
Controller utterances stream individually when demo audio is enabled; otherwise
they are included in the final controller audit's `utterances` list. Text-only
fake pilot/controller input has no recorded audio to export.

```bash
python -m unstep.ground.tower --clip assets/clips/real/clean_call.wav --live
python scripts/run_demo.py --live --demo-audio-dir
```

`TowerTranscriber.transcribe` accepts 16 kHz mono PCM16 bytes, PTT start/end epoch
milliseconds, frequency and callsign. It uses keyed ink-2 text and a second
ink-whisper stream for word timing. Both streams are paced and finalized at the
end of the PTT duration, using Cartesia's [manual STT endpoint](https://docs.cartesia.ai/api-reference/stt/websocket).
Without `--live`, the tower client uses the explicit scenario fake. Tower word
offsets remain seconds from `ptt_start`; pass a shared `--ptt-start` when matching
independently replayed tower and cockpit recordings. The demo runner supplies a
shared epoch automatically. The runner retains its scripted controller approval;
use the standalone voice approval client for recorded controller answers.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                # fill in keys, never commit .env
```

| Key | Used for |
| --- | --- |
| `CARTESIA_API_KEY` | Cartesia TTS and STT |
| `CARTESIA_VOICE_ID` | The advisory voice |
| `CARTESIA_PRONUNCIATION_DICT_ID` | ATC pronunciation dictionary (from the upload script below) |
| `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY` | Moss indexes (local fallback without them) |
| `ELASTIC_CLOUD_URL`, `ELASTIC_API_KEY` | Elastic (planned, Dev B) |
| `UNSTEP_GATEWAY_URL` | Gateway address, default `ws://127.0.0.1:8765` |
| `UNSTEP_GATEWAY_TOKEN` | Optional shared secret; clients then connect with `?token=` |

Then, once per account:

```bash
python scripts/upload_pronunciation_dict.py   # uploads assets/pronunciation/atc.json, prints the id
python scripts/smoke_cartesia.py              # TTS first audio, STT round trip, turn events
python scripts/smoke_moss.py                  # seeds and queries Moss, prints search time
python scripts/make_real_clips.py             # optional: real-speech clips into assets/clips/real/
```

Every script prints `skipped: ...` and exits 0 when its keys are missing.

## Cartesia features used

| Feature | Where in code | Why |
| --- | --- | --- |
| Sonic TTS (`sonic-3.6`) over WebSocket, one context per message | `unstep/cockpit/tts.py` `CartesiaTTS` | Low-latency advisory voice. Measured **214 ms to first audio** on our laptop, including network (`smoke_cartesia.py`) |
| Word timestamps (`add_timestamps`) | `CartesiaTTS.speak` | Collected per word, for highlighting words as spoken (on-screen highlight is planned) |
| Pronunciation dictionary | `assets/pronunciation/atc.json`, `scripts/upload_pronunciation_dict.py`, `pronunciation_dict_id` in the request | ATC numbers and words: "niner", "tree", "fife", "Unstep" |
| Calm advisory voice (`emotion: calm`, speed 1.1, volume 1.2) plus chime and "Advisory" prefix | `AdvisoryVoice`, `advisory()`, `chime()` | Never mistaken for a controller (FR-8, FR-16) |
| Left-ear output | `to_left_stereo` | Directives stay off the radio ear (FR-7) |
| Context cancel on interrupt | `CartesiaTTS.cancel`, `AdvisoryVoice.interrupt` on `turn.start` | Pilot speech cuts the voice off (FR-10) |
| Ink-2 STT with key terms (callsigns, runways, "hold short", "niner") | `unstep/cockpit/stt.py` `build_keyterms`, `CartesiaManualSTT` | Correct ATC words. Verified live: "likely hold short runway tree tree" came back exactly |
| Manual `finalize` on squelch close / PTT release | `CartesiaManualSTT.finalize`, used by `unstep/cockpit/edge.py` when a key is set | Transcript is final the moment the transmission ends |
| Turns endpoint (`turn.start` / `turn.end`, tuned end threshold) | `CartesiaTurnSTT` | Readbacks and pilot queries. Client works live (`smoke_cartesia.py`); the edge uses a scripted fake by default. Also used for controller voice approval (`unstep/ground/voice_approval.py`, task B10) |
| `ink-whisper` for word timestamps | `unstep/ground/tower.py` | Second paced stream for tower word times and blocked-word marking |

## Moss and Elastic

| Sponsor | Built | Planned |
| --- | --- | --- |
| Moss | `unstep/cockpit/memory.py`: `airport-<ICAO>` and `flight-<callsign>` indexes, one writer per index, filter translation to Moss format, local fallback with the same interface. Local hint (`hint.py`) and pilot queries (`queries.py`) with search time shown. Frequency Monitor (`monitor.py`) owns `freq-<frequency>`. **Verified on real Moss** (hint 0.6 ms, query 1.0 ms). `airport-KUNS` is a persistent cloud index created once by `scripts/ingest_airport.py` and loaded at startup; flight and frequency data are sessions. **Moss Inference** answers free-form pilot questions from records we retrieve, validated as exact quotes (`unstep/cockpit/inference.py`, about 165 ms to first token warm) | |
| Elastic | Gateway writes every message to an event sink (`data/events.jsonl` today) | Elastic events index, Workflow with Agent Builder agents (Intercept, Compliance with FAA JO 7110.65 citation, Readback Auditor), ES\|QL audit (task B5) |

## Responsible use

- **Human approval for every directive.** Nothing reaches the cockpit as a directive without a controller's Approve. The dashboard click always works.
- **Restrictive-only hints, with sources.** Before approval the pilot only hears a "Likely" hint for instructions that make the aircraft stop or wait (hold short, go around). Permissive instructions (cleared for takeoff, cross runway) are never hinted. No source record, no hint.
- **Only the Unstep key commands Unstep.** Speech on the radio frequency is transcribed but never obeyed.
- **Never mistaken for ATC.** Every message starts with a chime and "Advisory", in a distinct synthetic voice. No voice cloning of controllers.
- **Privacy.** Tower audio is transcribed only to recover blocked or misheard instructions. In the prototype all data stays local in `data/`. No keys in the repo: `.env` is ignored and the gateway accepts an optional token.
- **Accessibility.** Readback checks help pilots under high workload or with hearing difficulty. Blocked words are highlighted on the dashboard; highlighting words as they are spoken uses Cartesia word timestamps (screen side planned).

## Known limitations

- **Overlap detection is narrow.** It finds the heterodyne beat tone, not a second voice, and is only proven on clips we mixed ourselves. A full overlap, where the stronger signal captures the receiver, can't be detected from audio at all ([research RA-4](docs/06-research.md#3-evidence-table)). The reliable signal is comparing tower and cockpit transcripts.
- **Simulator, not avionics.** A laptop stands in for the audio panel. Nothing here is certified.
- **Moss real backend untested end to end.** Filters are translated to Moss's format and covered by tests, but the full demo has only run on the local fallback.
- **Cartesia workarounds.** `ink-2` returns no word timestamps and `ink-whisper` has no key terms (Cartesia feedback item 2), so tower word times need a second stream. The turns endpoint returns empty transcripts if audio arrives faster than real time (Cartesia feedback item 1), so replays are paced at real time.
- **Readback parser is regex-based.** It compares callsign, action and runway only; unusual phrasing can be misread.
- Ground agents and Elastic are mocked today (task B5). Controller voice approval is built and tested with scripted speech; live mode replays a recorded answer clip, there is no live microphone input yet.

## Repo layout

| Path | What | Owner |
| --- | --- | --- |
| `unstep/contracts.py` | Shared message contracts | Both |
| `unstep/clock.py` | One clock, epoch ms (FR-17) | Both |
| `unstep/scenario.py` | Demo scenario data | Both |
| `unstep/cockpit/` | Cockpit edge: overlap detector, Cartesia STT/TTS, Moss memory, hint, readback, queries, Frequency Monitor | Dev A |
| `unstep/gateway/` | WebSocket gateway and event sink | Dev B |
| `unstep/ground/` | Controller voice approval (B10), mock agents, auto approver | Dev A built B10, Dev B owns the rest |
| `web/dashboard.html` | Controller dashboard | Dev B |
| `scripts/` | Demo, smoke tests, clip generation, pronunciation upload | Both |
| `assets/` | Demo clips and pronunciation dictionary | Dev A |
| `contracts/examples/` | One JSON example per contract (`python scripts/export_contract_examples.py`) | Both |
| `docs/` | PRD, architecture, research, Cartesia feedback | Both |

Every message is an envelope `{"type": "AnomalyEvent", "ts": 1792800000000, "data": {...}}` on `ws://<gateway>/ws/<role>`, role one of `cockpit`, `tower`, `agents`, `dashboard`, `controller_voice`, `monitor`, `observer`. Routing is in `unstep/gateway/server.py` (`ROUTES`).

## Tests

```bash
python -m pytest -q   # 129 passed, 1 skipped, offline
```
