"""Optional audio artifacts for the browser demo."""

from pathlib import Path
from uuid import uuid4

import soundfile as sf

DEFAULT_DEMO_AUDIO_DIR = Path(__file__).resolve().parents[1] / "data" / "demo" / "audio"


def save_audio(directory: Path | None, samples, sample_rate: int) -> dict:
    if directory is None:
        return {}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{uuid4().hex}.wav"
    sf.write(directory / name, samples, sample_rate, subtype="PCM_16")
    return {"audio_url": f"/demo/audio/{name}"}


def speech_payload(text: str, party: str, speech, samples, directory: Path | None,
                   offset: float = 0.0) -> dict:
    return {
        "spoken_text": text, "party": party,
        "words": [{"word": word, "start": start + offset, "end": end + offset}
                  for word, start, end in speech.words],
        **save_audio(directory, samples, speech.sample_rate),
    }
