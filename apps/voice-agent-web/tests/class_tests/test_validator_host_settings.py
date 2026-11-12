# Class tests for ValidatorHostSettings. They prove allowed origins come back normalized, that an allowed origin naming
# no scheme and a call limit below one are refused with a HostSettingException naming the setting and the value, and
# that a port outside 1 to 65535 is refused, and that create_app refuses such a setting while it assembles the host, before the first request.

from typing import Final

import pytest
from web_test_support.asserter_host_setting_exception import AsserterHostSettingException, ExpectedHostSettingRefusal
from web_test_support.generated_words import create_generated_word

from voice_agent_conversation import DomainFacade
from voice_agent_web.exceptions.host_setting_exception import HostSettingException
from voice_agent_web.main import create_app
from voice_agent_web.validators.validator_host_settings import ValidatorHostSettings

ALLOWED_ORIGINS_SETTING_NAME: Final[str] = "allowed_origins"
MAXIMUM_CONCURRENT_CALLS_SETTING_NAME: Final[str] = "maximum_concurrent_calls"
PORT_SETTING_NAME: Final[str] = "port"
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
        booking_site_host: str = f"{create_generated_word().lower()}.example.com"
        booking_site_origin: str = f"https://{booking_site_host}"
        # Already in normal form, so it comes back unchanged.
        local_site_origin: str = f"http://{create_generated_word().lower()}.test:5173"
        expected_allowed_origins: frozenset[str] = frozenset({booking_site_origin, local_site_origin})

        actual_allowed_origins: frozenset[str] = ValidatorHostSettings.validate_allowed_origins(
            [f"HTTPS://{booking_site_host.capitalize()}/", f" {booking_site_origin} ", local_site_origin]
        )

        assert actual_allowed_origins == expected_allowed_origins

    def test_ValidateAllowedOrigins_WhenAnOriginNamesNoScheme_ThenAHostSettingExceptionNamesTheSettingAndTheOrigin(self) -> None:
        expected_host_setting_refusal: ExpectedHostSettingRefusal = ExpectedHostSettingRefusal(
            setting_name=ALLOWED_ORIGINS_SETTING_NAME,
            setting_value=BARE_HOST_ORIGIN,
            message_phrases=(BARE_HOST_ORIGIN, "must name a scheme and a host"),
        )

        with pytest.raises(HostSettingException) as raised:
            ValidatorHostSettings.validate_allowed_origins([f"https://{BARE_HOST_ORIGIN}", BARE_HOST_ORIGIN])

        AsserterHostSettingException.assert_refused_host_setting_is_as_expected(expected_host_setting_refusal, raised.value)

    @pytest.mark.parametrize("maximum_concurrent_calls", [pytest.param(0, id="zero"), pytest.param(-3, id="negative")])
    def test_ValidateMaximumConcurrentCalls_WhenBelowOne_ThenAHostSettingExceptionNamesTheSettingAndTheValue(
        self, maximum_concurrent_calls: int
    ) -> None:
        expected_host_setting_refusal: ExpectedHostSettingRefusal = ExpectedHostSettingRefusal(
            setting_name=MAXIMUM_CONCURRENT_CALLS_SETTING_NAME, setting_value=str(maximum_concurrent_calls), message_phrases=("must be at least 1",)
        )

        with pytest.raises(HostSettingException) as raised:
            ValidatorHostSettings.validate_maximum_concurrent_calls(maximum_concurrent_calls)

        AsserterHostSettingException.assert_refused_host_setting_is_as_expected(expected_host_setting_refusal, raised.value)

    def test_CreateApp_WhenAnAllowedOriginNamesNoScheme_ThenTheHostIsRefusedBeforeTheDomainIsBuilt(self) -> None:
        domain_facade_factory_recording: DomainFacadeFactoryRecording = DomainFacadeFactoryRecording()
        expected_outcome: tuple[str, int] = (ALLOWED_ORIGINS_SETTING_NAME, 0)

        with pytest.raises(HostSettingException) as raised:
            create_app(domain_facade_factory_recording, allowed_origins=[BARE_HOST_ORIGIN])

        actual_outcome: tuple[str, int] = (raised.value.setting_name, domain_facade_factory_recording.build_count)
        assert actual_outcome == expected_outcome

    @pytest.mark.parametrize("port", [pytest.param(0, id="zero"), pytest.param(65_536, id="above the highest port")])
    def test_ValidatePort_WhenOutsideTheRange_ThenAHostSettingExceptionNamesTheSettingAndTheValue(self, port: int) -> None:
        expected_host_setting_refusal: ExpectedHostSettingRefusal = ExpectedHostSettingRefusal(
            setting_name=PORT_SETTING_NAME, setting_value=str(port), message_phrases=("must be between 1 and 65535",)
        )

        with pytest.raises(HostSettingException) as raised:
            ValidatorHostSettings.validate_port(port)

        AsserterHostSettingException.assert_refused_host_setting_is_as_expected(expected_host_setting_refusal, raised.value)

    def test_ValidateAllowedOrigins_WhenAnOriginSpellsOutItsSchemesDefaultPort_ThenItComesBackAsABrowserSendsIt(self) -> None:
        booking_site_host: str = f"{create_generated_word().lower()}.example.com"
        expected_allowed_origins: frozenset[str] = frozenset({f"https://{booking_site_host}"})

        actual_allowed_origins: frozenset[str] = ValidatorHostSettings.validate_allowed_origins([f"https://{booking_site_host}:443"])

        assert actual_allowed_origins == expected_allowed_origins

    def test_ValidateAllowedOrigins_WhenAnOriginCarriesAUserName_ThenItIsRefusedBecauseNoBrowserSendsOne(self) -> None:
        origin_with_user_name: str = f"https://{create_generated_word().lower()}@{create_generated_word().lower()}.example.com"
        expected_host_setting_refusal: ExpectedHostSettingRefusal = ExpectedHostSettingRefusal(
            setting_name=ALLOWED_ORIGINS_SETTING_NAME, setting_value=origin_with_user_name, message_phrases=("must name a scheme and a host",)
        )

        with pytest.raises(HostSettingException) as raised:
            ValidatorHostSettings.validate_allowed_origins([origin_with_user_name])

        AsserterHostSettingException.assert_refused_host_setting_is_as_expected(expected_host_setting_refusal, raised.value)

    def test_ValidateAllowedOrigins_WhenAnOriginNamesAnIpv6Address_ThenItComesBackWithTheAddressStillInBrackets(self) -> None:
        local_ipv6_origin: str = "http://[::1]:5173"
        expected_allowed_origins: frozenset[str] = frozenset({local_ipv6_origin})

        actual_allowed_origins: frozenset[str] = ValidatorHostSettings.validate_allowed_origins([local_ipv6_origin])

        assert actual_allowed_origins == expected_allowed_origins
