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

## To check once we have an API key

- Whether our raw WebSocket clients match the live message shapes (see `scripts/smoke_cartesia.py` once added).
- Key term accuracy on ATC phrases ("hold short", "niner", "tree", callsigns).
- How turn detection handles short radio-style turns with squelch noise.
