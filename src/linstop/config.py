from __future__ import annotations

import json
import os
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from .models import LinStopConfig, PortConfig, StationProfile


def default_config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "linstop" / "config.json"


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()

    def load(self) -> LinStopConfig:
        if not self.path.exists():
            config = LinStopConfig()
            config.ensure_defaults()
            return config
        data = json.loads(self.path.read_text(encoding="utf-8"))
        config = LinStopConfig(
            station=_dataclass_from_dict(StationProfile, data.get("station", {})),
            ports=[_dataclass_from_dict(PortConfig, item) for item in data.get("ports", [])],
            active_port=data.get("active_port", ""),
        )
        config.ensure_defaults()
        return config

    def save(self, config: LinStopConfig) -> None:
        config.ensure_defaults()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _dataclass_from_dict(cls, data: dict[str, Any]):
    names = {field.name for field in fields(cls)}
    return cls(**{key: value for key, value in data.items() if key in names})