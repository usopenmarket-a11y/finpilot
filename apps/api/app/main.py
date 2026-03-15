from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import health


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
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/v1")

    return app


app = create_app()
