# GridWise Dockerfile — single-image container that serves both the
# FastAPI backend (port 8000) and the static frontend (port 8001)
# simultaneously via an entrypoint script and tini as PID 1.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# system deps: build-essential for some wheels, tini for proper
# signal handling of both processes, curl for the healthcheck
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install dependencies in their own layer for cache reuse
COPY pyproject.toml ./
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# copy the application source + frontend
COPY app ./app
COPY scripts ./scripts
COPY data ./data
COPY frontend ./frontend
COPY entrypoint.sh /entrypoint.sh
COPY README.md ./

# run as a non-root user; entrypoint must be executable by them
RUN useradd --create-home --shell /bin/bash gridwise \
    && chown -R gridwise:gridwise /app \
    && chmod 0755 /entrypoint.sh

USER gridwise

ENV APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    APP_LOG_LEVEL=info \
    APP_ENABLE_CACHE=true \
    UI_PORT=8001 \
    PYTHONPATH=/app

# backend on 8000, static frontend on 8001
EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# tini → forwards signals and reaps zombies for both child processes
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
