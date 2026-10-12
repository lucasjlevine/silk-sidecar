#!/usr/bin/env bash
# Assemble frontend into dist/web for Silk Unit (startup-script = server.js).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="$ROOT/dist/web"

rm -rf "$OUT"
mkdir -p "$OUT"
cp "$ROOT/frontend/server.js" "$OUT/server.js"
cp "$ROOT/frontend/package.json" "$OUT/package.json"
chmod u+x "$OUT/server.js"

# Ensure public docroot exists for .silk.ini document-root
mkdir -p "$ROOT/dist/public"

echo "Built $OUT"
