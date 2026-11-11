import json
from importlib import resources
from typing import Any

from voice_agent_conversation import PresentedGender, SpeechProvider, VoiceOption


def read_catalog_voice_option(voice_key: str) -> VoiceOption:
    """The voice the bundled catalog offers under voice_key, read from the catalog file itself so tests never copy it."""
    catalog_object: dict[str, Any] = json.loads(
        resources.files("voice_agent_conversation").joinpath("catalog_data", "voice_catalog.json").read_text(encoding="utf-8")
    )
    voice_objects: list[dict[str, Any]] = [voice_object for voice_object in catalog_object["voices"] if voice_object["voice_key"] == voice_key]
    assert len(voice_objects) == 1, f"The bundled voice catalog must offer exactly one voice '{voice_key}'; found {voice_objects!r}"
    voice_object: dict[str, Any] = voice_objects[0]
    return VoiceOption(
        voice_key=voice_object["voice_key"],
        speech_provider=SpeechProvider(voice_object["speech_provider"]),
        provider_voice_id=voice_object["provider_voice_id"],
        presented_gender=PresentedGender(voice_object["presented_gender"]),
        description=voice_object["description"],
    )
