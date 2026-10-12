"""Load and validate silk-sidecar.json configs."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_NAMES = ("silk-sidecar.json",)

UNIT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,180}$")


class ConfigError(ValueError):
    pass


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def expand_str(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(value))


@dataclass
class BackendConfig:
    port: int
    workdir: Path
    exec: str
    health_path: str = "/health"
    environment: dict[str, str] = field(default_factory=dict)
    unit_description: str | None = None

    @property
    def health_url(self) -> str:
        path = self.health_path if self.health_path.startswith("/") else f"/{self.health_path}"
        return f"http://127.0.0.1:{self.port}{path}"


@dataclass
class FrontendConfig:
    type: str = "nodejs"
    root: str = ""
    uri: str = "/*"
    startup_script: str = "server.js"
    node_version: str = "22"
    document_root: str = "public"
    proxy_prefix: str = "/api"
    build_cmd: str | None = None
    project_root: Path | None = None
    app_name: str = "web"
    max_request_length: int = 10485760
    request_timeout: int = 60
    environment: dict[str, str] = field(default_factory=dict)


@dataclass
class AppConfig:
    name: str
    netid: str
    host: str
    site_root: Path
    backend: BackendConfig
    frontend: FrontendConfig | None
    config_path: Path

    @property
    def unit_name(self) -> str:
        return self.name if self.name.endswith(".service") else f"{self.name}.service"

    @property
    def unit_basename(self) -> str:
        return self.unit_name.removesuffix(".service")


def find_config(start: Path | None = None) -> Path | None:
    cur = (start or Path.cwd()).resolve()
    for directory in [cur, *cur.parents]:
        for name in CONFIG_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _require(data: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in data:
        raise ConfigError(f"{ctx}: missing required field '{key}'")
    return data[key]


def _as_str_dict(value: Any, ctx: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{ctx}: expected object")
    out: dict[str, str] = {}
    for k, v in value.items():
        out[str(k)] = str(v)
    return out


def load_config(path: Path | str) -> AppConfig:
    path = Path(path).resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: root must be an object")

    name = str(_require(raw, "name", "root"))
    if not UNIT_NAME_RE.match(name.removesuffix(".service")):
        raise ConfigError(
            f"root.name: invalid unit name '{name}' "
            "(use letters, digits, . _ @ -)"
        )

    netid = str(raw.get("netid") or os.environ.get("USER") or os.environ.get("LOGNAME") or "")
    if not netid:
        raise ConfigError("root.netid: required (or set $USER)")
    host = str(raw.get("host") or f"{netid}.w3.uvm.edu")
    site_root = expand_path(str(raw.get("site_root") or "~/www-root"))

    backend_raw = _require(raw, "backend", "root")
    if not isinstance(backend_raw, dict):
        raise ConfigError("backend: expected object")

    port = int(_require(backend_raw, "port", "backend"))
    if not (1 <= port <= 65535):
        raise ConfigError(f"backend.port: out of range ({port})")

    workdir = expand_path(str(_require(backend_raw, "workdir", "backend")))
    exec_cmd = expand_str(str(_require(backend_raw, "exec", "backend")))
    if "0.0.0.0" in exec_cmd:
        raise ConfigError(
            "backend.exec: must bind 127.0.0.1 only (found 0.0.0.0)"
        )

    backend = BackendConfig(
        port=port,
        workdir=workdir,
        exec=exec_cmd,
        health_path=str(backend_raw.get("health_path") or "/health"),
        environment=_as_str_dict(backend_raw.get("environment"), "backend.environment"),
        unit_description=(
            str(backend_raw["unit_description"])
            if backend_raw.get("unit_description")
            else None
        ),
    )

    frontend: FrontendConfig | None = None
    if "frontend" in raw and raw["frontend"] is not None:
        fr = raw["frontend"]
        if not isinstance(fr, dict):
            raise ConfigError("frontend: expected object")
        project_root = None
        if fr.get("project_root"):
            project_root = expand_path(str(fr["project_root"]))
        frontend = FrontendConfig(
            type=str(fr.get("type") or "nodejs"),
            root=str(_require(fr, "root", "frontend")),
            uri=str(fr.get("uri") or "/*"),
            startup_script=str(fr.get("startup_script") or "server.js"),
            node_version=str(fr.get("node_version") or "22"),
            document_root=str(fr.get("document_root") or "public"),
            proxy_prefix=str(fr.get("proxy_prefix") or "/api"),
            build_cmd=str(fr["build_cmd"]) if fr.get("build_cmd") else None,
            project_root=project_root,
            app_name=str(fr.get("app_name") or "web"),
            max_request_length=int(fr.get("max_request_length") or 10485760),
            request_timeout=int(fr.get("request_timeout") or 60),
            environment=_as_str_dict(fr.get("environment"), "frontend.environment"),
        )
        if frontend.type != "nodejs":
            raise ConfigError(
                f"frontend.type: only 'nodejs' supported in v1 (got '{frontend.type}')"
            )

    return AppConfig(
        name=name.removesuffix(".service"),
        netid=netid,
        host=host,
        site_root=site_root,
        backend=backend,
        frontend=frontend,
        config_path=path,
    )


def default_init_config(
    *,
    name: str,
    netid: str,
    port: int = 8000,
    with_frontend: bool = True,
) -> dict[str, Any]:
    host = f"{netid}.w3.uvm.edu"
    cfg: dict[str, Any] = {
        "name": name,
        "netid": netid,
        "host": host,
        "site_root": "~/www-root",
        "backend": {
            "port": port,
            "workdir": f"~/www-root/{name}",
            "exec": (
                f"python3 -m http.server {port} --bind 127.0.0.1"
            ),
            "health_path": "/",
            "environment": {
                "CORS_ORIGINS": f"https://{host}",
            },
            "unit_description": f"{name} localhost backend (:{port})",
        },
    }
    if with_frontend:
        cfg["frontend"] = {
            "type": "nodejs",
            "app_name": "web",
            "root": f"{name}/dist/web",
            "uri": "/*",
            "startup_script": "server.js",
            "node_version": "22",
            "document_root": "public",
            "proxy_prefix": "/api",
            "project_root": f"~/www-root/{name}",
        }
    return cfg


def write_init_config(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path
