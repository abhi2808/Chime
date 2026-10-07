"""Chime API.

Mounted under two prefixes: ``/api`` for the app's own surface and ``/auth`` for the
OAuth round trip, matching SPEC section 7.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, body, dev, health, library, me, sessions
from app.core.config import settings
from app.core.logging import configure_logging
from app.services import scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    sqlite_path = settings.sqlite_path
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(
        "chime backend ready",
        extra={
            "frontend_origin": settings.frontend_origin,
            "database": "sqlite" if sqlite_path else "external",
            "allowlist": len(settings.allowed_spotify_user_id_list) or "open-until-first-login",
        },
    )
    # The live loop needs the running event loop, so it starts here rather than at import.
    # Off in tests and switchable in production; see app.services.scheduler.
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="Chime", version="0.1.0", lifespan=lifespan)

# The frontend is proxied through Vite, so requests are same-origin in dev. CORS is here
# for the day the frontend is served from somewhere else.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(me.router, prefix="/api")
app.include_router(library.router, prefix="/api")
app.include_router(body.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
if settings.enable_dev_api:
    app.include_router(dev.router, prefix="/api")
app.include_router(auth.router)
