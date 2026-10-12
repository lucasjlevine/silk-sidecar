"""silk-sidecar CLI entrypoint."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from silk_sidecar import __version__
from silk_sidecar.config import (
    ConfigError,
    default_init_config,
    find_config,
    load_config,
    write_init_config,
)
from silk_sidecar.doctor import format_doctor_report, run_doctor
from silk_sidecar.frontend_ini import write_ini
from silk_sidecar.health import probe_url
from silk_sidecar.linger import enable_linger, show_linger
from silk_sidecar.next_rewrite import render_snippet, write_snippet
from silk_sidecar.registry import load_registry, register_app, unregister_app
from silk_sidecar.silk_cmd import app_target, frontend_load, silk_available
from silk_sidecar.systemd_unit import (
    copy_unit_to_project,
    enable_and_start,
    install_unit,
    recent_logs,
    stop_unit,
    systemctl_user,
    unit_status_text,
)


def _die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _resolve_config(path: str | None) -> Path:
    if path:
        p = Path(path)
        if not p.is_file():
            _die(f"config not found: {p}")
        return p.resolve()
    found = find_config()
    if not found:
        _die(
            "no silk-sidecar.json found in this directory or parents; "
            "pass --config or run: silk-sidecar init"
        )
    return found


def _load(path: str | None):
    try:
        return load_config(_resolve_config(path))
    except ConfigError as exc:
        _die(str(exc))


def cmd_init(args: argparse.Namespace) -> int:
    dest = Path(args.path or "silk-sidecar.json").resolve()
    if dest.exists() and not args.force:
        _die(f"{dest} already exists (use --force to overwrite)")
    netid = args.netid or os.environ.get("USER") or os.environ.get("LOGNAME") or "NETID"
    name = args.name or dest.parent.name or "myapp"
    data = default_init_config(
        name=name,
        netid=netid,
        port=args.port,
        with_frontend=not args.backend_only,
    )
    write_init_config(dest, data)
    print(f"Wrote {dest}")
    if not args.backend_only:
        snippet_path = dest.parent / "silk-sidecar.rewrites.js"
        # Minimal stub until user fills real paths — still useful
        cfg = load_config(dest)
        if cfg.frontend:
            write_snippet(cfg, snippet_path)
            print(f"Wrote {snippet_path}")
    print("Edit the config, then: silk-sidecar register && silk-sidecar up")
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    entry = register_app(cfg.name, cfg.config_path, cfg.host, cfg.backend.port)
    print(f"Registered {entry.name} → {entry.config_path}")
    return 0


def cmd_unregister(args: argparse.Namespace) -> int:
    name = args.name
    if not name:
        cfg = _load(args.config)
        name = cfg.name
    if unregister_app(name):
        print(f"Unregistered {name}")
        return 0
    _die(f"not in registry: {name}")


def cmd_linger(args: argparse.Namespace) -> int:
    user = args.user
    if args.action == "show":
        status = show_linger(user)
        print(f"user={status.user} linger={'yes' if status.enabled else 'no'} ({status.raw})")
        return 0 if status.enabled else 1
    if args.action == "enable":
        status = enable_linger(user)
        print(f"Linger enabled for {status.user}")
        return 0
    _die(f"unknown linger action: {args.action}")


def cmd_up(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    print(f"==> Config: {cfg.config_path}")
    print(f"==> Unit:   {cfg.unit_name}")
    print(f"==> Bind:   127.0.0.1:{cfg.backend.port}")

    if not args.skip_linger:
        try:
            status = show_linger(cfg.netid)
            if not status.enabled:
                print(f"==> Enabling linger for {cfg.netid}")
                enable_linger(cfg.netid)
            else:
                print(f"==> Linger already on for {cfg.netid}")
        except Exception as exc:  # noqa: BLE001
            print(f"warning: linger check failed: {exc}", file=sys.stderr)
            print(
                f"  Run manually: loginctl enable-linger {cfg.netid}",
                file=sys.stderr,
            )

    if not cfg.backend.workdir.is_dir():
        _die(f"backend.workdir does not exist: {cfg.backend.workdir}")

    path = install_unit(cfg)
    print(f"==> Wrote {path}")
    if args.copy_unit:
        copied = copy_unit_to_project(cfg)
        if copied:
            print(f"==> Copied unit → {copied}")

    register_app(cfg.name, cfg.config_path, cfg.host, cfg.backend.port)

    try:
        enable_and_start(cfg)
    except FileNotFoundError:
        _die("systemctl not found (are you on Silk/Linux?)")
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc.stdout or str(exc), file=sys.stderr)
        print(recent_logs(cfg), file=sys.stderr)
        _die("systemctl --user enable/restart failed")

    print("==> Probe health")
    probe = probe_url(cfg.backend.health_url, retries=args.retries)
    if probe.ok:
        print(f"OK {probe.url} ({probe.message})")
        print(f"\nDirect: curl -fsS {cfg.backend.health_url}")
        print(f"Status: systemctl --user status {cfg.unit_name}")
        return 0

    print(f"FAIL {probe.url}: {probe.message}", file=sys.stderr)
    print("==> recent logs:", file=sys.stderr)
    print(recent_logs(cfg), file=sys.stderr)
    print(
        f"\nIf the unit dies after SSH logout:\n"
        f"  loginctl enable-linger {cfg.netid}\n"
        f"  systemctl --user restart {cfg.unit_name}",
        file=sys.stderr,
    )
    return 1


def cmd_down(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    stop_unit(cfg, disable=args.disable)
    print(f"Stopped {cfg.unit_name}" + (" (disabled)" if args.disable else ""))
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    proc = systemctl_user("restart", cfg.unit_name, check=False)
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout, file=sys.stderr)
        return proc.returncode
    print(f"Restarted {cfg.unit_name}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    text = unit_status_text(cfg)
    print(text)
    return 0 if "Active: active" in text or "active (running)" in text else 1


def cmd_logs(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    if args.follow:
        return subprocess.call(
            ["journalctl", "--user", "-u", cfg.unit_name, "-f", "-n", str(args.lines)]
        )
    print(recent_logs(cfg, lines=args.lines))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    entries = load_registry()
    if not entries:
        print("No registered apps. Run: silk-sidecar register")
        return 0
    for name, entry in sorted(entries.items()):
        state = "?"
        try:
            proc = systemctl_user("is-active", f"{name}.service", check=False)
            state = proc.stdout.strip() or "?"
        except FileNotFoundError:
            state = "n/a"
        print(f"{name:24} :{entry.port:<6} {state:10} {entry.config_path}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    checks = run_doctor(cfg)
    print(format_doctor_report(cfg, checks), end="")
    from silk_sidecar.doctor import is_ready

    return 0 if is_ready(checks) else 1


def cmd_frontend_write_ini(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    if not cfg.frontend:
        _die("config has no frontend section")
    path = write_ini(cfg, merge=not args.replace)
    print(f"Wrote {path}" + (" (replace)" if args.replace else " (merge)"))
    return 0


def cmd_frontend_rewrite_snippet(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    if not cfg.frontend:
        _die("config has no frontend section")
    text = render_snippet(cfg)
    if args.output:
        dest = Path(args.output)
        write_snippet(cfg, dest)
        print(f"Wrote {dest.resolve()}")
    else:
        print(text, end="" if text.endswith("\n") else "\n")
    return 0


def cmd_frontend_load(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    if not silk_available():
        _die(
            "silk CLI not found on PATH. Backend commands still work; "
            "frontend load must run on a Silk host."
        )
    uri = cfg.frontend.uri if cfg.frontend else "/*"
    target = app_target(cfg.host, uri)
    print(f"==> silk app {target} load")
    results = frontend_load(cfg.host, uri)
    code = 0
    for r in results:
        label = " ".join(r.command)
        if r.ok:
            print(f"OK  {label}")
            if r.stdout.strip():
                print(r.stdout.rstrip())
        else:
            code = 1
            print(f"FAIL {label}", file=sys.stderr)
            print((r.stderr or r.stdout).rstrip(), file=sys.stderr)
            if "No app found" in (r.stderr or r.stdout or "") and not target.endswith("*"):
                print(
                    f"hint: Silk addresses apps as host+uri; try: silk app {cfg.host}/* load",
                    file=sys.stderr,
                )
    return code


def cmd_deploy(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    # Optional build
    if cfg.frontend and cfg.frontend.build_cmd and not args.skip_build:
        cwd = cfg.frontend.project_root or cfg.config_path.parent
        print(f"==> build: {cfg.frontend.build_cmd} (cwd={cwd})")
        proc = subprocess.run(
            cfg.frontend.build_cmd,
            shell=True,
            cwd=str(cwd),
            check=False,
        )
        if proc.returncode != 0:
            _die(f"build_cmd failed with exit {proc.returncode}")

    # up
    up_ns = argparse.Namespace(
        config=args.config or str(cfg.config_path),
        skip_linger=args.skip_linger,
        copy_unit=True,
        retries=args.retries,
    )
    rc = cmd_up(up_ns)
    if rc != 0 and not args.allow_unhealthy:
        return rc

    if cfg.frontend:
        print("==> frontend write-ini")
        write_ini(cfg, merge=not args.replace_ini)
        if not args.skip_load:
            print("==> frontend load")
            load_ns = argparse.Namespace(config=str(cfg.config_path))
            rc_load = cmd_frontend_load(load_ns)
            if rc_load != 0:
                return rc_load
        else:
            print("==> skip frontend load")

    print()
    print(f"App:    https://{cfg.host}/")
    print(f"API:    https://{cfg.host}{cfg.frontend.proxy_prefix if cfg.frontend else '/api'}/…")
    print(f"Direct: curl -fsS {cfg.backend.health_url}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="silk-sidecar",
        description=(
            "Manage durable localhost backends on UVM Silk "
            "(systemd --user + linger) and wire them to Unit Node frontends."
        ),
    )
    p.add_argument("--version", action="version", version=f"silk-sidecar {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    # init
    s = sub.add_parser("init", help="Scaffold silk-sidecar.json")
    s.add_argument("--path", default="silk-sidecar.json")
    s.add_argument("--name", default=None)
    s.add_argument("--netid", default=None)
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--backend-only", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    # register
    s = sub.add_parser("register", help="Register app in ~/.config/silk-sidecar")
    s.add_argument("--config", default=None)
    s.set_defaults(func=cmd_register)

    s = sub.add_parser("unregister", help="Remove app from registry")
    s.add_argument("--config", default=None)
    s.add_argument("--name", default=None)
    s.set_defaults(func=cmd_unregister)

    # linger
    s = sub.add_parser("linger", help="Show or enable user lingering")
    s.add_argument("action", choices=["show", "enable"])
    s.add_argument("--user", default=None)
    s.set_defaults(func=cmd_linger)

    # lifecycle
    for name, help_text, func in [
        ("up", "Install unit, enable linger, start, health-probe", cmd_up),
        ("down", "Stop the user unit", cmd_down),
        ("restart", "Restart the user unit", cmd_restart),
        ("status", "systemctl --user status", cmd_status),
        ("logs", "journalctl --user -u …", cmd_logs),
        ("doctor", "Check linger, unit, port, health, frontend", cmd_doctor),
    ]:
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--config", default=None)
        if name == "up":
            s.add_argument("--skip-linger", action="store_true")
            s.add_argument("--copy-unit", action="store_true", default=True)
            s.add_argument("--retries", type=int, default=8)
        if name == "down":
            s.add_argument("--disable", action="store_true")
        if name == "logs":
            s.add_argument("-n", "--lines", type=int, default=80)
            s.add_argument("-f", "--follow", action="store_true")
        s.set_defaults(func=func)

    s = sub.add_parser("list", help="List registered apps")
    s.set_defaults(func=cmd_list)

    # frontend
    fe = sub.add_parser("frontend", help="Silk Unit / Next frontend helpers")
    fe_sub = fe.add_subparsers(dest="frontend_command", required=True)

    s = fe_sub.add_parser("write-ini", help="Write/merge site-root .silk.ini")
    s.add_argument("--config", default=None)
    s.add_argument("--replace", action="store_true", help="Replace file instead of merge")
    s.set_defaults(func=cmd_frontend_write_ini)

    s = fe_sub.add_parser("rewrite-snippet", help="Emit Next.js rewrite snippet")
    s.add_argument("--config", default=None)
    s.add_argument("-o", "--output", default=None)
    s.set_defaults(func=cmd_frontend_rewrite_snippet)

    s = fe_sub.add_parser("load", help="silk site update + silk app load")
    s.add_argument("--config", default=None)
    s.set_defaults(func=cmd_frontend_load)

    # deploy
    s = sub.add_parser("deploy", help="build (optional) + up + write-ini + load")
    s.add_argument("--config", default=None)
    s.add_argument("--skip-build", action="store_true")
    s.add_argument("--skip-load", action="store_true")
    s.add_argument("--skip-linger", action="store_true")
    s.add_argument("--replace-ini", action="store_true")
    s.add_argument("--allow-unhealthy", action="store_true")
    s.add_argument("--retries", type=int, default=8)
    s.set_defaults(func=cmd_deploy)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except RuntimeError as exc:
        _die(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
