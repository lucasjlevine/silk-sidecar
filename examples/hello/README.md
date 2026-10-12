# hello — minimal Node + FastAPI example

Tiny full-stack demo of the silk-sidecar pattern:

- **FastAPI** on `127.0.0.1:8765` — `/api/health`, `/api/hello`
- **Node** — one-page UI + proxy `/api/*` → that backend

No Next.js, no database.

## Laptop

```bash
cd examples/hello
./setup.sh
./run-local.sh
```

Open [http://127.0.0.1:3000/](http://127.0.0.1:3000/) → **Call /api/hello**.

## Silk

```bash
# once: install CLI from repo root
../../install.sh
export PATH="$HOME/bin:$PATH"

cd examples/hello
./setup.sh
silk-sidecar linger enable
silk-sidecar deploy --config ./silk-sidecar.json
silk-sidecar doctor --config ./silk-sidecar.json
```

Then open `https://YOUR_NETID.w3.uvm.edu/`, click the button, log out of SSH, and confirm:

```bash
curl -fsS http://127.0.0.1:8765/api/health
systemctl --user status silk-hello-api
```

`setup.sh` writes `silk-sidecar.json` (including `env.API_UPSTREAM` for the Node Unit app) and builds `dist/web`.

## Layout

```
hello/
  backend/main.py       FastAPI
  frontend/server.js    Node UI + /api proxy
  build.sh              → dist/web
  setup.sh              venv + silk-sidecar.json
  run-local.sh          laptop runner
```

| Knob | Default | Env override |
|------|---------|--------------|
| API port | `8765` | `HELLO_API_PORT` |
| Web port (local) | `3000` | `HELLO_WEB_PORT` |
| Venv | `~/venvs/silk-hello` | `HELLO_VENV` |
