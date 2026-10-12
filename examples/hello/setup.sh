#!/usr/bin/env bash
# Prepare the hello example: venv + silk-sidecar.json for this checkout.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$ROOT/../.." && pwd)"
NETID="${NETID:-${USER:-$(whoami)}}"
HOST="${HOST:-${NETID}.w3.uvm.edu}"
PORT="${HELLO_API_PORT:-8765}"
VENV="${HELLO_VENV:-$HOME/venvs/silk-hello}"
SITE_ROOT="${SITE_ROOT:-$HOME/www-root}"

# If this example lives under ~/www-root/..., use that as site root automatically.
case "$ROOT" in
  "$SITE_ROOT"/*) ;;
  *)
    if [[ -d "$SITE_ROOT" ]]; then
      :
    else
      # Local laptop / non-Silk: keep site_root next to the example
      SITE_ROOT="$ROOT/site"
      mkdir -p "$SITE_ROOT/public"
    fi
    ;;
esac

echo "==> Example root: $ROOT"
echo "==> Site root:    $SITE_ROOT"
echo "==> Venv:         $VENV"
echo "==> API port:     $PORT"

mkdir -p "$(dirname "$VENV")" "$SITE_ROOT/public"
if [[ ! -d "$VENV" ]]; then
  echo "==> Creating venv"
  python3 -m venv "$VENV"
fi
echo "==> pip install backend deps"
"$VENV/bin/pip" install -U pip
"$VENV/bin/pip" install -r "$ROOT/backend/requirements.txt"

# Relative frontend root from site_root → example dist
# Prefer a stable relative path when example is inside site_root; else absolute-ish via symlink helper.
REL_FRONT=""
if [[ "$ROOT" == "$SITE_ROOT"* ]]; then
  REL_FRONT="${ROOT#"$SITE_ROOT"/}/dist/web"
else
  # Point Silk at a copy/symlink under site_root so Unit can find it
  LINK="$SITE_ROOT/silk-hello"
  rm -rf "$LINK"
  ln -sfn "$ROOT" "$LINK"
  REL_FRONT="silk-hello/dist/web"
  echo "==> Linked $LINK → $ROOT"
fi

"$ROOT/build.sh"

# Write silk-sidecar.json with absolute expanded paths for systemd
python3 - <<PY
import json
from pathlib import Path

root = Path("$ROOT").resolve()
venv = Path("$VENV").resolve()
site = Path("$SITE_ROOT").resolve()
port = int("$PORT")
netid = "$NETID"
host = "$HOST"
rel_front = "$REL_FRONT"

cfg = {
    "name": "silk-hello-api",
    "netid": netid,
    "host": host,
    "site_root": str(site),
    "backend": {
        "port": port,
        "workdir": str(root / "backend"),
        "exec": f"{venv}/bin/uvicorn main:app --host 127.0.0.1 --port {port} --proxy-headers",
        "health_path": "/api/health",
        "unit_description": f"silk-sidecar hello FastAPI (:{port})",
        "environment": {
            "API_ROOT_PATH": "",
            "CORS_ORIGINS": f"https://{host},http://127.0.0.1:3000,http://localhost:3000",
        },
    },
    "frontend": {
        "type": "nodejs",
        "app_name": "hello",
        "root": rel_front,
        "uri": "/*",
        "startup_script": "server.js",
        "node_version": "22",
        "document_root": "public",
        "proxy_prefix": "/api",
        "project_root": str(root),
        "build_cmd": "./build.sh",
        "max_request_length": 10485760,
        "request_timeout": 60,
        "environment": {
            "API_UPSTREAM": f"http://127.0.0.1:{port}",
        },
    },
}
path = root / "silk-sidecar.json"
path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
print(f"==> Wrote {path}")
PY

cat >"$ROOT/dist/web/.env.example" <<EOF
API_UPSTREAM=http://127.0.0.1:${PORT}
PORT=3000
HOSTNAME=127.0.0.1
EOF

echo
echo "Setup complete."
echo
echo "Local laptop:"
echo "  $ROOT/run-local.sh"
echo
echo "On Silk:"
echo "  export PATH=\"\$HOME/bin:\$PATH\""
echo "  silk-sidecar linger enable"
echo "  silk-sidecar deploy --config $ROOT/silk-sidecar.json"
echo "  silk-sidecar doctor --config $ROOT/silk-sidecar.json"
