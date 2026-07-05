"""数据模块配置（模块单例）。

按 AGENTS.md §6 模块模式 + 高内聚低耦合四条自检：配置文件位置属模块
内部知识，本模块用 __file__ 自定位同层 config.yaml，import 时读取并缓存；
其他模块（provider / meta_store / sync_runner）经 `get` / `cfg` 取值，
不感知配置文件名与路径，也不依赖 cwd。override 走 `reload(dict)`，
不在任何公共入口塞 config 参数。

模块加载即就绪（Module as Singleton）：import 本模块即读配置，配置格式错
则 import fail-fast；构造数据源等需要 token 的重副作用仍在各模块惰性触发。
"""
from pathlib import Path
from typing import Any, Dict

import yaml

_CFG_PATH = Path(__file__).parent / "config.yaml"


def _load() -> Dict[str, Any]:
    with open(_CFG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml 顶层须为映射")
    return data


# 模块级状态：import 时即加载
_cfg: Dict[str, Any] = _load()


def cfg() -> Dict[str, Any]:
    """返回完整配置（浅拷贝）。"""
    return dict(_cfg)


def get(key: str, default: Any = None) -> Any:
    """取配置值，支持点号路径，如 `get("data.tushare_token")`。"""
    cur: Any = _cfg
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def reload(overrides: Dict[str, Any]) -> None:
    """用 overrides 整体替换配置（测试 override 用）。"""
    global _cfg
    _cfg = dict(overrides)


def module_dir() -> Path:
    """返回本模块所在目录（data/），供其他模块把相对配置路径相对此解析，
    不依赖 cwd。"""
    return Path(__file__).parent
