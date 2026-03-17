FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Copy project metadata
COPY pyproject.toml .

# Install dependencies (production only)
RUN uv sync --no-dev

# Production stage
FROM python:3.12-slim

WORKDIR /app

# Install system deps: curl for health checks + Chromium deps for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxshmfence1 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY . .

# Set PATH to use venv binaries
ENV PATH="/app/.venv/bin:$PATH"

# Install Playwright's Chromium browser
RUN playwright install chromium

# Health check for container orchestration
# Checks /api/v1/health endpoint (as defined in app/routers/health.py)
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

# Production server (no auto-reload)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
