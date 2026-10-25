# Cartesia findings: what we investigated, worked around and can report

Written by Deekshith's agent, 2026-10-25. Each finding has an evidence grade so nobody overclaims to Cartesia. We had no Cartesia network access while writing this. The "FROM DOCS" items come from Cartesia's public docs as found by web search (docs.cartesia.ai pages could not be fetched directly), so re-read the page before quoting it.

Grades: **MEASURED LIVE** (by us, numbers in this repo), **REPORTED** (Rishit's measurement, in the agent mailbox or docs/09, not re-run here), **FROM DOCS**, **COULD BE OURS**.

Ranked by how well evidenced and how much it hurt us. Only finding 1 is a plain Cartesia behaviour we measured. Findings 2 to 4 turned out to be mostly documented or our own doing, and we say so.

## 1. Manual STT tail latency and flaky handshakes (REPORTED, measured live by Rishit)

**What we saw** (docs/09 "Observed intermittently", `scripts/cartesia_repro.py`):
- Opening `/stt/websocket` or `/stt/turns/websocket` sometimes hung for the full 10 s open timeout, several times in about 30 minutes. An immediate retry always connected.
- `finalize` to final transcript for the same 4 s clip: 76, 91, 143 ms, then about 1.3, 3.4, 6.8 and 7.4 s within one hour.
- Repro run of 15 (about 12:30 PT): handshake 15/15, p50 198 ms, p95 446 ms. Finalize after paced audio p50 162 ms, p95 547 ms, 0 of 15 over 800 ms. So the slow tail did not reproduce at midday. It was seen at 2 to 3 AM PT.
- Finalize after the whole 5.2 s clip was sent at once: p50 901 ms (docs/09). Same endpoint, paced: p50 162 ms. Finalize cost grows when audio is sent in a burst. That fits the server working through a backlog, but it is our inference, not something Cartesia told us.
- Live room numbers after we stream audio while the key is held (R28): tower transcript 155 ms and cockpit 172 ms after release.

**Evidence grade:** REPORTED (Rishit's laptop; one night for the tail). Not re-run by us.

**Workaround (already in code):** `_connect` in `unstep/cockpit/stt.py` uses a 4 s open timeout and up to 3 attempts. Audio is streamed while the key is held, so `finalize` has almost nothing left to process. We tested racing a second open socket when finalize passes 800 ms: it won 0 of 15, so we did not build it (docs/09 "Checked").

**Suggested fix or doc change for Cartesia:** state expected `finalize` latency and whether it depends on how much audio is still queued. Say whether a handshake that hangs is a known cold-start effect. Give them our timestamps (2026-10-24 about 02:00 to 03:00 PT) so they can check their logs instead of trusting our numbers.

**Unverified:** whether the tail was Cartesia, our network or our laptop, and whether it still happens. We have no server-side timing.

## 2. Ink-2 has no partial results and no word timestamps; deltas can split a word (MEASURED LIVE + FROM DOCS)

**What we saw:**
- R26 (Rishit, live): the ink-2 manual endpoint sends no interim messages. While audio streams it sends `transcript` with `is_final: true` deltas about every 0.5 to 0.7 s, for example `" Cess"`, `"na one two three"`, `", hold short"`, `" thirty-"`, `"three, traffic"`. A word can be split across deltas. Implemented as `on_text` in `CartesiaManualSTT` (626a26b).
- docs/09 item 2: `ink-2` returns no `words` (also with `timestamp_granularities=word`). `ink-whisper` returns `words` with `start` and `end` (6 words in the 15-run re-test).
- `scripts/caption_probe.py` (on `rishit`, 76428c0) exists to measure update gaps for both endpoints. Its results are not in the repo, so the turns endpoint cadence is **unmeasured**.

**Correction to our own docs/09:** docs/09 says the reference does not say which models return `words`. Search results from Cartesia's own docs (the manual-finalize migration pages) say ink-2 does not return word timing yet and only ink-whisper supports timestamps, that Ink 2 and Whisper only send `is_final: true`, and that final messages are deltas to be appended without stripping whitespace. So this is **documented behaviour, not a bug**, and the word split is consistent with it. What is still a gap: we found `timestamp_granularities` only in the REST example, not on the WebSocket reference, and per-model support is spread over several pages. docs/09 should say "documented on the migration pages, not next to the field". Re-check before sending.

**Evidence grade:** MEASURED LIVE for the cadence and the split (Rishit, R26). FROM DOCS for "by design".

**Workaround:** `on_text(delta, so_far)` shows `so_far` as one line and never appends deltas. New in this change: `settle_caption(so_far, final=False)` in `unstep/cockpit/stt.py` holds back the last word until the utterance is final, so a half word like "Cess" is never drawn. The cost is about one delta of lag. `room.py` is shared and not touched here. It can call `settle_caption` in its caption path if Rishit agrees. For word timing we would need a second `ink-whisper` stream, which we have not built.

**Suggested feature request (not a bug):** word timestamps on ink-2 and on the turns endpoint (docs/09 request A), and optional interim results so live captions can update faster than one delta every 0.5 to 0.7 s.

**Unverified:** whether delta cadence depends on speech rate or clip, and whether the split is rare or common (we have examples, not a rate).

## 3. HTTP 429 with several clients: documented limits, and our leak is the likelier cause (COULD BE OURS + FROM DOCS)

**What we saw:** `eval_bench.py --live --n 200` died twice on HTTP 429 (R29). f3d78a8 says it happened "at 4 concurrent TTS connections" and added retry with backoff and concurrency 2. 9ee38bc says "the 429s were leaked websockets, not request rate: a single request still succeeds right after" and closes each socket. The hub had the same pattern (one `CartesiaTTS` per line or proposal, never closed). `room.py` now shares one connection per voice (`_voice_tts`, `_close_engine`, `_close_voices`).

**Docs check:** the candidate "the docs do not state the concurrent connection limit" is **rejected**. Cartesia's "Concurrency Limits and Timeouts" page (found by search, not fetched) lists per-plan concurrency (TTS: Free 2, Pro 3, Startup 5; STT higher). It says concurrency is counted in unique active contexts (extra messages on the same `context_id` do not count), caps parallel WebSockets at 10 times the concurrency limit, and says a 429 on opening a WebSocket usually means idle connections were not closed. Check which plan our key is on before quoting these numbers.

**Why this is probably ours, and what is not proven:** the "4 concurrent" 429 in f3d78a8 is also what a plan limit of 2 or 3 concurrent generations would produce, with no leak at all. The two fixes (concurrency 2, then closing sockets) landed one after the other, so we never isolated which one removed the 429. A leak alone should hit the 10x socket cap, which at 2 to 3 concurrency is 20 to 30 sockets, and we have no count of open sockets at failure.

**Evidence grade:** COULD BE OURS (with FROM DOCS for the limits). Not a Cartesia bug.

**Workaround:** shared, closed connections (done in `room.py` and `eval_bench.py`). New in this change: `unstep/cockpit/cartesia_errors.py`. `connect_with_backoff` retries a 429 handshake with backoff, then raises `CartesiaRateLimited` with a message that names the two documented causes. Both `CartesiaTTS.connect` and the STT `_connect` use it. A TTS error event with `status_code` 429 raises the same class (a subclass of `RuntimeError`, so existing handlers still work). Tests are in `tests/test_cartesia_errors.py`. Before this, the STT `_connect` only retried `TimeoutError` and `OSError`, so a 429 handshake failed on the first try.

**Suggested doc change for Cartesia (small):** say on the TTS and STT WebSocket reference pages, not only on the limits page, that an unclosed socket counts against the connection cap, and whether and after how long the server closes an idle socket. We saw a close after idle (comment in `CartesiaTTS.speak`) but have no number.

**Unverified:** the plan tier of our key, whether the 429 body had `error_code: concurrency_limited`, and how many sockets were open at failure. Logging the 429 body in `eval_bench.py` would settle it next time.

## 4. Pronunciation dictionary: respelling "niner" broke our own STT (COULD BE OURS; doc gap on entry format unverified)

**What we saw** (docs/09 "Lesson"): the entry `niner` as `NY-ner` made Sonic say something like "N-one-er". ink-2 heard "N1er", "N one er" or "and liner". Without the entry it was heard as "niner" 3/3, with it 0/3. Live eval of 40 pairs: runway 0.852 with the entry, 1.0 without. Fixed in 7ff40c1 and 8f60753.

**Is it TTS dictionary vs STT interplay?** No. The dictionary only changes what Sonic says (`pronunciation_dict_id` is sent on the TTS request in `CartesiaTTS.request`). STT never sees the dictionary, it just heard the bad audio. The TTS to STT loop in `scripts/eval_unstep.py --live` is what exposed it. The cause was our entry.

**Evidence grade:** COULD BE OURS (and was). The A/B is only 3 runs each, and the eval is 40 pairs on one voice.

**Workaround:** entry removed, plus a test that the dictionary must not respell niner. Still open: the `fower` ("FOW-er"), `juliett`, `quebec` and `NOTAM` respellings in `assets/pronunciation/atc.json` have not been checked through STT one by one. The eval scored 1.0 without a per-word breakdown. Adding those words to a TTS to STT round trip is the cheap next step.

**Doc gap to raise politely:** Cartesia's phoneme guide documents IPA inside `<<...>>` for Sonic-3. We could not find a page that explains the `text` / `pronunciation` entry format we use (what hyphens and capitals mean). Our search was shallow, so it may exist. Check before reporting.

**Unverified:** the exact audio Sonic produced for `NY-ner` (we have STT transcripts, not a saved clip).

## 5. Turns endpoint empty transcripts on faster-than-real-time audio (NOT REPRODUCED)

**What we saw:** on the night of 2026-10-23 to 24, empty `turn.start` / `turn.eager_end` / `turn.end` on a clip sent in 100 ms chunks as fast as possible. The 15-run re-test on 2026-10-24: fast 15/15 and paced 15/15 correct, 0 empty (docs/09). Separately, about 2 in 25 paced runs gave an empty `turn.end` for a clear clip (docs/09, intermittent, with and without key terms).

**Docs check:** the turns docs example paces 100 ms chunks with a real-time sleep and says to pace sends. A search found no statement of what happens if you send faster. That is a mild doc gap, not a bug.

**Evidence grade:** REPORTED once, then not reproduced. Do not call it a bug.

**Workaround (already in code):** `send_paced` for replay. `ReplayTurnSTT._clip_events` retries an empty final transcript once on a fresh connection. The `send_paced` docstring and docs/09 CF-10 still say the endpoint returns empty transcripts when sent fast. That is stronger than the evidence and should read "seen once, not reproduced".

**Suggested doc change:** state that turns audio should be sent at real-time pace, and what happens otherwise.

**Unverified:** whether the 2-in-25 empties share a cause with the earlier fast-send failure.

## What we can truthfully say to Cartesia

| Statement | Say it? | Basis |
| --- | --- | --- |
| Manual STT `finalize` latency had a slow tail (up to 7.4 s) and some handshakes hung for 10 s on 2026-10-24 about 02:00 to 03:00 PT; a midday 15-run test did not show it | Yes, as numbers with timestamps | REPORTED (docs/09) |
| Ink-2 sends only final-text deltas about every 0.5 to 0.7 s, which can split a word; we would like interim results | Yes, as a feature request, noting it matches the docs | MEASURED LIVE (R26) + FROM DOCS |
| Ink-2 has no word timestamps, so we would need two streams for key terms plus timing | Yes, as a feature request. Do not say "undocumented" | MEASURED LIVE + FROM DOCS |
| The WebSocket reference does not list `timestamp_granularities`, and model support for `words` is only on migration pages | Yes, after re-checking the page | FROM DOCS, shallow search |
| We hit HTTP 429 and the limits are not documented | No. They are documented | FROM DOCS |
| We hit HTTP 429 while leaking sockets and running 4 concurrent TTS calls; a doc note on socket cleanup and idle timeout would help | Yes, framed as our mistake | COULD BE OURS |
| A pronunciation respelling of "niner" broke recognition | Only as our lesson, plus a request to document the entry format if we confirm it is missing | COULD BE OURS |
| The turns endpoint returns empty transcripts on fast input | No. Say it was seen once and not reproduced in 15 runs | NOT REPRODUCED |
| About 2 in 25 paced turns runs ended with an empty `turn.end` | Yes, as an observation, with our retry | REPORTED, intermittent |

## Still to do with live access

- Run `scripts/caption_probe.py --runs 5` and save the JSON (turns cadence is unmeasured).
- Log the 429 response body and the plan tier the next time it happens.
- Per-word TTS to STT check of every entry in `assets/pronunciation/atc.json`.
- Re-read the docs.cartesia.ai pages cited here before sending anything to Cartesia.
