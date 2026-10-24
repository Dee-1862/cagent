"""One clock for every timestamp (PRD FR-17).

All `ts`, `*_start`, `*_end` and `*_at` fields are epoch milliseconds from this
clock. The only exception is `TowerTranscript.words`, which are seconds from
`ptt_start`. Use `word_to_epoch_ms` before comparing them with an overlap window.
"""

import time


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def word_to_epoch_ms(ptt_start_ms: int, offset_s: float) -> int:
    return ptt_start_ms + round(offset_s * 1000)
