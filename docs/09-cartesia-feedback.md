# Cartesia Feedback and Bug Reports

Issues and friction we hit while building Unstep on Cartesia (Sonic TTS, Ink-2 STT). The Cartesia team asked for feedback, so we log everything here as we find it.

| Field | Value |
| --- | --- |
| Last updated | 2026-10-23 |
| API version used | `cartesia_version` 2026-08-14 |
| Models | `sonic-3.6`, `ink-2` |

**Status key:** **Docs**: found by reading the docs, not yet confirmed against the live API. **Confirmed**: reproduced against the live API. **Request**: a feature request, not a bug.

## Summary

| ID | Area | Title | Status | Severity |
| --- | --- | --- | --- | --- |
| CF-1 | STT | Turns endpoint has no word timestamps | Request | Medium |
| CF-2 | STT | Key terms can't be changed mid-stream | Request | Medium |
| CF-3 | STT | Manual vs turns endpoints use different close/finalize message formats | Docs | Low |
| CF-4 | STT | Deprecated `is_final` still present on `flush_done` and `done` | Docs | Low |
| CF-5 | TTS | No "urgent" or "alert" emotion for safety-critical speech | Request | Low |
| CF-6 | TTS | Pronunciation dictionary create endpoint is hard to find from the TTS reference | Docs | Low |
| CF-7 | TTS | Case-insensitive dictionary matching needs Sonic 3.6, not stated on the TTS reference | Docs | Low |
| CF-8 | TTS | Latency claim doesn't say what it measures | Docs | Low |
| CF-9 | STT | `ink-2` returns no word timestamps; `ink-whisper` does but has no key terms | Confirmed | High |
| CF-10 | STT | Turns endpoint returns empty transcripts, with no error, when audio arrives faster than real time | Confirmed | Medium |
| CF-11 | Auth | REST uses `Authorization: Bearer` plus `Cartesia-Version`, WebSockets use `X-API-Key` | Docs | Low |
| CF-12 | STT | Key terms must be `%20`-encoded; standard `+` encoding of spaces is not mentioned as supported | Docs | Low |

## Details

### CF-1: Turns endpoint has no word timestamps

- **Where:** `wss://api.cartesia.ai/stt/turns/websocket`
- **What:** The manual endpoint (`/stt/websocket`) returns `words` with `start` and `end`. The turns endpoint only returns cumulative `transcript` text in `turn.update` and `turn.end`.
- **Why it matters:** We use turn detection for pilot readbacks, and word times would let us highlight exactly which words were read back wrong. Today we must choose between turn detection and word timing.
- **Ask:** Add optional `words` to `turn.update` and `turn.end`.

### CF-2: Key terms can't be changed mid-stream

- **Where:** `keyterm` query parameter on both STT endpoints.
- **What:** Key terms are fixed when the connection opens. The turns endpoint already accepts a mid-stream `{"type": "config"}` for turn thresholds, but not for key terms.
- **Why it matters:** On an ATC frequency the set of callsigns changes every few minutes. We have to reconnect, and risk dropping audio, every time an aircraft joins.
- **Ask:** Allow `keyterm` in the `config` message.

### CF-3: Different close/finalize message formats

- **Where:** STT manual vs turns endpoints.
- **What:** The manual endpoint takes plain-text `finalize` and `close` commands. The turns endpoint takes JSON `{"type": "close"}`. Easy to get wrong when one client supports both.
- **Ask:** Accept the JSON form on both, or call out the difference on each page.

### CF-4: Deprecated `is_final` still present

- **Where:** `flush_done` and `done` messages on `/stt/websocket`.
- **What:** The docs mark `is_final` on these messages as deprecated, but `transcript` messages still rely on `is_final`. It's unclear whether client code should ignore the field only on `flush_done` and `done`.
- **Ask:** A short migration note.

### CF-5: No "urgent" emotion

- **Where:** `generation_config.emotion` (`neutral`, `calm`, `angry`, `content`, `sad`).
- **What:** There's no option between calm and angry for alerts. We use `calm` plus higher `speed` and `volume`.
- **Ask:** An "alert" or "urgent but calm" option for safety and accessibility use cases.

### CF-6: Pronunciation dictionary create endpoint is hard to find

- **Where:** TTS WebSocket reference lists `pronunciation_dict_id` but doesn't link to how to create one. Third-party SDK issues (for example the Vercel AI SDK) report the same confusion.
- **Ask:** Link "Create a pronunciation dictionary" directly from the `pronunciation_dict_id` field.

### CF-7: Case-insensitive matching needs Sonic 3.6

- **Where:** Custom pronunciations guide says `case_sensitive: false` needs Sonic 3.6 or later. The TTS reference doesn't mention it.
- **Ask:** Note the model requirement next to `pronunciation_dict_id`.

### CF-8: Latency claim doesn't say what it measures

- **Where:** Marketing pages say "first audio in under 90 ms". Third-party tests of Sonic 3 including network report about 166 to 190 ms.
- **What:** It's not stated whether 90 ms is model-only, server-side, or end to end, or from which region.
- **Ask:** State the measurement point and region, so builders can quote it correctly.

### CF-9: `ink-2` returns no word timestamps, and `ink-whisper` has no key terms (Confirmed)

- **Where:** `wss://api.cartesia.ai/stt/websocket`, `cartesia_version` 2026-08-14, tested 2026-10-23.
- **Repro:** Stream a 5.2 s 16 kHz PCM clip, send `finalize`.
  - `model=ink-2`: `transcript` messages have `text` and `is_final` only. No `words`, also with `timestamp_granularities=word`.
  - `model=ink-whisper` with `timestamp_granularities=word`: `words` with `start` and `end` are returned (words carry a leading space, e.g. `" Advisory."`).
- **Why it matters:** The docs list `words` as an optional field on the manual endpoint without saying which models return it. Key terms only work on `ink-2`/`ink-preview`. For ATC we need both: key terms for callsigns and runways, and word timestamps to mark which words were blocked. Today we must pick one or run two streams.
- **Ask:** Word timestamps on `ink-2`, or key terms on `ink-whisper`, and state model support next to `words` in the docs.

### CF-10: Turns endpoint returns empty transcripts when audio is sent faster than real time (Confirmed)

- **Where:** `wss://api.cartesia.ai/stt/turns/websocket`, `model=ink-2`.
- **Repro:** Send a whole 5.2 s clip in 100 ms chunks as fast as possible, then `{"type": "close"}`. Events arrive (`turn.start`, `turn.eager_end`, `turn.end`) but every `transcript` is `""`. Sending the same chunks paced at real time gives full, correct `turn.update` and `turn.end` transcripts.
- **Why it matters:** Pre-recorded audio, tests and replays are common. Empty transcripts with no error or warning are easy to mistake for silence.
- **Ask:** Either process burst audio correctly, or send an `error` or warning when input runs ahead of real time. Document the pacing requirement.

### CF-11: Different auth for REST and WebSockets

- **What:** REST endpoints (`/voices`, pronunciation dictionaries) use `Authorization: Bearer` plus a `Cartesia-Version` header. WebSockets use `X-API-Key` and a `cartesia_version` query parameter.
- **Ask:** Accept both forms everywhere, or put the difference in one place in the docs.

### CF-12: Key term encoding

- **What:** The key term docs say to join multi-word phrases with `%20`. Most URL libraries (Python's `urlencode` by default) encode spaces as `+`. Our first client did, and it's not documented whether the server treats `+` as a space.
- **Ask:** Accept `+` as a space, or call it out explicitly.

## Measured numbers (2026-10-23, from our laptop)

| Measure | Value | Notes |
| --- | --- | --- |
| TTS first audio, `sonic-3.6` WebSocket | 214 ms | One 5.2 s advisory, includes network |
| TTS total generation | 1427 ms | Same sentence |
| STT `ink-2` key-term transcript | Correct | "likely hold short runway tree tree" came back exactly |

## To check once we have an API key

- ~~Whether our raw WebSocket clients match the live message shapes~~ Checked: TTS and both STT endpoints work with our clients (`scripts/smoke_cartesia.py`).
- Key term accuracy on ATC phrases ("hold short", "niner", "tree", callsigns).
- How turn detection handles short radio-style turns with squelch noise.
