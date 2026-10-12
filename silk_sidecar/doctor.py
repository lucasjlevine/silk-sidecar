"""Health / readiness checks for a silk-sidecar app."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from silk_sidecar.config import AppConfig
from silk_sidecar.frontend_ini import silk_ini_path
from silk_sidecar.health import port_open, probe_url
from silk_sidecar.linger import show_linger
from silk_sidecar.silk_cmd import silk_available
from silk_sidecar.systemd_unit import unit_is_active, unit_path


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required_for_ready: bool = True


def run_doctor(cfg: AppConfig) -> list[Check]:
    checks: list[Check] = []

    # Linger
    try:
        linger = show_linger(cfg.netid)
        checks.append(
            Check(
                name="linger",
                ok=linger.enabled,
                detail=(
                    f"{linger.raw} — user systemd survives SSH logout"
                    if linger.enabled
                    else f"{linger.raw} — run: silk-sidecar linger enable"
                ),
                required_for_ready=True,
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            Check(
                name="linger",
                ok=False,
                detail=str(exc),
                required_for_ready=True,
            )
        )

    # Unit file
    upath = unit_path(cfg)
    checks.append(
        Check(
            name="unit-file",
            ok=upath.is_file(),
            detail=str(upath) if upath.is_file() else f"missing {upath} (run: silk-sidecar up)",
        )
    )

    # Unit active
    try:
        active = unit_is_active(cfg)
        checks.append(
            Check(
                name="unit-active",
                ok=active,
                detail="active" if active else "not active (run: silk-sidecar up)",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            Check(
                name="unit-active",
                ok=False,
                detail=f"systemctl unavailable: {exc}",
            )
        )

    # Port
    listening = port_open("127.0.0.1", cfg.backend.port)
    checks.append(
        Check(
            name="port",
            ok=listening,
            detail=(
                f"127.0.0.1:{cfg.backend.port} open"
                if listening
                else f"127.0.0.1:{cfg.backend.port} not listening"
            ),
        )
    )

    # Health
    probe = probe_url(cfg.backend.health_url, retries=2, delay=0.2)
    checks.append(
        Check(
            name="health",
            ok=probe.ok,
            detail=f"{probe.url} → {probe.message}",
        )
    )

    # Workdir
    checks.append(
        Check(
            name="workdir",
            ok=cfg.backend.workdir.is_dir(),
            detail=str(cfg.backend.workdir),
        )
    )

    # Frontend pieces (optional for "backend-only ready")
    if cfg.frontend:
        ini = silk_ini_path(cfg)
        checks.append(
            Check(
                name="silk-ini",
                ok=ini.is_file(),
                detail=str(ini) if ini.is_file() else f"missing {ini} (run: silk-sidecar frontend write-ini)",
                required_for_ready=False,
            )
        )
        fe_root = cfg.site_root / cfg.frontend.root
        startup = fe_root / cfg.frontend.startup_script
        checks.append(
            Check(
                name="frontend-startup",
                ok=startup.is_file(),
                detail=(
                    str(startup)
                    if startup.is_file()
                    else f"missing {startup} (build frontend first)"
                ),
                required_for_ready=False,
            )
        )

    checks.append(
        Check(
            name="silk-cli",
            ok=silk_available(),
            detail="silk on PATH" if silk_available() else "silk CLI not found (ok off-host)",
            required_for_ready=False,
        )
    )

    return checks


def is_ready(checks: list[Check]) -> bool:
    return all(c.ok for c in checks if c.required_for_ready)


def format_doctor_report(cfg: AppConfig, checks: list[Check]) -> str:
    lines = [
        f"doctor: {cfg.name}",
        f"  config: {cfg.config_path}",
        f"  host:   https://{cfg.host}",
        f"  api:    {cfg.backend.health_url}",
        "",
    ]
    for c in checks:
        mark = "OK " if c.ok else "FAIL"
        req = "" if c.required_for_ready else " (optional)"
        lines.append(f"  [{mark}] {c.name}{req}: {c.detail}")
    lines.append("")
    if is_ready(checks):
        lines.append("READY — backend should survive SSH logout (linger on + unit active).")
        lines.append("Verify: log out of SSH, wait 30s, reconnect, then:")
        lines.append(f"  systemctl --user status {cfg.unit_name}")
        lines.append(f"  curl -fsS {cfg.backend.health_url}")
    else:
        lines.append("NOT READY — fix FAIL items above.")
        if any(c.name == "linger" and not c.ok for c in checks):
            lines.append(f"  silk-sidecar linger enable --user {cfg.netid}")
    return "\n".join(lines) + "\n"
