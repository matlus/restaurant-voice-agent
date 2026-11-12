from collections.abc import AsyncGenerator, Callable, Collection
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path

from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.routing import Mount, Route, WebSocketRoute

from voice_agent_conversation import DomainFacade
from voice_agent_web.configuration_providers.host_settings_provider import HostSettingsProvider
from voice_agent_web.handlers.conversation_handler import ConversationHandler
from voice_agent_web.middleware.call_admission import create_call_admission
from voice_agent_web.middleware.middleware_exception_translation import MiddlewareExceptionTranslation
from voice_agent_web.middleware.middleware_websocket_origin import MiddlewareWebSocketOrigin
from voice_agent_web.static_assets.static_assets_app import StaticAssetsApp
from voice_agent_web.validators.validator_host_settings import ValidatorHostSettings

type DomainFacadeFactory = Callable[[], DomainFacade]


def create_app(
    create_domain_facade: DomainFacadeFactory = DomainFacade,
    allowed_origins: Collection[str] = (),
    maximum_concurrent_calls: int = HostSettingsProvider.DEFAULT_MAXIMUM_CONCURRENT_CALLS,
) -> FastAPI:
    """Assembles the host. The one DomainFacade lives as long as the app; tests pass a factory that builds it on a test locator.

    allowed_origins names the sites other than this host whose pages may open a call; maximum_concurrent_calls bounds
    how many calls, each holding a paid speech provider session, run at once. Both are checked here, before anything is
    built, because the middleware below is only built on the first request, where a bad setting would fail every request
    instead of stopping startup.
    """
    normalized_allowed_origins: frozenset[str] = ValidatorHostSettings.validate_allowed_origins(allowed_origins)
    call_slot_count: int = ValidatorHostSettings.validate_maximum_concurrent_calls(maximum_concurrent_calls)
    domain_facade: DomainFacade = create_domain_facade()
    conversation_handler: ConversationHandler = ConversationHandler(domain_facade)
    # importlib.resources finds the page inside the installed package wherever it is installed, but returns a
    # Traversable, which StaticFiles cannot take; for an installed package it names a real folder, so it becomes a Path.
    static_folder: Path = Path(str(resources.files("voice_agent_web").joinpath("static")))

    @asynccontextmanager
    async def close_domain_facade_on_shutdown(_app: FastAPI) -> AsyncGenerator[None]:
        async with domain_facade:
            yield

    return FastAPI(
        title="Ember & Sprout voice agent",
        lifespan=close_domain_facade_on_shutdown,
        middleware=[
            Middleware(MiddlewareExceptionTranslation),
            Middleware(MiddlewareWebSocketOrigin, allowed_origins=normalized_allowed_origins),
            Middleware(create_call_admission, maximum_concurrent_calls=call_slot_count),
        ],
        routes=[
            Route("/healthz", conversation_handler.check_health, methods=["GET"]),
            Route("/voices", conversation_handler.list_voices, methods=["GET"]),
            WebSocketRoute("/conversation", conversation_handler.hold_conversation),
            Mount("/", StaticAssetsApp(static_folder)),
        ],
    )
