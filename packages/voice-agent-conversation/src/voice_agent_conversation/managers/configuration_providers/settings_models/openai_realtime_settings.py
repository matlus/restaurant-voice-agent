from dataclasses import dataclass, field


@dataclass(frozen=True)
class OpenAIRealtimeSettings:
    """How to reach the OpenAI Realtime API. The key is kept out of repr so it never reaches a log.

    websocket_base_url is None unless the Realtime service lives somewhere other than OpenAI's default address.
    """

    api_key: str = field(repr=False)
    model: str
    websocket_base_url: str | None
