#!/usr/bin/env bash
# Install silk-sidecar onto PATH (symlink into ~/bin).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${SILK_SIDECAR_BIN:-$HOME/bin}"
TARGET="$BIN_DIR/silk-sidecar"
WRAPPER="$ROOT/silk-sidecar"

mkdir -p "$BIN_DIR"

cat >"$WRAPPER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
ROOT="${ROOT}"
export PYTHONPATH="\${ROOT}\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m silk_sidecar "\$@"
EOF
chmod +x "$WRAPPER"

ln -sfn "$WRAPPER" "$TARGET"
echo "Installed: $TARGET -> $WRAPPER"
echo
echo "Ensure ~/bin is on PATH, e.g.:"
echo '  export PATH="$HOME/bin:$PATH"'
echo
export PATH="$BIN_DIR:$PATH"
"$TARGET" --help | head -n 20
