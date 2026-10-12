"""Find and kill stale Silk Unit Node workers for this account."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from silk_sidecar.config import AppConfig


@dataclass
class ProcInfo:
    pid: int
    args: str


@dataclass
class KillReport:
    matched: list[ProcInfo]
    term_sent: list[int]
    kill_sent: list[int]
    still_running: list[ProcInfo]


def _current_uid() -> int:
    return os.getuid()


def list_user_node_procs() -> list[ProcInfo]:
    """List this user's node / Unit-related processes."""
    try:
        proc = subprocess.run(
            [
                "ps",
                "-u",
                str(_current_uid()),
                "-o",
                "pid=,args=",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    out: list[ProcInfo] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        args = parts[1]
        low = args.lower()
        if any(
            token in low
            for token in (
                "node ",
                "/node ",
                "server.js",
                "nginx-unit",
                "unit:",
            )
        ):
            # Skip the silk-sidecar / ps helpers themselves
            if "silk_sidecar" in low or "kill-stale" in low:
                continue
            out.append(ProcInfo(pid=pid, args=args))
    return out


def match_patterns_for(cfg: AppConfig) -> list[str]:
    """Return substrings used to match stale workers for this app."""
    patterns: list[str] = []
    if cfg.frontend:
        startup = cfg.frontend.startup_script or "server.js"
        root = cfg.frontend.root.strip("/")
        # Prefer specific path under site root / relative root
        if root:
            patterns.append(f"{root}/{startup}")
            patterns.append(root)
        patterns.append(startup)
        # Dist folder basename often appears in argv
        if root:
            patterns.append(Path(root).name)
    # Broad fallback: any node server.js for this user (Unit workers)
    patterns.append("server.js")
    # de-dupe preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for p in patterns:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def find_stale(cfg: AppConfig, *, broad: bool = False) -> list[ProcInfo]:
    """Match Node workers likely belonging to this frontend app."""
    procs = list_user_node_procs()
    if not procs:
        return []
    patterns = match_patterns_for(cfg)
    # Specific patterns first (path fragments); optional broad = any node
    matched: list[ProcInfo] = []
    for proc in procs:
        args = proc.args
        if any(pat in args for pat in patterns):
            matched.append(proc)
            continue
        if broad and ("node" in args.lower()):
            matched.append(proc)
    # unique by pid
    by_pid = {p.pid: p for p in matched}
    return [by_pid[k] for k in sorted(by_pid)]


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_pids(pids: list[int], *, wait: float = 2.0) -> KillReport:
    term_sent: list[int] = []
    kill_sent: list[int] = []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            term_sent.append(pid)
        except OSError:
            continue
    if wait > 0:
        time.sleep(wait)
    for pid in term_sent:
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
                kill_sent.append(pid)
            except OSError:
                continue
    if kill_sent:
        time.sleep(0.3)
    still = [ProcInfo(pid=p, args="") for p in pids if _pid_alive(p)]
    # refresh args for still-running
    living = {p.pid: p for p in list_user_node_procs()}
    still_running = [living[p.pid] for p in still if p.pid in living]
    return KillReport(
        matched=[],
        term_sent=term_sent,
        kill_sent=kill_sent,
        still_running=still_running,
    )


def kill_stale(
    cfg: AppConfig,
    *,
    broad: bool = False,
    dry_run: bool = False,
) -> KillReport:
    matched = find_stale(cfg, broad=broad)
    if dry_run or not matched:
        return KillReport(
            matched=matched,
            term_sent=[],
            kill_sent=[],
            still_running=matched if dry_run else [],
        )
    report = kill_pids([p.pid for p in matched])
    report.matched = matched
    return report


def format_procs(procs: list[ProcInfo]) -> str:
    if not procs:
        return "(none)"
    lines = [f"  {p.pid:>7}  {p.args}" for p in procs]
    return "\n".join(lines)
