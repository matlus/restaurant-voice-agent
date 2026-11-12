from dataclasses import dataclass

from voice_agent_web.exceptions.host_setting_exception import HostSettingException


@dataclass(frozen=True)
class ExpectedHostSettingRefusal:
    """What a refused host setting must say: which setting, the value it was given, and phrases its message carries."""

    setting_name: str
    setting_value: str
    message_phrases: tuple[str, ...]


class AsserterHostSettingException:
    """Compares a HostSettingException with the refusal a scenario expects, reporting every difference at once."""

    @staticmethod
    def assert_refused_host_setting_is_as_expected(
        expected_host_setting_refusal: ExpectedHostSettingRefusal, actual_host_setting_exception: HostSettingException
    ) -> None:
        mismatch_messages: list[str] = AsserterHostSettingException.find_refused_host_setting_mismatches(
            expected_host_setting_refusal, actual_host_setting_exception
        )
        failure_report: str = "\n".join(mismatch_messages)
        assert not mismatch_messages, f"The refused host setting is not as expected; {len(mismatch_messages)} mismatches:\n{failure_report}"

    @staticmethod
    def find_refused_host_setting_mismatches(
        expected_host_setting_refusal: ExpectedHostSettingRefusal, actual_host_setting_exception: HostSettingException
    ) -> list[str]:
        actual_message: str = str(actual_host_setting_exception)
        mismatch_messages: list[str] = []
        if actual_host_setting_exception.setting_name != expected_host_setting_refusal.setting_name:
            mismatch_messages.append(
                f"setting_name: expected {expected_host_setting_refusal.setting_name!r}, actual {actual_host_setting_exception.setting_name!r}"
            )
        if actual_host_setting_exception.setting_value != expected_host_setting_refusal.setting_value:
            mismatch_messages.append(
                f"setting_value: expected {expected_host_setting_refusal.setting_value!r}, actual {actual_host_setting_exception.setting_value!r}"
            )
        mismatch_messages.extend(
            f"message: expected the phrase {message_phrase!r} in {actual_message!r}"
            for message_phrase in expected_host_setting_refusal.message_phrases
            if message_phrase not in actual_message
        )
        return mismatch_messages
