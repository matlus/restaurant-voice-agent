import json
from collections import Counter
from importlib import resources
from typing import Final, cast

from voice_agent_conversation.managers.exceptions.conversation_exceptions import LogEventConversation, VoiceCatalogInvalidException
from voice_agent_conversation.managers.models.conversation_models import PresentedGender, SpeechProvider, VoiceOption


class DataManagerVoiceCatalog:
    """Reads the voice catalog bundled with the package. The file is small, so it is read on every request."""

    CATALOG_FILE_NAME: Final[str] = "voice_catalog.json"
    CATALOG_FOLDER_NAME: Final[str] = "catalog_data"
    CATALOG_SHAPE_PROBLEM: Final[str] = "must be an object with a 'voices' list"
    VOICE_KEY_FIELD_NAME: Final[str] = "voice_key"
    SPEECH_PROVIDER_FIELD_NAME: Final[str] = "speech_provider"
    PROVIDER_VOICE_ID_FIELD_NAME: Final[str] = "provider_voice_id"
    PRESENTED_GENDER_FIELD_NAME: Final[str] = "presented_gender"
    DESCRIPTION_FIELD_NAME: Final[str] = "description"
    VOICE_FIELD_NAMES: Final[tuple[str, ...]] = (
        VOICE_KEY_FIELD_NAME,
        SPEECH_PROVIDER_FIELD_NAME,
        PROVIDER_VOICE_ID_FIELD_NAME,
        PRESENTED_GENDER_FIELD_NAME,
        DESCRIPTION_FIELD_NAME,
    )

    @classmethod
    def get_voice_options(cls) -> list[VoiceOption]:
        catalog_text: str = cls._read_catalog_text()
        catalog_document: object = cls._parse_catalog_document(catalog_text)
        voice_entries: list[object] = cls._read_voice_entries(catalog_document)
        voice_options: list[VoiceOption] = cls._read_voice_options(voice_entries)
        cls._verify_catalog_invariants(voice_options)
        return voice_options

    @classmethod
    def _read_catalog_text(cls) -> str:
        return resources.files("voice_agent_conversation").joinpath(cls.CATALOG_FOLDER_NAME, cls.CATALOG_FILE_NAME).read_text(encoding="utf-8")

    @classmethod
    def _parse_catalog_document(cls, catalog_text: str) -> object:
        try:
            return json.loads(catalog_text)
        except json.JSONDecodeError as json_error:
            raise cls._create_invalid_catalog_exception(f"is not valid JSON: {json_error}") from json_error

    @classmethod
    def _read_voice_entries(cls, catalog_document: object) -> list[object]:
        if not isinstance(catalog_document, dict):
            raise cls._create_invalid_catalog_exception(cls.CATALOG_SHAPE_PROBLEM)
        voice_entries: object = cast(dict[str, object], catalog_document).get("voices")
        if not isinstance(voice_entries, list):
            raise cls._create_invalid_catalog_exception(cls.CATALOG_SHAPE_PROBLEM)
        return cast(list[object], voice_entries)

    @classmethod
    def _read_voice_options(cls, voice_entries: list[object]) -> list[VoiceOption]:
        voice_options: list[VoiceOption] = []
        entry_index: int
        voice_entry: object
        for entry_index, voice_entry in enumerate(voice_entries):
            voice_options.append(cls._read_voice_option(voice_entry, entry_index))
        return voice_options

    @classmethod
    def _verify_catalog_invariants(cls, voice_options: list[VoiceOption]) -> None:
        if not voice_options:
            raise cls._create_invalid_catalog_exception("must list at least one voice")
        voice_key_counts: Counter[str] = Counter(voice_option.voice_key for voice_option in voice_options)
        duplicated_voice_keys: list[str] = []
        voice_key: str
        voice_key_count: int
        for voice_key, voice_key_count in voice_key_counts.items():
            if voice_key_count > 1:
                duplicated_voice_keys.append(voice_key)
        if duplicated_voice_keys:
            raise cls._create_invalid_catalog_exception(f"lists the same voice_key more than once: {', '.join(duplicated_voice_keys)}")

    @classmethod
    def _read_voice_option(cls, voice_entry: object, entry_index: int) -> VoiceOption:
        if not isinstance(voice_entry, dict):
            raise cls._create_invalid_catalog_exception(f"voice {entry_index} must be an object")
        voice_fields: dict[str, object] = cast(dict[str, object], voice_entry)
        voice_text_by_field_name: dict[str, str] = {}
        field_name: str
        for field_name in cls.VOICE_FIELD_NAMES:
            field_value: object = voice_fields.get(field_name)
            if not isinstance(field_value, str) or field_value.strip() == "":
                raise cls._create_invalid_catalog_exception(f"voice {entry_index} must have a non-empty text '{field_name}'")
            voice_text_by_field_name[field_name] = field_value.strip()
        try:
            speech_provider: SpeechProvider = SpeechProvider(voice_text_by_field_name[cls.SPEECH_PROVIDER_FIELD_NAME])
            presented_gender: PresentedGender = PresentedGender(voice_text_by_field_name[cls.PRESENTED_GENDER_FIELD_NAME])
        except ValueError as value_error:
            permitted_values: str = (
                f"speech_provider must be one of {', '.join(SpeechProvider)}; presented_gender must be one of {', '.join(PresentedGender)}"
            )
            raise cls._create_invalid_catalog_exception(
                f"voice {entry_index} has an unknown provider or gender: {value_error} ({permitted_values})"
            ) from value_error
        return VoiceOption(
            voice_key=voice_text_by_field_name[cls.VOICE_KEY_FIELD_NAME].lower(),
            speech_provider=speech_provider,
            provider_voice_id=voice_text_by_field_name[cls.PROVIDER_VOICE_ID_FIELD_NAME],
            presented_gender=presented_gender,
            description=voice_text_by_field_name[cls.DESCRIPTION_FIELD_NAME],
        )

    @classmethod
    def _create_invalid_catalog_exception(cls, problem: str) -> VoiceCatalogInvalidException:
        return VoiceCatalogInvalidException(
            message=f"The bundled voice catalog {cls.CATALOG_FILE_NAME} {problem}.",
            log_event=LogEventConversation.VOICE_CATALOG_READ,
            contextual_data_by_name={"VoiceCatalog.FileName": cls.CATALOG_FILE_NAME},
        )
