from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "default.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_CONFIG
    with config_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    config = deepcopy(config)
    base = config_path.resolve().parent.parent
    project = config["project"]
    for key in ("data_dir", "artifact_dir", "database_path"):
        value = Path(project[key])
        project[key] = str(value if value.is_absolute() else (base / value).resolve())
    return config

