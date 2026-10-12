"""Emit Next.js rewrite helpers that proxy API paths to localhost backends."""

from __future__ import annotations

from pathlib import Path
from string import Template

from silk_sidecar.config import AppConfig


def templates_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "templates"


def render_snippet(cfg: AppConfig) -> str:
    if not cfg.frontend:
        raise ValueError("config has no frontend section")
    prefix = cfg.frontend.proxy_prefix.rstrip("/") or "/api"
    upstream = f"http://127.0.0.1:{cfg.backend.port}{prefix}"
    template_path = templates_dir() / "next.rewrites.snippet.js"
    if template_path.is_file():
        tmpl = Template(template_path.read_text(encoding="utf-8"))
    else:
        tmpl = Template(_DEFAULT_SNIPPET)
    return tmpl.substitute(
        proxy_prefix=prefix,
        upstream=upstream,
        port=str(cfg.backend.port),
        name=cfg.name,
    )


def write_snippet(cfg: AppConfig, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_snippet(cfg), encoding="utf-8")
    return dest


_DEFAULT_SNIPPET = """\
// silk-sidecar rewrite helper for $name
// Proxy browser $proxy_prefix/* → $upstream/*
//
// next.config.js / next.config.mjs example:
//
//   async rewrites() {
//     return [
//       {
//         source: '$proxy_prefix/:path*',
//         destination: '$upstream/:path*',
//       },
//     ];
//   },
//
// Or set env at build time:
//   RELAX_API_UPSTREAM=$upstream
//   NEXT_PUBLIC_API_URL=$proxy_prefix

module.exports = {
  source: '$proxy_prefix/:path*',
  destination: '$upstream/:path*',
};
"""
