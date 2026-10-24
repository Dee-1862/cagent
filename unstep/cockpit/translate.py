"""Private advisory in the pilot's own language (Cartesia multilingual TTS).

The radio stays ICAO English. After Unstep speaks an approved directive in
English, it can repeat it in the pilot's language, as an accessibility aid for
non-native English speakers. Translation runs on Moss Inference with no
retrieval; the result is used only if every number in the English instruction
(callsign digits, runway) appears in the translation. Otherwise the pilot gets
English only. A translation never replaces the English directive.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional, Protocol

log = logging.getLogger("unstep.translate")

# Languages we offer: only ones checked live (Cartesia voice and translation meaning).
LANGUAGES = {
    "es": "Spanish",
    "hi": "Hindi",
    "fr": "French",
}

# Standard phrasing per language, so the model uses the operational term, not a literal one.
GLOSSARY = {
    "es": "'hold short of runway N' = 'espere antes de la pista N'; 'read back' = 'colacione'; 'Advisory' = 'Aviso'",
    "fr": "'hold short of runway N' = 'maintenez avant la piste N'; 'read back' = 'collationnez'; 'Advisory' = 'Avis'",
    "hi": "'hold short of runway N' = 'रनवे N से पहले रुकें'; 'read back' = 'निर्देश दोहराएं'; 'Advisory' = 'सूचना'",
}

PROMPT = (
    "Translate this air traffic advisory for a pilot into {language}. Translate the meaning, "
    "not word by word: 'hold short of Runway N' means stop and wait before entering runway N; "
    "'read back' means repeat the instruction to confirm it; 'Advisory' is a heading meaning "
    "'notice'. Translate every word including 'Advisory'. Keep every number exactly as digits "
    "(callsign digits and runway numbers) and keep aircraft type names unchanged. Reply with "
    "the translation only. Use this standard phrasing: {glossary}."
)


def digits(text: str) -> list[str]:
    """Every digit in order. "Cessna 1-2-3, Runway 33" and "123 ... 33" both give 1,2,3,3,3."""
    return re.findall(r"\d", text)


def keeps_numbers(english: str, translated: str) -> bool:
    """A translation is usable only if it carries exactly the same digits, in order."""
    return bool(translated.strip()) and digits(english) == digits(translated)


class Translator(Protocol):
    async def translate(self, text: str, language: str) -> str: ...


class MossTranslator:
    """Moss Inference, OpenAI-compatible, with server-side retrieval off."""

    def __init__(self, project_id: str, project_key: str):
        from moss.inference import MossInference

        self.client = MossInference(project_id, project_key)

    async def translate(self, text: str, language: str) -> str:
        stream = await self.client.chat.completions.create(
            model="moss", indexes=[], stream=True, cache=False,
            messages=[{"role": "system", "content": PROMPT.format(language=LANGUAGES[language], glossary=GLOSSARY[language])},
                      {"role": "user", "content": text}])
        parts = []
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                parts.append(delta)
        return "".join(parts).strip()


class FakeTranslator:
    """For tests and offline runs: tags the text and keeps it verbatim."""

    def __init__(self, broken: bool = False):
        self.broken = broken

    async def translate(self, text: str, language: str) -> str:
        if self.broken:
            return f"[{language}] runway {''.join(reversed(digits(text)))} 9"
        return f"[{language}] {text}"


def create_translator() -> Optional[Translator]:
    project_id, project_key = os.getenv("MOSS_PROJECT_ID"), os.getenv("MOSS_PROJECT_KEY")
    if not (project_id and project_key):
        return None
    try:
        return MossTranslator(project_id, project_key)
    except Exception:
        log.warning("Moss Inference unavailable; advisories stay English only")
        return None


async def translate_advisory(translator: Optional[Translator], english: str, language: Optional[str],
                             timeout_s: float = 4.0) -> Optional[str]:
    """The validated translation, or None (English only) on any doubt."""
    if not translator or not language or language == "en" or language not in LANGUAGES:
        return None
    try:
        translated = await asyncio.wait_for(translator.translate(english, language), timeout_s)
    except Exception:
        log.warning("translation to %s failed; English only", language)
        return None
    translated = " ".join(translated.split())  # the model sometimes adds line breaks
    if not keeps_numbers(english, translated):
        log.warning("translation to %s changed a number; English only", language)
        return None
    return translated
