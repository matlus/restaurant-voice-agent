from dataclasses import dataclass


@dataclass(frozen=True)
class CallLimitSettings:
    """How far one process lets calls run. Every open call holds a paid speech provider session, so each limit bounds spend.

    A call ends with a spoken goodbye once it has lasted maximum_call_seconds, or once the guest has not spoken for
    maximum_silence_seconds.
    """

    maximum_call_seconds: float
    maximum_silence_seconds: float
