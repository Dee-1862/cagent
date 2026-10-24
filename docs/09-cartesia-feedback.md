# Cartesia Feedback

Feedback from building Unstep on Cartesia (Sonic TTS, Ink STT). Everything under "Observed" was reproduced against the live API. Nothing here blocked us: Unstep runs end to end on Cartesia.

| Field | Value |
| --- | --- |
| Last updated | 2026-10-23 |
| API version | `cartesia_version` 2026-08-14 |
| Models | `sonic-3.6`, `ink-2`, `ink-whisper` |

## Observed (reproduced live)

### 1. Turns endpoint returns empty transcripts, with no error, when audio arrives faster than real time

- **Endpoint:** `wss://api.cartesia.ai/stt/turns/websocket`, `model=ink-2`
- **Repro:** Send a 5.2 s 16 kHz `pcm_s16le` clip as 100 ms chunks as fast as possible, then `{"type": "close"}`. We get `turn.start`, `turn.eager_end` and `turn.end`, each with `"transcript": ""`. Sending the same chunks paced at real time (one chunk every 100 ms) gives correct `turn.update` and `turn.end` transcripts.
- **Why it matters:** Replaying recorded audio is common in tests and demos. Empty transcripts with no error look exactly like silence, so this is easy to miss. It may be intended for a real-time model, but it isn't documented.
- **Suggestion:** Document the pacing requirement, or send a warning when input runs ahead of real time.

### 2. Word timestamps depend on the model, which the docs don't say

- **Endpoint:** `wss://api.cartesia.ai/stt/websocket` (manual finalize)
- **Repro:** Same clip, then `finalize`.
  - `model=ink-2`: `transcript` messages have `text` and `is_final`, no `words` (also with `timestamp_granularities=word`).
  - `model=ink-whisper` with `timestamp_granularities=word`: `words` with `start` and `end` are returned.
- **Why it matters:** The reference lists `words` as an optional field without saying which models return it. For our use case we need both key terms (only on `ink-2`) and word timestamps (only on `ink-whisper`), so today we'd run two streams.
- **Suggestion:** Note model support next to `words`. Longer term, word timestamps on `ink-2` (see request A).

## Observed intermittently (not yet reproducible on demand)

Seen while running our demo repeatedly between about 2 and 3 AM PT on 2026-10-24. We're reporting the numbers, not claiming a cause.

- **STT WebSocket handshakes sometimes hang.** Opening `wss://api.cartesia.ai/stt/websocket` or `/stt/turns/websocket` occasionally timed out during the opening handshake (10 s default timeout). It happened several times in about 30 minutes; an immediate retry always connected.
- **Manual STT `finalize` latency varied widely** for the same 4 s clip: 76 ms, 91 ms, 143 ms, about 1.3 s, 3.4 s, 6.8 s and 7.4 s across runs within the same hour.
- **Turns endpoint occasionally returns an empty `turn.end`** for a clear utterance: about 2 in 25 paced runs of the same clip, with or without key terms (8 of 8 succeeded each way in a controlled comparison).

## Feature requests

- **A. Word timestamps on `ink-2`, and on the turns endpoint.** `turn.update` and `turn.end` only carry text. Word times would let a readback checker point at the exact word that was wrong.
- **B. Update key terms mid-stream.** The turns endpoint already accepts a mid-stream `{"type": "config"}` for turn thresholds. Accepting `keyterm` there too would avoid reconnecting when the vocabulary changes (in our case, the callsigns on a radio frequency).

## Minor docs notes

- The `pronunciation_dict_id` field in the TTS reference doesn't link to how to create a dictionary.
- Case-insensitive dictionary matching needs Sonic 3.6 (stated in the pronunciation guide, not next to the field).
- Manual STT takes plain-text `finalize`/`close`, the turns endpoint takes JSON `{"type": "close"}`. Both work; a one-line note on each page would help.

## What worked well

- Key terms: `ink-2` returned "hold short runway 33" and ATC words like "tree" exactly as spoken.
- Latency: `sonic-3.6` first audio measured 88 to 115 ms over WebSocket from our laptop (one cold first run at 214 ms). Manual STT `finalize` to final transcript: 91 to 143 ms.
- Interruption via context cancel, word timestamps on TTS, and pronunciation dictionaries all worked as documented.

## Checked and not an issue

- Key terms encoded with `+` instead of `%20` work the same (same transcript).
