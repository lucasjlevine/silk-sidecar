# AGENTS.md — Silk deployment knowledge for silk-sidecar

This file is for AI agents and humans working on **Silk hosting** via this repo.
It captures hard-won operational facts about UVM Silk, `systemd --user`, linger,
and Unit frontends. Keep product-specific app logic out of here.

## What Silk gives you

- Public site: `https://{NETID}.w3.uvm.edu`
- Site files typically under `~/www-root/`
- Site config: `~/www-root/.silk.ini` (Unit apps)
- CLI: `silk site {host} update`, `silk app {host} load`
- TLS terminates at Silk; your apps usually listen on loopback

Silk Unit is excellent for **Node / static** apps declared in `.silk.ini`.
It is a poor fit for long-lived custom backends (FastAPI, Flask, etc.) unless
those backends run **outside** Unit.

## The working architecture

```
Browser → https://{NETID}.w3.uvm.edu/...
              → Silk Unit [Node frontend]
Browser → https://{NETID}.w3.uvm.edu/api/...
              → Unit [Node] rewrite/proxy → 127.0.0.1:{PORT}
                                            ↑
                                  systemd --user unit
                                  + loginctl linger
```

Rules:

1. Backend binds **`127.0.0.1` only** — never `0.0.0.0`.
2. Frontend (Node) performs the **same-origin `/api` proxy** to localhost.
3. Backend lifespan is owned by **`systemd --user`**, not the SSH session.
4. **Linger must be enabled** or the backend dies when SSH disconnects.

## Critical issue: processes die after SSH logout

### Symptom

API works while you are SSH’d in. After logout (or idle disconnect),
`curl http://127.0.0.1:{PORT}/…` fails and the Unit frontend returns 502 /
upstream errors.

### Cause

On modern systemd hosts (including Silk), logging out ends the user session.
Without linger, `systemd --user` is torn down and user units / session-scoped
processes are killed (`KillUserProcesses`-style behavior).

Also fails for the same reason:

- `uvicorn … &` started in SSH
- `nohup` / background jobs still in the login session scope
- tmux/screen **without** linger / user scope (can still be killed on some hosts)

### Fix (once per account)

```bash
loginctl enable-linger "$USER"
# verify:
loginctl show-user "$USER" -p Linger
# expect: Linger=yes
```

Then run the backend as a **user unit**:

```bash
systemctl --user daemon-reload
systemctl --user enable --now myapp-api.service
systemctl --user status myapp-api.service
```

### Logout test (acceptance)

1. Confirm health while logged in: `curl -fsS http://127.0.0.1:{PORT}/api/health`
2. Exit SSH completely
3. Wait ~30s
4. SSH back in
5. Re-check health + `systemctl --user status myapp-api`

If step 5 fails, linger is off or the process was never under `systemd --user`.

## systemd --user unit requirements

Put units in `~/.config/systemd/user/{name}.service`.

Must-haves:

- `WorkingDirectory=` **absolute** path
- `ExecStart=` absolute binary path (expand `~` and venv paths before writing)
- Bind address in the command: `--host 127.0.0.1` (or equivalent)
- `Restart=on-failure` (short `RestartSec` is fine)
- `WantedBy=default.target`
- Prefer `Environment=KEY=value` lines with absolute/stable values

`ExecStart` is **argv-style, no shell**. Do not rely on shell quoting tricks;
use systemd-compatible quoting for spaces. Resolve interpreters (`python3`,
`uvicorn`) to absolute paths when possible.

After editing a unit:

```bash
systemctl --user daemon-reload
systemctl --user restart {name}
journalctl --user -u {name} -n 80 --no-pager
```

## Frontend / Unit (`.silk.ini`)

Typical Node app stanza:

```ini
[general]
document-root = public
redirect-insecure-http = true

[nodejs]
version = 22

[app: web]
type = nodejs
root = path/relative/to/www-root/dist/web
uri = /*
document-root = public
startup-script = server.js
env.NODE_ENV = production
env.HOSTNAME = 127.0.0.1
env.PORT = 3000
env.API_UPSTREAM = http://127.0.0.1:8765
```

Notes:

- `root` is relative to the site root (`~/www-root`), not the git repo, unless
  you deliberately structure it that way.
- Unit does **not** reverse-proxy to your localhost backend by itself.
- The Node process must proxy/rewrite `/api` → `http://127.0.0.1:{PORT}`.
- Pass upstream via `env.API_UPSTREAM` (or bake rewrites at build time).
- After changing `.silk.ini` or built assets:

```bash
silk site {NETID}.w3.uvm.edu update
silk app {NETID}.w3.uvm.edu/* load
```

**App locator gotcha:** `silk app HOST load` looks up `HOST/` and fails with
`No app found at HOST/` when the app’s `uri = /*`. Always pass the uri pattern:
`silk app HOST/* load` (or `HOST/myapp*` for a path-scoped app). See
[Silk Node.js docs](https://silk.uvm.edu/manual/nodejs/).

**Stale Node workers:** Unit often keeps old `node server.js` processes after
`.silk.ini` / dist changes. Symptoms: site still serves an old app, wrong
env, or 502 while a new config exists on disk. Always kill then reload:

```bash
silk-sidecar frontend kill-stale --config ./silk-sidecar.json   # or --broad
silk-sidecar frontend load --config ./silk-sidecar.json
# deploy/load do this kill step by default (--keep-stale to skip)
```

Do **not** kill the systemd backend (uvicorn); only Unit Node workers.

## Proxy / CORS / path conventions

- Prefer **same-origin** browser calls: `fetch("/api/…")` against the public host.
- Only the Node process should talk to `127.0.0.1`.
- If the backend cares about public origin (CORS, redirects, cookies), set
  something like `CORS_ORIGINS=https://{NETID}.w3.uvm.edu`.
- If the API is mounted behind a path prefix, configure the framework for
  proxy headers / root path (e.g. FastAPI `root_path`, uvicorn `--proxy-headers`).
- Next.js (and similar) can use rewrites:

```js
{
  source: "/api/:path*",
  destination: "http://127.0.0.1:8000/api/:path*",
}
```

A plain Node `http` proxy (see `examples/hello`) is enough to prove the pattern.

## silk-sidecar CLI mapping

This repo automates the above:

| Concern | Command |
|---------|---------|
| Scaffold config | `silk-sidecar init` |
| Linger | `silk-sidecar linger enable` / `doctor` |
| Unit install + start + health | `silk-sidecar up` |
| Merge `.silk.ini` | `silk-sidecar frontend write-ini` |
| Reload Unit | `silk-sidecar frontend load` |
| Build + up + ini + load | `silk-sidecar deploy` |
| Diagnose | `silk-sidecar doctor` |

Config file: `silk-sidecar.json` (JSON, stdlib-only parser).
Registry: `~/.config/silk-sidecar/apps.json`.

Guarantees enforced by the tool:

- Rejects `0.0.0.0` in `backend.exec`
- Expands `~` / env vars to absolute paths in generated units
- Health-probes after `up`; dumps `journalctl --user` on failure
- Merge-aware `.silk.ini` writer (preserves unrelated `[app: …]` stanzas)
- `frontend.environment` → `env.KEY =` lines (e.g. `API_UPSTREAM`)

## Local laptop vs Silk

| | Laptop | Silk |
|--|--------|------|
| Backend | foreground / `run-local.sh` | `systemd --user` + linger |
| Frontend | `node server.js` on `:3000` | Unit via `.silk.ini` |
| `silk` CLI | often missing (OK) | required for `frontend load` |
| Site root | can be a temp dir under the example | `~/www-root` |

`doctor` treats missing `silk` as optional off-host; linger + unit + health are
required for “ready”.

## Debugging checklist

1. `loginctl show-user "$USER" -p Linger` → must be `yes`
2. `systemctl --user status {unit}` → `active (running)`
3. `ss`/`curl` to `127.0.0.1:{PORT}` from the Silk shell
4. `journalctl --user -u {unit} -f` for crash loops / bad `WorkingDirectory`
5. Confirm Node env has the correct `API_UPSTREAM`
6. `silk app {host} load` after frontend rebuilds
7. Logout test (above) before calling it production-ready

## Anti-patterns

- Starting the API only inside an SSH session and expecting it to survive logout
- Binding the API on `0.0.0.0` on a shared host
- Assuming Unit will proxy to localhost without app-level rewrites/proxy code
- Relative paths in `ExecStart=` / `WorkingDirectory=` that break under systemd
- Editing `.silk.ini` by hand in ways that wipe unrelated apps (use merge-aware writes)
- Claiming success without the SSH logout test

## Example to prove the stack

Use [`examples/hello/`](examples/hello/): minimal FastAPI + Node proxy.

```bash
cd examples/hello
./setup.sh
./run-local.sh                 # laptop
# or on Silk:
silk-sidecar deploy --config ./silk-sidecar.json
```

That example is the canonical smoke test for this repository’s Silk knowledge.
