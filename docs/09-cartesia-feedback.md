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
