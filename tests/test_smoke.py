#!/usr/bin/env python3
"""Stdlib smoke tests (no systemd required)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from silk_sidecar.config import ConfigError, load_config, default_init_config, write_init_config
from silk_sidecar.frontend_ini import merge_ini, render_full_ini
from silk_sidecar.next_rewrite import render_snippet
from silk_sidecar.silk_cmd import app_target
from silk_sidecar.stale import match_patterns_for
from silk_sidecar.systemd_unit import render_unit


class ConfigTests(unittest.TestCase):
    def test_init_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "silk-sidecar.json"
            write_init_config(path, default_init_config(name="demo", netid="alice", port=8123))
            cfg = load_config(path)
            self.assertEqual(cfg.name, "demo")
            self.assertEqual(cfg.backend.port, 8123)
            self.assertEqual(cfg.host, "alice.w3.uvm.edu")
            self.assertIsNotNone(cfg.frontend)

    def test_rejects_bind_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "silk-sidecar.json"
            data = default_init_config(name="bad", netid="alice", port=8000)
            data["backend"]["exec"] = "uvicorn app:app --host 0.0.0.0 --port 8000"
            data["backend"]["workdir"] = tmp
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_unit_contains_localhost_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "silk-sidecar.json"
            data = default_init_config(name="svc", netid="bob", port=9000)
            data["backend"]["workdir"] = tmp
            data["backend"]["exec"] = f"/usr/bin/python3 -m http.server 9000 --bind 127.0.0.1"
            write_init_config(path, data)
            cfg = load_config(path)
            unit = render_unit(cfg)
            self.assertIn("WorkingDirectory=", unit)
            self.assertIn("ExecStart=", unit)
            self.assertIn("Restart=on-failure", unit)
            self.assertIn("WantedBy=default.target", unit)

    def test_ini_merge_preserves_other_apps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "silk-sidecar.json"
            data = default_init_config(name="svc", netid="bob", port=9000)
            data["backend"]["workdir"] = tmp
            data["frontend"]["app_name"] = "web"
            data["frontend"]["root"] = "svc/dist"
            write_init_config(path, data)
            cfg = load_config(path)
            existing = """\
[general]
document-root = public

[nodejs]
version = 20

[app: other]
type = nodejs
root = other/app
uri = /other
startup-script = server.js

[app: web]
type = nodejs
root = old/path
uri = /*
startup-script = server.js
"""
            merged = merge_ini(existing, cfg)
            self.assertIn("[app: other]", merged)
            self.assertIn("root = other/app", merged)
            self.assertIn("root = svc/dist", merged)
            self.assertNotIn("root = old/path", merged)
            self.assertIn("version = 22", merged)

    def test_rewrite_snippet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "silk-sidecar.json"
            data = default_init_config(name="svc", netid="bob", port=9000)
            data["backend"]["workdir"] = tmp
            write_init_config(path, data)
            cfg = load_config(path)
            snip = render_snippet(cfg)
            self.assertIn("127.0.0.1:9000", snip)
            self.assertIn("/api/:path*", snip)

    def test_stale_match_patterns_include_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "silk-sidecar.json"
            data = default_init_config(name="demo", netid="alice", port=8000)
            data["backend"]["workdir"] = tmp
            data["frontend"]["root"] = "silk-hello/dist/web"
            data["frontend"]["startup_script"] = "server.js"
            write_init_config(path, data)
            cfg = load_config(path)
            pats = match_patterns_for(cfg)
            self.assertIn("silk-hello/dist/web/server.js", pats)
            self.assertIn("server.js", pats)

    def test_app_target_includes_uri_star(self) -> None:
        self.assertEqual(
            app_target("ljlevine.w3.uvm.edu", "/*"),
            "ljlevine.w3.uvm.edu/*",
        )
        self.assertEqual(
            app_target("ljlevine.w3.uvm.edu/", "/myapp*"),
            "ljlevine.w3.uvm.edu/myapp*",
        )
        self.assertEqual(
            app_target("host.example", "api*"),
            "host.example/api*",
        )

    def test_hello_example_config_shape(self) -> None:
        """Hello example generates silk-sidecar.json via setup.sh; validate shape here."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data = {
                "name": "silk-hello-api",
                "netid": "demo",
                "host": "demo.w3.uvm.edu",
                "site_root": str(tmp_path),
                "backend": {
                    "port": 8765,
                    "workdir": str(tmp_path),
                    "exec": "/usr/bin/true",
                    "health_path": "/api/health",
                    "environment": {},
                },
                "frontend": {
                    "type": "nodejs",
                    "app_name": "hello",
                    "root": "silk-hello/dist/web",
                    "uri": "/*",
                    "startup_script": "server.js",
                    "proxy_prefix": "/api",
                    "environment": {"API_UPSTREAM": "http://127.0.0.1:8765"},
                },
            }
            path = tmp_path / "silk-sidecar.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            cfg = load_config(path)
            self.assertEqual(cfg.name, "silk-hello-api")
            self.assertEqual(cfg.backend.port, 8765)
            self.assertEqual(cfg.frontend.app_name, "hello")
            full = render_full_ini(cfg)
            self.assertIn("[app: hello]", full)
            self.assertIn("env.API_UPSTREAM = http://127.0.0.1:8765", full)
            self.assertTrue((ROOT / "examples" / "hello" / "run-local.sh").is_file())
            self.assertTrue((ROOT / "examples" / "hello" / "backend" / "main.py").is_file())


if __name__ == "__main__":
    unittest.main()
