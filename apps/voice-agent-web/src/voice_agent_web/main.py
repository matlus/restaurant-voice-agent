from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path

from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from voice_agent_conversation import DomainFacade
from voice_agent_web.handlers.conversation_handler import ConversationHandler
from voice_agent_web.middleware.middleware_exception_translation import MiddlewareExceptionTranslation

type DomainFacadeFactory = Callable[[], DomainFacade]


def create_app(create_domain_facade: DomainFacadeFactory = DomainFacade) -> FastAPI:
    """Assembles the host. The one DomainFacade lives as long as the app; tests pass a factory that builds it on a test locator."""
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
        middleware=[Middleware(MiddlewareExceptionTranslation)],
        routes=[
            Route("/voices", conversation_handler.list_voices, methods=["GET"]),
            WebSocketRoute("/conversation", conversation_handler.hold_conversation),
            Mount("/", StaticFiles(directory=static_folder, html=True)),
        ],
    )
