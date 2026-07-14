from pathlib import Path
from typing import Any, Dict

import yaml

_CFG_PATH = Path(__file__).parent / "config.yaml"


def _load() -> Dict[str, Any]:
    with open(_CFG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml顶层须为映射")
    return data


_cfg: Dict[str, Any] = _load()


def cfg() -> Dict[str, Any]:
    return dict(_cfg)


def get(key: str, default: Any = None) -> Any:
    cur: Any = _cfg
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def reload(overrides: Dict[str, Any]) -> None:
    global _cfg
    _cfg = dict(overrides)


def module_dir() -> Path:
    return Path(__file__).parent
