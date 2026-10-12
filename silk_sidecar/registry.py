"""Global registry of managed apps under ~/.config/silk-sidecar/."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".config"


def registry_dir() -> Path:
    return config_home() / "silk-sidecar"


def registry_path() -> Path:
    return registry_dir() / "apps.json"


@dataclass
class RegistryEntry:
    name: str
    config_path: str
    host: str
    port: int


def load_registry() -> dict[str, RegistryEntry]:
    path = registry_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    apps = data.get("apps") if isinstance(data, dict) else None
    if not isinstance(apps, dict):
        return {}
    out: dict[str, RegistryEntry] = {}
    for name, raw in apps.items():
        if not isinstance(raw, dict):
            continue
        out[str(name)] = RegistryEntry(
            name=str(name),
            config_path=str(raw.get("config_path") or ""),
            host=str(raw.get("host") or ""),
            port=int(raw.get("port") or 0),
        )
    return out


def save_registry(entries: dict[str, RegistryEntry]) -> Path:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "apps": {name: asdict(entry) for name, entry in sorted(entries.items())}
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def register_app(name: str, config_path: Path, host: str, port: int) -> RegistryEntry:
    entries = load_registry()
    entry = RegistryEntry(
        name=name,
        config_path=str(config_path.resolve()),
        host=host,
        port=port,
    )
    entries[name] = entry
    save_registry(entries)
    return entry


def unregister_app(name: str) -> bool:
    entries = load_registry()
    if name not in entries:
        return False
    del entries[name]
    save_registry(entries)
    return True
