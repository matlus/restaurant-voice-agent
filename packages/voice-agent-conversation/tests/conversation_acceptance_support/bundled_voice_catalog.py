import json
from importlib import resources
from typing import Any

from voice_agent_conversation import PresentedGender, SpeechProvider, VoiceOption


def read_catalog_voice_options() -> list[VoiceOption]:
    """Every voice the bundled catalog offers, in catalog order, read from the catalog file itself so tests never copy it."""
    catalog_object: dict[str, Any] = json.loads(
        resources.files("voice_agent_conversation").joinpath("catalog_data", "voice_catalog.json").read_text(encoding="utf-8")
    )
    return [
        VoiceOption(
            voice_key=voice_object["voice_key"],
            speech_provider=SpeechProvider(voice_object["speech_provider"]),
            provider_voice_id=voice_object["provider_voice_id"],
            presented_gender=PresentedGender(voice_object["presented_gender"]),
            description=voice_object["description"],
        )
        for voice_object in catalog_object["voices"]
    ]


def read_catalog_voice_option(voice_key: str) -> VoiceOption:
    """Fails the test's arrangement unless the bundled catalog offers exactly one voice under voice_key."""
    matching_voice_options: list[VoiceOption] = [voice_option for voice_option in read_catalog_voice_options() if voice_option.voice_key == voice_key]
    assert len(matching_voice_options) == 1, f"The bundled voice catalog must offer exactly one voice '{voice_key}'; found {matching_voice_options!r}"
    return matching_voice_options[0]
