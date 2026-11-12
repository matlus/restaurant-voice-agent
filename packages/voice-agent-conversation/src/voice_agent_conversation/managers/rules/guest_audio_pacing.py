from typing import Final

from voice_agent_conversation.managers.models.conversation_models import GuestAudioAllowance


class GuestAudioPacing:
    """Which pieces of guest speech go to the provider. Speech arrives as mono 16-bit PCM, and the provider charges for all
    of it, so a piece larger than any page sends is dropped, and so is speech arriving faster than it could be spoken.

    The allowance starts full, refills at the speaking rate and never holds more than a burst, so a page that catches up
    after a short stall loses nothing while a sender streaming faster than real time is held to real time.
    """

    BYTES_PER_SAMPLE: Final[int] = 2
    # The page sends 50 ms pieces; four times that leaves room for a slow audio thread without inviting large frames.
    MAXIMUM_PIECE_SECONDS: Final[float] = 0.2
    BURST_SECONDS: Final[float] = 1.0

    @classmethod
    def start_allowance(cls, guest_audio_sample_rate_hz: int, now: float) -> GuestAudioAllowance:
        return GuestAudioAllowance(available_byte_count=cls._count_bytes(cls.BURST_SECONDS, guest_audio_sample_rate_hz), measured_at=now)

    @classmethod
    def refill_allowance(cls, guest_audio_allowance: GuestAudioAllowance, guest_audio_sample_rate_hz: int, now: float) -> GuestAudioAllowance:
        earned_byte_count: float = cls._count_bytes(now - guest_audio_allowance.measured_at, guest_audio_sample_rate_hz)
        return GuestAudioAllowance(
            available_byte_count=min(
                guest_audio_allowance.available_byte_count + earned_byte_count, cls._count_bytes(cls.BURST_SECONDS, guest_audio_sample_rate_hz)
            ),
            measured_at=now,
        )

    @classmethod
    def admits_guest_speech(cls, guest_audio_allowance: GuestAudioAllowance, piece_byte_count: int, guest_audio_sample_rate_hz: int) -> bool:
        return (
            piece_byte_count <= cls._count_bytes(cls.MAXIMUM_PIECE_SECONDS, guest_audio_sample_rate_hz)
            and piece_byte_count <= guest_audio_allowance.available_byte_count
        )

    @staticmethod
    def spend_allowance(guest_audio_allowance: GuestAudioAllowance, piece_byte_count: int) -> GuestAudioAllowance:
        return GuestAudioAllowance(
            available_byte_count=guest_audio_allowance.available_byte_count - piece_byte_count, measured_at=guest_audio_allowance.measured_at
        )

    @classmethod
    def _count_bytes(cls, seconds: float, guest_audio_sample_rate_hz: int) -> float:
        return seconds * guest_audio_sample_rate_hz * cls.BYTES_PER_SAMPLE
