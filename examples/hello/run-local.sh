#!/usr/bin/env bash
# Run the hello example on a laptop: FastAPI + Node proxy (no systemd / Silk).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${HELLO_API_PORT:-8765}"
WEB_PORT="${HELLO_WEB_PORT:-3000}"
VENV="${HELLO_VENV:-$HOME/venvs/silk-hello}"

if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  echo "==> venv missing; running setup.sh first"
  HELLO_API_PORT="$PORT" HELLO_VENV="$VENV" "$ROOT/setup.sh"
fi

"$ROOT/build.sh"

cleanup() {
  if [[ -n "${API_PID:-}" ]]; then kill "$API_PID" 2>/dev/null || true; fi
  if [[ -n "${WEB_PID:-}" ]]; then kill "$WEB_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

echo "==> FastAPI on 127.0.0.1:${PORT}"
(
  cd "$ROOT/backend"
  "$VENV/bin/uvicorn" main:app --host 127.0.0.1 --port "$PORT" --proxy-headers
) &
API_PID=$!

# Wait for health
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done
curl -fsS "http://127.0.0.1:${PORT}/api/health"
echo

echo "==> Node on 127.0.0.1:${WEB_PORT} (proxy /api → :${PORT})"
(
  cd "$ROOT/dist/web"
  API_UPSTREAM="http://127.0.0.1:${PORT}" HOSTNAME=127.0.0.1 PORT="$WEB_PORT" node server.js
) &
WEB_PID=$!

sleep 0.4
echo
echo "Open:  http://127.0.0.1:${WEB_PORT}/"
echo "API:   http://127.0.0.1:${PORT}/api/hello"
echo "Ctrl-C to stop."
wait
