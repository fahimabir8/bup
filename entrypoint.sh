#!/bin/sh
# GridWise container entrypoint.
#
# Runs the FastAPI backend (uvicorn) on $APP_PORT and the static
# frontend (Python http.server) on $UI_PORT inside the same container.
#
# Both processes share the tini PID-1 so they receive SIGTERM properly
# and shut down together on `docker compose down`.
#
# POSIX-compatible (uses /bin/sh, not bash) so it works on any base
# image without extra packages.

set -eu

APP_PORT="${APP_PORT:-8000}"
UI_PORT="${UI_PORT:-8001}"
APP_HOST="${APP_HOST:-0.0.0.0}"

echo "[entrypoint] starting backend on ${APP_HOST}:${APP_PORT}"

# Launch uvicorn in the background; logs flow to stdout/stderr.
LLM_PROVIDER="${LLM_PROVIDER:-mock}" \
  python -m uvicorn app.main:app \
    --host "${APP_HOST}" \
    --port "${APP_PORT}" &
APP_PID=$!

echo "[entrypoint] starting static frontend on 0.0.0.0:${UI_PORT}"

# Hand the static server the project root so /data/example_request.json
# is reachable from the UI (matches the local dev workflow).
python -m http.server "${UI_PORT}" --bind 0.0.0.0 &
UI_PID=$!

# Tear everything down on SIGTERM / SIGINT.
shutdown() {
  echo "[entrypoint] received signal, shutting down"
  kill -TERM "${UI_PID}" 2>/dev/null || true
  kill -TERM "${APP_PID}" 2>/dev/null || true
  wait 2>/dev/null || true
  exit 0
}
trap shutdown TERM INT

# Poll for either child exiting; the trap then takes over.
while :; do
  if ! kill -0 "${APP_PID}" 2>/dev/null; then
    echo "[entrypoint] backend exited, tearing down"
    shutdown
  fi
  if ! kill -0 "${UI_PID}" 2>/dev/null; then
    echo "[entrypoint] frontend exited, tearing down"
    shutdown
  fi
  sleep 1
done
