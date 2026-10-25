# Corrections for docs/09-cartesia-feedback.md (for Rishit to apply)

docs/09 is Rishit's file, so this is a patch to copy in, not an edit. Written by Deekshith's agent, 2026-10-25. The reasons are in `docs/24-cartesia-findings.md` (findings 2 and 5). Both corrections come from our own re-test and from Cartesia's pages as found by web search. We could not fetch docs.cartesia.ai from the sandbox, so **re-read the two Cartesia pages named below before this goes to Cartesia** (marked "unverified" where it matters).

Apply each block by replacing the exact `OLD` text with the `NEW` text. Line numbers are for `docs/09-cartesia-feedback.md` at commit ec9b976.

## Correction 1: item 1, line 17 ("Why it matters")

Why it is stale: the re-test paragraph a few lines below says the empty transcripts did not reproduce (fast 15/15 and paced 15/15 correct). The line still says the behaviour is "not documented" as if it were a known fact about the service. We saw it once. What we can support is a doc gap about what happens if audio is sent faster than real time.

OLD (line 17):

```
- **Why it matters:** Replaying recorded audio is common in tests and demos. Empty transcripts with no error look exactly like silence, so this is easy to miss. It may be intended for a real-time model, but it isn't documented.
```

NEW:

```
- **Why it matters:** Replaying recorded audio is common in tests and demos. If it happens, empty transcripts with no error look exactly like silence, so it would be easy to miss. We saw it once and have not reproduced it (see the re-test below), so we are not claiming a cause. The turns example we found sends 100 ms chunks with a real-time sleep, but we found no statement of what happens when audio arrives faster than that (unverified: shallow search, re-read the turns page).
```

Same overclaim elsewhere, for whoever owns it: the intro sentence on line 3 says everything under "Observed" was reproduced, which item 1 no longer is. Suggested: "Everything under "Observed" was seen against the live API; item 1 was seen once and did not reproduce in the re-test." The `send_paced` docstring in `unstep/cockpit/stt.py` and a comment in `unstep/cockpit/edge.py` still cite "docs/09 CF-10" for "returns empty transcripts when sent fast"; that label does not exist in this file and the claim is stronger than the evidence.

## Correction 2: item 2, heading (line 22) and "Why it matters" (line 28)

Why it is stale: both say the docs do not say which models return word timestamps. Search results from Cartesia's own manual-finalize migration pages say `ink-2` does not return word timing yet and that only `ink-whisper` supports timestamps (unverified: from search results, not fetched). So the behaviour we measured is documented. What remains true is that we found `timestamp_granularities` only in the REST example, not on the WebSocket reference page, and that model support is spread over several pages.

OLD (line 22):

```
### 2. Word timestamps depend on the model, which the docs don't say
```

NEW:

```
### 2. Word timestamps depend on the model; documented on the migration pages, not next to the field
```

OLD (line 28):

```
- **Why it matters:** The reference lists `words` as an optional field without saying which models return it. For our use case we need both key terms (only on `ink-2`) and word timestamps (only on `ink-whisper`), so today we'd run two streams.
```

NEW:

```
- **Why it matters:** This matches what Cartesia's migration pages say (as found by search, re-read before sending): `ink-2` has no word timing yet and only `ink-whisper` supports timestamps, so it is documented behaviour, not a bug. What we could not find is that note next to the `words` field on the WebSocket reference, or `timestamp_granularities` outside the REST example. For our use case we need both key terms (only on `ink-2`) and word timestamps (only on `ink-whisper`), so today we'd run two streams.
```

The "Request" section further down ("Note which models return `words`, next to the field") stays as it is: it asks for exactly the remaining gap.

## Checklist before sending anything to Cartesia

- Re-read the Cartesia STT migration pages and the WebSocket reference for `words` and `timestamp_granularities`.
- Re-read the turns endpoint page for any statement about audio sent faster than real time.
- Do not quote plan concurrency numbers (docs/24 finding 3) until the plan tier of our key is known.
