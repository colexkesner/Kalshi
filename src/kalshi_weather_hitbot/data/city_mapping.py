from __future__ import annotations

from pathlib import Path

import yaml


def load_city_mapping(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}
