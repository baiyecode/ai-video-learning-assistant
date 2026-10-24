"""Application factory (composition root) and ASGI entrypoint.

Feature tickets add routes to their module router and models to their module's
``models.py`` (registered in ``models_registry.py``). This file owns process
lifecycle: configuration validation, database init, background managers and their
restart recovery.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import Settings, load_settings
from .container import Adapters, build_production_adapters
from .db import create_engine_and_sessionmaker, init_db
from .errors import register_exception_handlers
from .logging_setup import RequestContextMiddleware, configure_logging
from .modules.analysis.manager import AnalysisManager
from .modules.analysis.router import router as analysis_router
from .modules.billing.router import router as billing_router
from .modules.catalog.router import router as catalog_router
from .modules.identity.router import router as identity_router
from .modules.media.manager import DownloadManager
from .modules.media.router import router as media_router
from .modules.ops.router import router as ops_router
from .modules.ops.sentry import init_sentry

logger = logging.getLogger("app.main")


def create_app(settings: Settings | None = None, adapters: Adapters | None = None) -> FastAPI:
    settings = settings or load_settings()
    # Fail before binding a port if production still carries development secrets.
    settings.validate_production_secrets()
    # The engine exists before the adapters so the SQLite budget ledger can share it.
    engine, sessionmaker = create_engine_and_sessionmaker(settings)
    adapters = adapters or build_production_adapters(settings, sessionmaker)
    configure_logging(settings.log_level)
    # No-op unless SENTRY_DSN is set; failures to import/init never block startup.
    init_sentry(environment=settings.env)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_directories()
        await init_db(engine)
        # Managers are process-wide singletons. Starting them here (not lazily on the
        # first request) means a restart recovers interrupted Downloads/Analyses and
        # releases their Quota before any traffic arrives.
        download_manager = DownloadManager(
            sessionmaker=sessionmaker, adapters=adapters, settings=settings
        )
        analysis_manager = AnalysisManager(
            sessionmaker=sessionmaker, adapters=adapters, settings=settings
        )
        app.state.download_manager = download_manager
        app.state.analysis_manager = analysis_manager
        await download_manager.start()
        await analysis_manager.start()
        logger.info("app_started", extra={"event": "app_started", "env": settings.env})
        try:
            yield
        finally:
            await analysis_manager.stop()
            await download_manager.stop()
            await engine.dispose()
            logger.info("app_stopped", extra={"event": "app_stopped"})

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.adapters = adapters
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )

    register_exception_handlers(app)
    # Added last so it is the outermost user middleware and sees every response.
    app.add_middleware(RequestContextMiddleware)

    api_router = APIRouter(prefix="/api")
    api_router.include_router(catalog_router)
    api_router.include_router(identity_router)
    api_router.include_router(media_router)
    api_router.include_router(analysis_router)
    api_router.include_router(billing_router)
    app.include_router(api_router)
    app.include_router(ops_router)  # /health lives outside /api

    return app


app = create_app()
