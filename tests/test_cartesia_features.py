"""Cartesia features: the private advisory in the pilot's language, and slower corrections."""

import asyncio

from unstep.cockpit.translate import FakeTranslator, digits, keeps_numbers, translate_advisory
from unstep.cockpit.tts import AdvisoryVoice, CartesiaTTS, FakeTTS


def test_digits_and_number_check():
    assert digits("Cessna 1-2-3, hold short Runway 33") == ["1", "2", "3", "3", "3"]
    assert keeps_numbers("Cessna 1-2-3, hold short Runway 33", "Aviso. Cessna 123, espere antes de la pista 33")
    assert not keeps_numbers("Cessna 1-2-3, hold short Runway 33", "Aviso. Cessna 123, pista 23")
    assert not keeps_numbers("Runway 33", "")


def test_translate_advisory_falls_back_to_english_on_any_doubt():
    english = "Cessna 1-2-3, hold short Runway 33. Read back."
    ok = asyncio.run(translate_advisory(FakeTranslator(), english, "es"))
    assert ok == f"[es] {english}"
    assert asyncio.run(translate_advisory(FakeTranslator(broken=True), english, "es")) is None
    assert asyncio.run(translate_advisory(FakeTranslator(), english, "en")) is None
    assert asyncio.run(translate_advisory(FakeTranslator(), english, None)) is None
    assert asyncio.run(translate_advisory(None, english, "es")) is None
    assert asyncio.run(translate_advisory(FakeTranslator(), english, "xx")) is None


def test_cartesia_request_carries_language_and_speed(monkeypatch):
    monkeypatch.setenv("CARTESIA_API_KEY", "test")
    tts = CartesiaTTS()
    default = tts.request("hello", "ctx")
    assert default["language"] == "en"
    custom = tts.request("hola", "ctx", language="es", speed=0.85)
    assert custom["language"] == "es" and custom["generation_config"]["speed"] == 0.85
    assert tts.request("hello", "ctx")["generation_config"]["speed"] == default["generation_config"]["speed"]


def test_advisory_voice_prefix_and_options():
    seen = []

    class Recording(FakeTTS):
        async def speak(self, text, context_id=None, on_chunk=None, **options):
            seen.append((text, options))
            return await super().speak(text, context_id, on_chunk)

    voice = AdvisoryVoice(Recording())
    asyncio.run(voice.say("Readback incorrect. Runway 33.", speed=0.85))
    asyncio.run(voice.say("[es] Aviso. Pista 33.", language="es", prefix=False))
    assert seen[0][0].startswith("Advisory.") and seen[0][1] == {"speed": 0.85}
    assert seen[1][0] == "[es] Aviso. Pista 33." and seen[1][1] == {"language": "es"}
