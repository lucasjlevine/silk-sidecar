# silk-sidecar

Durable **localhost backends** on [UVM Silk](https://www.uvm.edu/it/silk), wired to real **Silk Unit** frontends.

Silk’s Unit process manager is great for Node/static apps, but long-lived custom backends (FastAPI, Flask, etc.) die when your SSH session ends — unless they run under `systemd --user` with **linger** enabled. This CLI packages that pattern end-to-end.

```
Browser → https://{NETID}.w3.uvm.edu/...
                → Silk Unit [Next.js / Node]
Browser → https://{NETID}.w3.uvm.edu/api/...
                → Next rewrites/proxy → 127.0.0.1:{PORT}
                                        ↑
                              systemd --user + linger
```

## Install (on Silk)

```bash
git clone https://github.com/lucasjlevine/silk-sidecar.git ~/src/silk-sidecar
cd ~/src/silk-sidecar
chmod +x install.sh
./install.sh
export PATH="$HOME/bin:$PATH"   # add to ~/.bashrc if needed

loginctl enable-linger "$USER"
loginctl show-user "$USER" -p Linger   # expect Linger=yes

silk-sidecar --help
```

No venv required for the CLI — Python 3 stdlib only.

## Try the hello example first (plain Node + FastAPI)

Minimal demo under [`examples/hello/`](examples/hello/) — good for proving linger + Unit before you wire Next:

```bash
cd examples/hello
./setup.sh
./run-local.sh          # laptop: http://127.0.0.1:3000/
```

On Silk:

```bash
cd examples/hello
./setup.sh
silk-sidecar linger enable
silk-sidecar deploy --config ./silk-sidecar.json
silk-sidecar doctor --config ./silk-sidecar.json
```

---

## New project workflow: Next.js + FastAPI

### 1. Scaffold under `~/www-root`

```bash
NETID="$(whoami)"
APP=myapp
PORT=8000

mkdir -p ~/www-root/$APP/{backend,frontend,deploy}
cd ~/www-root/$APP

python3 -m venv ~/venvs/$APP
~/venvs/$APP/bin/pip install fastapi 'uvicorn[standard]'
```

**FastAPI** (`backend/main.py`): expose at least `/api/health`, plus your routes under `/api/...`. Always bind `127.0.0.1` and use `--proxy-headers`.

**Next.js** (`frontend/`):

- Use App Router (or Pages) with `output: 'standalone'` in `next.config`
- Same-origin API from the browser: `NEXT_PUBLIC_API_URL=/api`
- Proxy `/api` to the sidecar at build/runtime:

```js
// next.config.js / next.config.mjs
async rewrites() {
  const upstream = process.env.API_UPSTREAM || 'http://127.0.0.1:8000';
  return [{
    source: '/api/:path*',
    destination: `${upstream}/api/:path*`,
  }];
},
```

Or generate a snippet later:

```bash
silk-sidecar frontend rewrite-snippet --config ./silk-sidecar.json
```

**Build script** (`deploy/build-web.sh`): assemble Next’s standalone output into something Unit can run, e.g. `deploy/dist/web/server.js`, and ensure **`deploy/dist/web/public/` exists** (Silk requires `document-root` on disk even if empty).

### 2. Declare the sidecar

```bash
cd ~/www-root/$APP
silk-sidecar init --name ${APP}-api --port $PORT --netid "$NETID"
```

Edit `silk-sidecar.json` (example shape):

```json
{
  "name": "myapp-api",
  "netid": "YOUR_NETID",
  "host": "YOUR_NETID.w3.uvm.edu",
  "site_root": "~/www-root",
  "backend": {
    "port": 8000,
    "workdir": "~/www-root/myapp/backend",
    "exec": "~/venvs/myapp/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --proxy-headers",
    "health_path": "/api/health",
    "environment": {
      "CORS_ORIGINS": "https://YOUR_NETID.w3.uvm.edu"
    }
  },
  "frontend": {
    "type": "nodejs",
    "app_name": "web",
    "root": "myapp/deploy/dist/web",
    "uri": "/*",
    "startup_script": "server.js",
    "node_version": "22",
    "document_root": "public",
    "proxy_prefix": "/api",
    "project_root": "~/www-root/myapp",
    "build_cmd": "./deploy/build-web.sh",
    "environment": {
      "API_UPSTREAM": "http://127.0.0.1:8000"
    }
  }
}
```

### 3. Deploy

```bash
cd ~/www-root/$APP
silk-sidecar linger enable
silk-sidecar deploy --config ./silk-sidecar.json
silk-sidecar doctor --config ./silk-sidecar.json
```

This enables linger → writes/starts the systemd user unit → health-checks → merges `~/www-root/.silk.ini` → ensures `public/` → kills stale Unit Node workers → `silk site … update` + `silk app HOST/* load`.

Open: `https://{NETID}.w3.uvm.edu/`

### 4. Logout test (required)

```bash
curl -fsS http://127.0.0.1:8000/api/health
# exit SSH completely, wait ~30s, reconnect
curl -fsS http://127.0.0.1:8000/api/health
systemctl --user status myapp-api
```

If step two fails, linger is off: `loginctl enable-linger "$USER"`.

### Day-to-day

| Change | Command |
|--------|---------|
| Backend code | `silk-sidecar restart --config ./silk-sidecar.json` |
| Frontend code | rebuild (`build_cmd`) then `silk-sidecar frontend load --config ./silk-sidecar.json` |
| Full redeploy | `silk-sidecar deploy --config ./silk-sidecar.json` |
| Weird / old UI | `silk-sidecar frontend kill-stale --broad --config ./silk-sidecar.json` then `frontend load` |
| Logs | `silk-sidecar logs -f --config ./silk-sidecar.json` |
| Health | `silk-sidecar doctor --config ./silk-sidecar.json` |

### Silk gotchas checklist

1. **Linger** — or the API dies when SSH ends  
2. **Bind `127.0.0.1` only** — never `0.0.0.0`  
3. **Next proxies `/api`** — Unit does not reverse-proxy to localhost for you  
4. **`silk app HOST/* load`** — not bare `HOST` (uri is `/*`)  
5. **`document-root` (`public/`) must exist** under the app root  
6. **Kill stale Node workers** when Unit keeps serving an old build  

More operational detail: [`AGENTS.md`](AGENTS.md).

---

## Config: `silk-sidecar.json`

| Field | Meaning |
|-------|---------|
| `name` | systemd user unit basename (`name.service`) |
| `netid` / `host` | Silk account / public hostname |
| `site_root` | Directory that holds `.silk.ini` (usually `~/www-root`) |
| `backend.port` | Localhost port (**always** `127.0.0.1`) |
| `backend.workdir` | `WorkingDirectory=` |
| `backend.exec` | Absolute `ExecStart=` command |
| `backend.health_path` | Probed after `up` |
| `backend.environment` | `Environment=` keys |
| `frontend.*` | Node Unit app stanza + proxy/build helpers |
| `frontend.environment` | Extra `env.KEY =` lines in `.silk.ini` (e.g. `API_UPSTREAM`) |

`backend.exec` must not bind `0.0.0.0` — the CLI rejects it.

## Commands

| Command | Purpose |
|---------|---------|
| `init` | Scaffold `silk-sidecar.json` (+ rewrite stub) |
| `register` / `unregister` / `list` | Track apps in `~/.config/silk-sidecar/apps.json` |
| `linger show\|enable` | Inspect / enable user lingering |
| `up` | Linger + install unit + enable/start + health probe |
| `down` / `restart` / `status` / `logs` | Lifecycle wrappers |
| `doctor` | Linger, unit, port, health, `.silk.ini`, stale Node, `silk` CLI |
| `frontend write-ini` | Merge-aware `.silk.ini` writer (+ ensure document-root) |
| `frontend rewrite-snippet` | Next.js rewrite helper for `/api` → localhost |
| `frontend kill-stale` | Kill leftover Unit Node workers (`--broad`, `--dry-run`) |
| `frontend load` | Kill stale workers, then `silk site` + `silk app HOST/* load` |
| `deploy` | Optional build + `up` + write-ini + load (kills stale by default) |

## Frontend proxy contract

Silk Unit does **not** reverse-proxy to your localhost backend by itself. Your Node/Next app must forward the API prefix:

```js
{
  source: '/api/:path*',
  destination: 'http://127.0.0.1:8000/api/:path*',
}
```

Browser calls stay same-origin (`https://YOU.w3.uvm.edu/api/...`); only the Node process talks to `127.0.0.1`.

## Why linger matters

`systemd --user` starts when you log in and, by default, stops when the last session ends. `loginctl enable-linger` keeps your user manager (and thus `myapp-api`) running after SSH logout. Without it, every backend dies when you disconnect.

## License

MIT
