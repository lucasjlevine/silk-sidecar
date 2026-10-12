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

# Silk requires document-root under the app root (relative to frontend.root).
# With document-root = public → …/dist/web/public must exist.
if [[ -d "$ROOT/frontend/public" ]]; then
  cp -R "$ROOT/frontend/public" "$OUT/public"
else
  mkdir -p "$OUT/public"
fi
: >"$OUT/public/.keep"

echo "Built $OUT (with public/)"
