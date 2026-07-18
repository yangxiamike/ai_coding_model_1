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


def get_declare(ts_code: str = None) -> Dict[str, Any]:
    declare = dict(_cfg.get("declare", {}))
    bars = declare.get("bars", [])
    if ts_code:
        for bar in bars:
            bar["ts_code"] = ts_code
    return declare
