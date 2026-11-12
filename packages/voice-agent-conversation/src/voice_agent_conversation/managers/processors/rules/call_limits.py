from typing import Final

from voice_agent_conversation.managers.configuration_providers.settings_models.call_limit_settings import CallLimitSettings
from voice_agent_conversation.managers.models.conversation_models import CallLimit, GuestSpeechActivity


class CallLimits:
    """When a call has run too long or the guest has gone quiet for too long. Times are seconds on one monotonic clock.

    Silence is counted from when the guest last started or stopped speaking, or from the start of the call if they have
    not spoken yet; it does not grow while the guest is talking.
    """

    # How long a farewell may take before the call is ended without it. A goodbye takes a few seconds to speak.
    FAREWELL_GRACE_SECONDS: Final[float] = 15.0

    @staticmethod
    def find_reached_call_limit(
        call_limit_settings: CallLimitSettings, call_started_at: float, guest_speech_activity: GuestSpeechActivity, now: float
    ) -> CallLimit | None:
        if now - call_started_at >= call_limit_settings.maximum_call_seconds:
            return CallLimit.MAXIMUM_DURATION
        if not guest_speech_activity.guest_is_speaking and now - guest_speech_activity.last_heard_at >= call_limit_settings.maximum_silence_seconds:
            return CallLimit.MAXIMUM_SILENCE
        return None

    @staticmethod
    def count_seconds_until_a_limit_could_be_reached(
        call_limit_settings: CallLimitSettings, call_started_at: float, guest_speech_activity: GuestSpeechActivity, now: float
    ) -> float:
        """How long nothing can change the answer of find_reached_call_limit, unless the guest's activity changes first.
        A guest who is talking cannot reach the silence limit sooner than a full silence from now."""
        silence_starts_at: float = now if guest_speech_activity.guest_is_speaking else guest_speech_activity.last_heard_at
        seconds_until_maximum_duration: float = call_started_at + call_limit_settings.maximum_call_seconds - now
        seconds_until_maximum_silence: float = silence_starts_at + call_limit_settings.maximum_silence_seconds - now
        return max(0.0, min(seconds_until_maximum_duration, seconds_until_maximum_silence))
