"""Wrappers around the Silk `silk` CLI."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class SilkResult:
    ok: bool
    command: list[str]
    stdout: str
    stderr: str
    returncode: int


def silk_available() -> bool:
    return shutil.which("silk") is not None


def run_silk(*args: str, check: bool = False) -> SilkResult:
    if not silk_available():
        return SilkResult(
            ok=False,
            command=["silk", *args],
            stdout="",
            stderr="silk CLI not found on PATH (expected on Silk hosts)",
            returncode=127,
        )
    proc = subprocess.run(
        ["silk", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    ok = proc.returncode == 0
    if check and not ok:
        raise RuntimeError(
            f"silk {' '.join(args)} failed ({proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    return SilkResult(
        ok=ok,
        command=["silk", *args],
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=proc.returncode,
    )


def site_update(host: str) -> SilkResult:
    return run_silk("site", host.rstrip("/"), "update")


def app_target(host: str, uri: str = "/*") -> str:
    """Silk app locator: hostname + uri pattern (e.g. host/*).

    ``silk app HOST load`` looks up ``HOST/`` and misses apps whose
    ``.silk.ini`` uri is ``/*``. Pass ``HOST/*`` instead.
    See https://silk.uvm.edu/manual/nodejs/
    """
    host = host.rstrip("/")
    uri = (uri or "/*").strip()
    if not uri.startswith("/"):
        uri = f"/{uri}"
    return f"{host}{uri}"


def app_load(host: str, uri: str = "/*") -> SilkResult:
    return run_silk("app", app_target(host, uri), "load")


def frontend_load(host: str, uri: str = "/*") -> list[SilkResult]:
    return [site_update(host), app_load(host, uri)]
