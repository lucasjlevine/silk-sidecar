# silk-sidecar

Durable **localhost backends** on [UVM Silk](https://www.uvm.edu/it/silk), wired to real **Silk Unit** frontends.

Silk’s Unit process manager is great for Node/static apps, but long-lived custom backends (FastAPI, Flask, etc.) die when your SSH session ends — unless they run under `systemd --user` with **linger** enabled. This CLI packages that pattern end-to-end.

```
Browser → https://YOU.w3.uvm.edu/...
                → Silk Unit [Node] → Next (or other) frontend
Browser → https://YOU.w3.uvm.edu/api/...
                → Unit [Node] rewrite/proxy → 127.0.0.1:PORT
                                              ↑
                                    systemd --user + linger
```

## Install (on Silk)

```bash
git clone <this-repo> ~/src/silk-sidecar
cd ~/src/silk-sidecar
chmod +x install.sh
./install.sh
export PATH="$HOME/bin:$PATH"   # add to ~/.bashrc if needed
silk-sidecar --help
```

No venv required for the CLI — Python 3 stdlib only.

## Try the hello example (Node + FastAPI)

Minimal demo app under [`examples/hello/`](examples/hello/):

```bash
cd examples/hello
./setup.sh
./run-local.sh          # laptop: open http://127.0.0.1:3000/
```

On Silk (after `./install.sh`):

```bash
cd examples/hello
./setup.sh
silk-sidecar linger enable
silk-sidecar deploy --config ./silk-sidecar.json
silk-sidecar doctor --config ./silk-sidecar.json
```

## Quickstart (your own app)

```bash
cd ~/www-root/myapp
silk-sidecar init --name myapp-api --port 8000
# edit silk-sidecar.json: workdir, exec, frontend.root, build_cmd, …

silk-sidecar linger enable          # once per account
silk-sidecar deploy                 # up + write-ini + silk app load
silk-sidecar doctor
```

**Logout test:** disconnect SSH, wait ~30s, reconnect:

```bash
systemctl --user status myapp-api
curl -fsS http://127.0.0.1:8000/…health…
```

If that fails, linger is off: `loginctl enable-linger "$USER"`.

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
| `doctor` | Linger, unit, port, health, `.silk.ini`, `silk` CLI |
| `frontend write-ini` | Merge-aware `.silk.ini` writer |
| `frontend rewrite-snippet` | Next.js rewrite helper for `/api` → localhost |
| `frontend load` | `silk site HOST update` + `silk app HOST/* load` |
| `deploy` | Optional build + `up` + write-ini + load |

## Frontend proxy contract

Silk Unit does **not** reverse-proxy to your localhost backend by itself. Your Node app (typically Next.js rewrites) must forward the API prefix:

```js
// from: silk-sidecar frontend rewrite-snippet
{
  source: '/api/:path*',
  destination: 'http://127.0.0.1:8000/api/:path*',
}
```

Browser calls stay same-origin (`https://YOU.w3.uvm.edu/api/...`); only the Node process talks to `127.0.0.1`.

## Day-to-day

```bash
# Backend code changed
systemctl --user restart myapp-api
# or
silk-sidecar restart

# Frontend rebuilt
silk-sidecar frontend load

# Logs
silk-sidecar logs -f
```

## Why linger matters

`systemd --user` starts when you log in and, by default, stops when the last session ends. `loginctl enable-linger` keeps your user manager (and thus `silk-hello-api` / `myapp-api`) running after SSH logout. Without it, every backend dies when you disconnect.

## License

MIT
