"""loginctl linger helpers — keep systemd --user alive after SSH logout."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


@dataclass
class LingerStatus:
    user: str
    enabled: bool
    raw: str


def current_user() -> str:
    return os.environ.get("USER") or os.environ.get("LOGNAME") or os.getlogin()


def show_linger(user: str | None = None) -> LingerStatus:
    user = user or current_user()
    try:
        proc = subprocess.run(
            ["loginctl", "show-user", user, "-p", "Linger", "--value"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("loginctl not found (are you on Silk/Linux?)") from exc

    raw = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        # Older loginctl may not support --value
        proc2 = subprocess.run(
            ["loginctl", "show-user", user, "-p", "Linger"],
            check=False,
            capture_output=True,
            text=True,
        )
        raw = (proc2.stdout or "").strip()
        enabled = "Linger=yes" in raw.replace(" ", "")
        if proc2.returncode != 0:
            raise RuntimeError(
                f"loginctl show-user failed for {user}: {proc2.stderr.strip() or raw}"
            )
        return LingerStatus(user=user, enabled=enabled, raw=raw)

    enabled = raw.lower() in {"yes", "true", "1"}
    return LingerStatus(user=user, enabled=enabled, raw=raw or f"Linger={'yes' if enabled else 'no'}")


def enable_linger(user: str | None = None) -> LingerStatus:
    user = user or current_user()
    try:
        proc = subprocess.run(
            ["loginctl", "enable-linger", user],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("loginctl not found (are you on Silk/Linux?)") from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            f"loginctl enable-linger {user} failed: {err or 'unknown error'}\n"
            "You may need to run this once interactively on Silk."
        )
    return show_linger(user)


def ensure_linger(user: str | None = None, *, enable: bool = True) -> LingerStatus:
    status = show_linger(user)
    if status.enabled or not enable:
        return status
    return enable_linger(user)
