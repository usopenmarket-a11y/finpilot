FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Copy project metadata
COPY pyproject.toml uv.lock ./

# Install dependencies (production only)
RUN uv sync --locked --no-dev

# Production stage
FROM python:3.12-slim

WORKDIR /app

# curl is used by the container health check. Playwright installs the
# distribution packages needed by its pinned Chromium build below.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY . .

# Set PATH to use venv binaries
ENV PATH="/app/.venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Other bank scrapers use Playwright; BDC uses Patchright's own Chromium.
RUN playwright install --with-deps chromium \
    && patchright install chromium

# Health check for container orchestration
# Checks /api/v1/health endpoint (as defined in app/routers/health.py)
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

# Production server (no auto-reload)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
