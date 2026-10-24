# Cartesia Feedback

Feedback from building Unstep on Cartesia (Sonic TTS, Ink STT). Everything under "Observed" was reproduced against the live API. Nothing here blocked us: Unstep runs end to end on Cartesia.

| Field | Value |
| --- | --- |
| Last updated | 2026-10-24 |
| API version | `cartesia_version` 2026-08-14 |
| Models | `sonic-3.6`, `ink-2`, `ink-whisper` |

## Observed (reproduced live)

### 1. Turns endpoint returns empty transcripts, with no error, when audio arrives faster than real time

- **Endpoint:** `wss://api.cartesia.ai/stt/turns/websocket`, `model=ink-2`
- **Repro:** Send a 5.2 s 16 kHz `pcm_s16le` clip as 100 ms chunks as fast as possible, then `{"type": "close"}`. We get `turn.start`, `turn.eager_end` and `turn.end`, each with `"transcript": ""`. Sending the same chunks paced at real time (one chunk every 100 ms) gives correct `turn.update` and `turn.end` transcripts.
- **Why it matters:** Replaying recorded audio is common in tests and demos. Empty transcripts with no error look exactly like silence, so this is easy to miss. It may be intended for a real-time model, but it isn't documented.
- **Suggestion:** Document the pacing requirement, or send a warning when input runs ahead of real time.

**Re-test 2026-10-24 ~12:30 PT (`scripts/cartesia_repro.py --runs 15`): not reproduced.** Fast and paced sends both gave 15/15 correct `turn.end` transcripts, 0 empty. We saw empty transcripts on fast input the previous night; it may have been transient or since fixed. Treat this item as unconfirmed until it reproduces again.

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

## Measured re-test, 2026-10-24 (scripts/cartesia_repro.py)

Run by Rishit on his laptop at about 12:30 PT with `python scripts/cartesia_repro.py --runs 15`, one 16 kHz clip of "hold short runway 33", `ink-2` with key terms unless noted. Only results that reproduced are listed. Full JSON stays local in `data/cartesia-repro/`.

### Observed

- **Manual finalize endpoint does not need real-time pacing.** On `wss://api.cartesia.ai/stt/websocket`, sending the clip as fast as possible then `finalize` gave 15/15 correct transcripts, 0 empty, finalize p50 901 ms, total p50 1080 ms. Paced at real time the same clip takes about 4 s before finalize can start.
- **Word timestamps depend on the model (item 2 confirmed).** `ink-2` returned 0 words, `ink-whisper` with `timestamp_granularities=word` returned 6 words.
- **Handshake:** 15/15 opened, p50 198 ms, p95 446 ms, 0 failures in this run.
- **Finalize after paced audio:** p50 162 ms, p95 547 ms, 0 of 15 over 800 ms, 0 empty.

### Request

- Say on the STT reference page whether the manual endpoint accepts audio faster than real time. It worked for us, which saves seconds when replaying recorded audio, but we only found out by testing.
- Note which models return `words`, next to the field (same as item 2 and request A).

### Checked

- Racing a second, already open socket when finalize passes 800 ms (our planned workaround) never won: 0 of 15, and one slow run (1689 ms) was not saved by it. We are not building it.
- Empty `turn.end` on fast input (item 1) did not reproduce: fast 15/15 and paced 15/15 correct.

## Lesson: a pronunciation respelling silently broke our own STT (2026-10-24)

Not a Cartesia bug; our mistake, found by closing the loop from TTS to STT in an evaluation (`scripts/eval_unstep.py --live`).

### Observed

- Our pronunciation dictionary respelled "niner" as `NY-ner`. With it, Sonic said something like "N-one-er", and ink-2 heard "N1er", "N one er" or "and liner". Every runway miss in our first live eval was this word, and both correct readbacks that were wrongly flagged were the same lines.
- A/B on Rishit's laptop, 3 runs each: with the entry, "niner" was lost 3 of 3; without it, heard as "niner" 3 of 3; "nine" was fine either way (3 of 3).
- Live eval, 40 instruction and readback pairs (80 lines, line length p50 3.68 s):

| | Callsign | Runway | Readback-error precision / recall | Finalize p50 / p95 |
| --- | --- | --- | --- | --- |
| With the `niner` entry | 0.95 | 0.852 | 0.882 / 1.0 | 598.5 / 1514 ms |
| Entry dropped | 1.0 | 1.0 | 1.0 / 1.0 | 519.8 / 1176.2 ms |

### Request

- Document the respelling format for pronunciation dictionary entries (what a hyphen or capitals mean), or warn when an entry makes the word unrecognizable. A one-line "test your entries through STT" note would have saved us the debugging.

### Checked

- Sonic says "niner" correctly with no dictionary entry, so we dropped it (Rishit's 7ff40c1, 8f60753). A new dictionary has to be uploaded with `scripts/upload_pronunciation_dict.py`; the old one still has the bad entry.

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
