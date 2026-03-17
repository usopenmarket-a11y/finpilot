import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import analytics, credentials, debts, health, recommendations, scrape, sync, utils

logger = logging.getLogger(__name__)

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
    "Accept-Language",
    "Content-Language",
    "Origin",
    "X-CSRF-Token",
    "X-User-Id",
]

if settings.app_env == "production" and ("*" in settings.cors_origins or not settings.cors_origins):
    raise RuntimeError(
        "CORS misconfiguration: cors_origins must not contain '*' or be empty in "
        "production.  Set CORS_ORIGINS to the explicit Vercel deployment URL(s)."
    )


async def _ensure_playwright_browsers() -> None:
    """Install Playwright Chromium browser binary and diagnose system library status."""
    import glob as _glob
    import os as _os

    # Install browser binary (--with-deps fails on Render due to no sudo)
    try:
        proc = await asyncio.create_subprocess_exec(
            "playwright", "install", "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        rc = proc.returncode
        print(f"[playwright-install] exit={rc} stderr={stderr.decode()[:300]}", flush=True)
    except Exception as exc:
        print(f"[playwright-install] exception: {exc}", flush=True)

    # Find the installed binary
    patterns = [
        "/opt/render/.cache/ms-playwright/chromium*/chrome-headless-shell-linux64/chrome-headless-shell",
        "/opt/render/.cache/ms-playwright/chromium*/chrome-linux64/chrome",
    ]
    binary = None
    for pat in patterns:
        matches = _glob.glob(pat)
        if matches:
            binary = matches[0]
            break

    if not binary or not _os.path.isfile(binary):
        print("[playwright-diag] Chromium binary NOT FOUND", flush=True)
        return

    print(f"[playwright-diag] binary={binary}", flush=True)

    # ldd to find missing shared libraries
    try:
        ldd_proc = await asyncio.create_subprocess_exec(
            "ldd", binary,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        ldd_out, _ = await ldd_proc.communicate()
        missing = [l for l in ldd_out.decode().splitlines() if "not found" in l]
        if missing:
            print(f"[playwright-diag] MISSING LIBS: {missing}", flush=True)
        else:
            print("[playwright-diag] All libraries present", flush=True)
    except Exception as exc:
        print(f"[playwright-diag] ldd failed: {exc}", flush=True)

    # Try actually launching the binary and capture exit code / stderr
    try:
        run_proc = await asyncio.create_subprocess_exec(
            binary, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        run_out, run_err = await asyncio.wait_for(run_proc.communicate(), timeout=10)
        print(
            f"[playwright-diag] binary --version exit={run_proc.returncode} "
            f"stdout={run_out.decode()[:200]} stderr={run_err.decode()[:200]}",
            flush=True,
        )
    except asyncio.TimeoutError:
        print("[playwright-diag] binary --version timed out (likely missing lib)", flush=True)
    except Exception as exc:
        print(f"[playwright-diag] binary --version failed: {exc}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Run browser install in the background so the server starts immediately.
    # Render free-tier has a port-binding timeout; blocking on the ~80s download
    # causes a failed deploy even though the install would have succeeded.
    asyncio.create_task(_ensure_playwright_browsers())
    yield


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
    app.include_router(credentials.router, prefix="/api/v1")
    app.include_router(analytics.router, prefix="/api/v1")
    app.include_router(debts.router, prefix="/api/v1")
    app.include_router(recommendations.router, prefix="/api/v1")
    app.include_router(utils.router, prefix="/api/v1")
    app.include_router(sync.router, prefix="/api/v1")

    return app


app = create_app()
