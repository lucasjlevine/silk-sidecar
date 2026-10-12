"""Merge-aware .silk.ini writer for Silk Unit Node apps."""

from __future__ import annotations

import re
from pathlib import Path

from silk_sidecar.config import AppConfig, FrontendConfig

APP_HEADER_RE = re.compile(r"^\[app:\s*(.+?)\s*\]\s*$")
SECTION_RE = re.compile(r"^\[(.+?)\]\s*$")


def silk_ini_path(cfg: AppConfig) -> Path:
    return cfg.site_root / ".silk.ini"


def render_app_stanza(frontend: FrontendConfig, *, document_root_general: str = "public") -> str:
    env = {
        "NODE_ENV": "production",
        "HOSTNAME": "127.0.0.1",
        "PORT": "3000",
        **frontend.environment,
    }
    lines = [
        f"[app: {frontend.app_name}]",
        "type = nodejs",
        f"root = {frontend.root}",
        f"uri = {frontend.uri}",
        f"document-root = {frontend.document_root or document_root_general}",
        f"startup-script = {frontend.startup_script}",
    ]
    for key, value in env.items():
        lines.append(f"env.{key} = {value}")
    return "\n".join(lines) + "\n"


def render_full_ini(cfg: AppConfig) -> str:
    if not cfg.frontend:
        raise ValueError("config has no frontend section")
    fr = cfg.frontend
    parts = [
        "# Generated/managed by silk-sidecar",
        "#",
        "# Architecture:",
        "#   - Node Unit app serves the site",
        f"#   - Backend via systemd --user on 127.0.0.1:{cfg.backend.port}",
        f"#   - Proxy {fr.proxy_prefix}/* → http://127.0.0.1:{cfg.backend.port}{fr.proxy_prefix}/*",
        "#     (configure in your Next/server rewrite layer)",
        "",
        "[general]",
        f"document-root = {fr.document_root}",
        f"max-request-length = {fr.max_request_length}",
        f"request-timeout = {fr.request_timeout}",
        "redirect-insecure-http = true",
        "",
        "[nodejs]",
        f"version = {fr.node_version}",
        "",
        render_app_stanza(fr).rstrip(),
        "",
    ]
    return "\n".join(parts)


def _split_sections(text: str) -> list[tuple[str | None, list[str]]]:
    """Return list of (section_name_or_None_for_preamble, lines including header)."""
    sections: list[tuple[str | None, list[str]]] = []
    current_name: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_name, current_lines
        if current_name is not None or current_lines:
            sections.append((current_name, current_lines))
        current_name = None
        current_lines = []

    for line in text.splitlines():
        m = SECTION_RE.match(line.strip())
        if m:
            flush()
            current_name = m.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    flush()
    return sections


def _app_name_from_section(section_name: str | None) -> str | None:
    if not section_name:
        return None
    if section_name.lower().startswith("app:"):
        return section_name.split(":", 1)[1].strip()
    return None


def merge_ini(existing: str, cfg: AppConfig) -> str:
    if not cfg.frontend:
        raise ValueError("config has no frontend section")
    fr = cfg.frontend
    managed_app = fr.app_name
    new_app = render_app_stanza(fr).rstrip("\n").splitlines()

    if not existing.strip():
        return render_full_ini(cfg)

    sections = _split_sections(existing)
    out_lines: list[str] = []
    replaced_app = False
    seen_general = False
    seen_nodejs = False

    for name, lines in sections:
        app = _app_name_from_section(name)
        if app is not None and app == managed_app:
            if out_lines and out_lines[-1].strip() != "":
                out_lines.append("")
            out_lines.extend(new_app)
            replaced_app = True
            continue

        if name == "general":
            seen_general = True
        if name == "nodejs":
            seen_nodejs = True
            # Ensure version line reflects config
            rewritten = [lines[0]]
            has_version = False
            for line in lines[1:]:
                if line.strip().startswith("version"):
                    rewritten.append(f"version = {fr.node_version}")
                    has_version = True
                else:
                    rewritten.append(line)
            if not has_version:
                rewritten.append(f"version = {fr.node_version}")
            out_lines.extend(rewritten)
            continue

        out_lines.extend(lines)

    if not seen_general:
        preamble = [
            "[general]",
            f"document-root = {fr.document_root}",
            f"max-request-length = {fr.max_request_length}",
            f"request-timeout = {fr.request_timeout}",
            "redirect-insecure-http = true",
            "",
        ]
        out_lines = preamble + out_lines

    if not seen_nodejs:
        out_lines.extend(["", "[nodejs]", f"version = {fr.node_version}"])

    if not replaced_app:
        if out_lines and out_lines[-1].strip() != "":
            out_lines.append("")
        out_lines.extend(new_app)

    text = "\n".join(out_lines).rstrip() + "\n"
    return text


def write_ini(cfg: AppConfig, *, merge: bool = True) -> Path:
    path = silk_ini_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    if merge and path.is_file():
        text = merge_ini(path.read_text(encoding="utf-8"), cfg)
    else:
        text = render_full_ini(cfg)
    path.write_text(text, encoding="utf-8")
    return path
