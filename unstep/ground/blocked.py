"""Find tower words lost inside a stepped-on window (B3)."""

from unstep.clock import word_to_epoch_ms
from unstep.contracts import TowerTranscript


def blocked_words(transcript: TowerTranscript, overlap_start_ms: int, overlap_end_ms: int) -> list[str]:
    """Include positive-duration words with at least half their duration blocked."""
    if overlap_end_ms <= overlap_start_ms:
        return []
    result = []
    for word in transcript.words:
        start = word_to_epoch_ms(transcript.ptt_start, word.start)
        end = word_to_epoch_ms(transcript.ptt_start, word.end)
        overlap = max(0, min(end, overlap_end_ms) - max(start, overlap_start_ms))
        if end > start and overlap * 2 >= end - start:
            result.append(word.word)
    return result
