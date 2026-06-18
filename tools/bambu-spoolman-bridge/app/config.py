"""Configuration loading for the bridge.

Reads a YAML file (path from BRIDGE_CONFIG, default ./data/config.yaml) into a
plain dict. Kept deliberately simple — no schema validation yet (TODO).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = os.environ.get("BRIDGE_CONFIG", "data/config.yaml")
DEFAULT_DB_PATH = os.environ.get("BRIDGE_DB", "data/state.db")


def load_config(path: str | None = None) -> dict[str, Any]:
    cfg_path = Path(path or DEFAULT_CONFIG_PATH)
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Config not found at {cfg_path}. Copy config.example.yaml -> {cfg_path}."
        )
    with cfg_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
