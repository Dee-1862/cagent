# Proposal: use `settle_caption` in the live caption path

From Deekshith's agent, 2026-10-25. `unstep/live/room.py` is a shared file, so **nothing here has been applied**. This is the exact change for Rishit to agree to or counter, as the agent-mail rules ask. Background: `docs/24-cartesia-findings.md`, finding 2.

## The problem in one line

ink-2 streams final-text deltas about every 0.5 to 0.7 s (Rishit's R26 check), and a delta can end in the middle of a word, for example `" Cess"` then `"na one two"`. The room's `on_text` shows `so_far` as one line, so a judge can see "Cess" on the tower lane for half a second before it becomes "Cessna". The cause is documented ink-2 behaviour, not a bug (docs/24, finding 2).

## What `settle_caption` does

`settle_caption(so_far, final=False)` in `unstep/cockpit/stt.py` is already written and tested (`tests/test_cartesia_errors.py::test_settle_caption_holds_back_a_possibly_split_word`). Until the utterance is final it drops the last word, because the next delta may still extend it. With `final=True` it returns the text unchanged. The cost is about one delta of caption lag (0.5 to 0.7 s measured, so roughly that much slower on screen). The final caption is already sent separately with `final=True` when `finalize` returns, so the end text is unaffected.

## The change (one import and a few lines in `LiveRoom._pump`)

Diff against `unstep/live/room.py` at commit 660c604 (last change to that file on this branch):

```diff
--- a/unstep/live/room.py
+++ b/unstep/live/room.py
@@ -37,7 +37,7 @@
 from unstep.cockpit.memory import LocalMemory, create_memory
 from unstep.cockpit.monitor import FrequencyMonitor
 from unstep.cockpit.phraseology import parse_callsign
-from unstep.cockpit.stt import CartesiaManualSTT, FakeManualSTT, TurnEvent, build_keyterms
+from unstep.cockpit.stt import CartesiaManualSTT, FakeManualSTT, TurnEvent, build_keyterms, settle_caption
 from unstep.cockpit.tts import SAMPLE_RATE as TTS_SAMPLE_RATE, FakeTTS, chime
 from unstep.ground.mock_agents import propose
 from unstep.ground.policy import PolicyAgent
@@ -1309,8 +1309,10 @@
         def on_text(delta: str, so_far: str) -> None:
             # ink-2 streams final-text deltas while the key is still held (Rishit's live check, R26);
             # show the whole utterance so far, never the raw delta (deltas can split a word).
-            if so_far:
-                self._caption(s.id, stream_id, so_far, final=False, source="stt",
+            # settle_caption holds back the last word, which the next delta may still extend ("Cess" + "na").
+            shown = settle_caption(so_far)
+            if shown:
+                self._caption(s.id, stream_id, shown, final=False, source="stt",
                               lag_ms=now_ms() - st["sent_end_ms"])
 
         turns = self._caption_turns_stt(s) if st.get("captions", True) else None
```

Not changed on purpose:

- `_turn_captions` (the `UNSTEP_CAPTION_SOURCE=turns` path). `turn.update` carries the turn's text so far rather than deltas, so there is no reason to think it splits words (unverified: the live check below measures turns cadence, but a split word is not something it counts).
- The final caption at the end of `_pump` (`final=True`), which must show the whole text.
- The typed tower line (`"captions": False` in its stream state): no `on_text` is attached there, so it never shows deltas. Mic streams from any station go through the one `on_text` above.

## What we checked (offline, in a scratch copy, room.py in this branch untouched)

- With the diff applied, `tests/test_live_room.py` and `tests/test_live_captions.py` and `tests/test_caption_turns.py` pass (12 tests).
- The test below fails on the current `room.py` (a caption ending in "Cess" is sent) and passes with the diff.

## Test to add with it (`tests/test_caption_settle.py`, new file)

```python
"""A live caption never shows a half word: ink-2 deltas can split one ("Cess" then "na")."""

import asyncio

from unstep.clock import now_ms

from tests.test_live_captions import PartialStream, of
from tests.test_live_room import make_room, wait_for  # noqa: F401 (fixture)
from tests.test_stream_mic import frames

# (frame count, delta, so_far) as CartesiaManualSTT would call on_text; "Cess" and "thirty-" are half words
DELTAS = [(3, " Cess", "Cess"), (6, "na one", "Cessna one"), (9, " two thirty-", "Cessna one two thirty-"),
          (12, "three", "Cessna one two thirty-three")]


class SplitWordStream(PartialStream):
    async def send_audio(self, pcm):
        self.frames.append(pcm)
        for n, delta, so_far in DELTAS:
            if len(self.frames) == n and self.on_text:
                self.on_text(delta, so_far)


def test_interim_captions_never_show_a_half_word(make_room):
    async def go():
        room, atc, pilot = await make_room()
        room.stream_stt_factory = lambda s: SplitWordStream("Cessna one two thirty-three")
        for f in frames(1.5, now_ms() - 3000):
            await room.handle("N123AB", f)
        await asyncio.sleep(0.05)
        partials = [m["text"] for m in of(atc, "caption") if not m["final"]]
        assert partials and all(not t.endswith(("Cess", "thirty-")) for t in partials)
        assert "Cessna" in partials  # shown once the next word started
        await room.handle("N123AB", {"type": "mic_end"})
        await wait_for(lambda: any(m["final"] for m in of(atc, "caption")))
        assert next(m for m in of(atc, "caption") if m["final"])["text"] == "Cessna one two thirty-three"
        await room.stop()

    asyncio.run(go())
```

## Decision for Rishit

- **Agree:** apply the diff and the test, run `python -m pytest -q`, commit, and post the hash in the mailbox.
- **Counter:** if one delta of extra lag is too much for the demo (the console says "Cartesia live caption, N ms behind speech"), keep the raw `so_far` and accept the half word. Another option is to apply `settle_caption` only when the last character of the delta is not a space and the next delta has not arrived within, say, 300 ms; that needs a timer and we have not built it.
- Whichever is chosen, `scripts/cartesia_live_check.py` prints the real gap between ink-2 updates (check 1), so the lag cost can be quoted from a measurement instead of the 0.5 to 0.7 s in R26.
