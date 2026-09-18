# GridWise Dockerfile
# A production-quality image for the LLM-Assisted Smart Campus Energy
# Optimization API.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# system dependencies
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install dependencies in their own layer for cache reuse
COPY pyproject.toml ./
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# copy the application source
COPY app ./app
COPY scripts ./scripts
COPY data ./data
COPY README.md ./

# run as a non-root user
RUN useradd --create-home --shell /bin/bash gridwise
RUN chown -R gridwise:gridwise /app
USER gridwise

ENV APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    APP_LOG_LEVEL=info \
    APP_ENABLE_CACHE=true \
    PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
