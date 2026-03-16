from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import analytics, debts, health, scrape

# ---------------------------------------------------------------------------
# CORS origin safety guard
# ---------------------------------------------------------------------------
# In production, a wildcard origin combined with allow_credentials=True is a
# critical misconfiguration (browsers will refuse such responses anyway, but
# it signals a broken deployment).  Fail loudly at startup rather than
# silently serving broken CORS headers.
_ALLOWED_CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_ALLOWED_CORS_HEADERS = [
    "Authorization",
    "Content-Type",
    "X-Requested-With",
    "Accept",
    "Origin",
    "X-CSRF-Token",
]

if settings.app_env == "production" and (
    "*" in settings.cors_origins or not settings.cors_origins
):
    raise RuntimeError(
        "CORS misconfiguration: cors_origins must not contain '*' or be empty in "
        "production.  Set CORS_ORIGINS to the explicit Vercel deployment URL(s)."
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: initialise connections, load models, etc.
    yield
    # Shutdown: close connections, flush buffers, etc.


def create_app() -> FastAPI:
    app = FastAPI(
        title="FinPilot API",
        version="0.1.0",
        description="AI-powered financial assistant backend",
        lifespan=lifespan,
        # Disable the auto-generated /docs and /redoc in production to avoid
        # leaking internal API shape to unauthenticated users.
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None if settings.app_env == "production" else "/redoc",
    )

    # Explicit method and header allow-lists.  Wildcards on either would
    # allow non-standard verbs (TRACE, CONNECT) and arbitrary request headers
    # with no benefit to this application.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=_ALLOWED_CORS_METHODS,
        allow_headers=_ALLOWED_CORS_HEADERS,
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(scrape.router, prefix="/api/v1")
    app.include_router(analytics.router, prefix="/api/v1")
    app.include_router(debts.router, prefix="/api/v1")

    return app


app = create_app()
