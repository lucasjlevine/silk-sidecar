"""Health probes for localhost backends."""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class ProbeResult:
    ok: bool
    url: str
    status_code: int | None
    message: str
    elapsed_ms: int


def port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_url(
    url: str,
    *,
    timeout: float = 5.0,
    retries: int = 5,
    delay: float = 0.4,
) -> ProbeResult:
    last_message = "no attempts"
    last_code: int | None = None
    started = time.monotonic()
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = getattr(resp, "status", None) or resp.getcode()
                body = resp.read(256)
                elapsed = int((time.monotonic() - started) * 1000)
                ok = 200 <= int(code) < 400
                return ProbeResult(
                    ok=ok,
                    url=url,
                    status_code=int(code),
                    message=f"HTTP {code} ({len(body)} bytes) attempt={attempt}",
                    elapsed_ms=elapsed,
                )
        except urllib.error.HTTPError as exc:
            last_code = exc.code
            last_message = f"HTTP {exc.code}: {exc.reason}"
            if 200 <= exc.code < 400:
                elapsed = int((time.monotonic() - started) * 1000)
                return ProbeResult(
                    ok=True,
                    url=url,
                    status_code=exc.code,
                    message=last_message,
                    elapsed_ms=elapsed,
                )
        except Exception as exc:  # noqa: BLE001 — surface any probe failure
            last_message = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(delay)
    elapsed = int((time.monotonic() - started) * 1000)
    return ProbeResult(
        ok=False,
        url=url,
        status_code=last_code,
        message=last_message,
        elapsed_ms=elapsed,
    )
