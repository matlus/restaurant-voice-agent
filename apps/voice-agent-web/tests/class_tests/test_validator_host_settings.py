# Class tests for ValidatorHostSettings. They prove allowed origins come back normalized, that an allowed origin naming
# no scheme and a call limit below one are refused with a HostSettingException naming the setting and the value, and
# that create_app refuses such a setting while it assembles the host, before the first request.

from typing import Final

import pytest

from voice_agent_conversation import DomainFacade
from voice_agent_web.exceptions.host_setting_exception import HostSettingException
from voice_agent_web.main import create_app
from voice_agent_web.validators.validator_host_settings import ValidatorHostSettings

ALLOWED_ORIGINS_SETTING_NAME: Final[str] = "allowed_origins"
MAXIMUM_CONCURRENT_CALLS_SETTING_NAME: Final[str] = "maximum_concurrent_calls"
BARE_HOST_ORIGIN: Final[str] = "booking.example.com"


class DomainFacadeFactoryRecording:
    """Stands in for the DomainFacade factory create_app calls, counting the builds; building at all fails the test."""

    def __init__(self) -> None:
        self.build_count: int = 0

    def __call__(self) -> DomainFacade:
        self.build_count += 1
        raise AssertionError("The domain must not be built when a host setting is refused.")


class TestValidatorHostSettings:
    def test_ValidateAllowedOrigins_WhenOriginsDifferOnlyInCaseOrATrailingSlash_ThenEachComesBackOnceNormalized(self) -> None:
        expected_allowed_origins: frozenset[str] = frozenset({"https://booking.example.com", "http://localhost:5173"})

        actual_allowed_origins: frozenset[str] = ValidatorHostSettings.validate_allowed_origins(
            ["HTTPS://Booking.Example.com/", " https://booking.example.com ", "http://localhost:5173"]
        )

        assert actual_allowed_origins == expected_allowed_origins

    def test_ValidateAllowedOrigins_WhenAnOriginNamesNoScheme_ThenAHostSettingExceptionNamesTheSettingAndTheOrigin(self) -> None:
        expected_setting: tuple[str, str] = (ALLOWED_ORIGINS_SETTING_NAME, BARE_HOST_ORIGIN)
        expected_message_phrases: tuple[str, ...] = (BARE_HOST_ORIGIN, "must name a scheme and a host")

        with pytest.raises(HostSettingException) as raised:
            ValidatorHostSettings.validate_allowed_origins(["https://booking.example.com", BARE_HOST_ORIGIN])

        actual_setting: tuple[str, str] = (raised.value.setting_name, raised.value.setting_value)
        assert (actual_setting, all(phrase in str(raised.value) for phrase in expected_message_phrases)) == (expected_setting, True)

    @pytest.mark.parametrize("maximum_concurrent_calls", [pytest.param(0, id="zero"), pytest.param(-3, id="negative")])
    def test_ValidateMaximumConcurrentCalls_WhenBelowOne_ThenAHostSettingExceptionNamesTheSettingAndTheValue(
        self, maximum_concurrent_calls: int
    ) -> None:
        expected_setting: tuple[str, str] = (MAXIMUM_CONCURRENT_CALLS_SETTING_NAME, str(maximum_concurrent_calls))
        expected_message_phrase: str = "must be at least 1"

        with pytest.raises(HostSettingException) as raised:
            ValidatorHostSettings.validate_maximum_concurrent_calls(maximum_concurrent_calls)

        actual_setting: tuple[str, str] = (raised.value.setting_name, raised.value.setting_value)
        assert (actual_setting, expected_message_phrase in str(raised.value)) == (expected_setting, True)

    def test_CreateApp_WhenAnAllowedOriginNamesNoScheme_ThenTheHostIsRefusedBeforeTheDomainIsBuilt(self) -> None:
        domain_facade_factory_recording: DomainFacadeFactoryRecording = DomainFacadeFactoryRecording()
        expected_outcome: tuple[str, int] = (ALLOWED_ORIGINS_SETTING_NAME, 0)

        with pytest.raises(HostSettingException) as raised:
            create_app(domain_facade_factory_recording, allowed_origins=[BARE_HOST_ORIGIN])

        actual_outcome: tuple[str, int] = (raised.value.setting_name, domain_facade_factory_recording.build_count)
        assert actual_outcome == expected_outcome
