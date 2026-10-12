"""Render and manage systemd --user units for localhost backends."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from string import Template

from silk_sidecar.config import AppConfig


def user_unit_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "systemd" / "user"


def unit_path(cfg: AppConfig) -> Path:
    return user_unit_dir() / cfg.unit_name


def templates_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "templates"


def render_unit(cfg: AppConfig) -> str:
    template_path = templates_dir() / "unit.service.tmpl"
    if template_path.is_file():
        tmpl = Template(template_path.read_text(encoding="utf-8"))
    else:
        tmpl = Template(_DEFAULT_UNIT)

    env_lines = []
    for key, value in sorted(cfg.backend.environment.items()):
        # systemd Environment= values with spaces need quoting
        env_lines.append(f"Environment={key}={_systemd_escape(value)}")
    environment_block = "\n".join(env_lines)

    description = cfg.backend.unit_description or (
        f"{cfg.name} localhost backend (:{cfg.backend.port})"
    )

    # ExecStart is argv-style (no shell). Prefer an absolute binary path.
    exec_start = _format_exec_start(cfg.backend.exec)

    return tmpl.substitute(
        description=description,
        workdir=str(cfg.backend.workdir),
        environment_block=environment_block,
        exec_start=exec_start,
        port=str(cfg.backend.port),
    )


def install_unit(cfg: AppConfig) -> Path:
    path = unit_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render_unit(cfg)
    # Drop empty Environment block blank lines cleanly
    lines = []
    for line in text.splitlines():
        if line.strip() == "" and lines and lines[-1].strip() == "":
            continue
        lines.append(line)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def _systemd_escape(value: str) -> str:
    if value == "" or any(c in value for c in ' \t"\'\\'):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _format_exec_start(command: str) -> str:
    parts = shlex.split(command)
    if not parts:
        raise ValueError("backend.exec is empty")
    if not parts[0].startswith("/"):
        resolved = _which(parts[0])
        if resolved:
            parts[0] = resolved
    return " ".join(_systemd_escape(p) for p in parts)


def _which(cmd: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / cmd
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    return None


def systemctl_user(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def journalctl_user(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["journalctl", "--user", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def daemon_reload() -> None:
    systemctl_user("daemon-reload")


def enable_and_start(cfg: AppConfig) -> None:
    daemon_reload()
    systemctl_user("enable", cfg.unit_name)
    systemctl_user("restart", cfg.unit_name)


def stop_unit(cfg: AppConfig, *, disable: bool = False) -> None:
    systemctl_user("stop", cfg.unit_name, check=False)
    if disable:
        systemctl_user("disable", cfg.unit_name, check=False)


def unit_is_active(cfg: AppConfig) -> bool:
    proc = systemctl_user("is-active", cfg.unit_name, check=False)
    return proc.stdout.strip() == "active"


def unit_status_text(cfg: AppConfig) -> str:
    proc = systemctl_user("--no-pager", "--full", "status", cfg.unit_name, check=False)
    return (proc.stdout or proc.stderr or "").strip()


def recent_logs(cfg: AppConfig, lines: int = 80) -> str:
    proc = journalctl_user("-u", cfg.unit_name, "-n", str(lines), "--no-pager")
    return (proc.stdout or proc.stderr or "").strip()


def copy_unit_to_project(cfg: AppConfig, dest_dir: Path | None = None) -> Path | None:
    """Optionally keep a human-readable copy next to the config."""
    if dest_dir is None:
        dest_dir = cfg.config_path.parent / "systemd"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / cfg.unit_name
        dest.write_text(unit_path(cfg).read_text(encoding="utf-8"), encoding="utf-8")
        return dest
    except OSError:
        return None


_DEFAULT_UNIT = """\
[Unit]
Description=$description
After=network.target

[Service]
Type=simple
WorkingDirectory=$workdir
$environment_block
ExecStart=$exec_start
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
"""
