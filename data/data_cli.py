"""数据模块统一公共入口。

数据包 API 轻量加载；旧 provider/sync_runner、数据源与日历符号按首次访问
惰性导入。因此只读 ``open_dataset`` 不依赖旧 config 或外部行情源。
"""
import importlib

from data.dataset_package import (
    DatasetPackage as DatasetPackage,
    DatasetSpec as DatasetSpec,
    STANDARD_DAILY_PRESET_NAME as STANDARD_DAILY_PRESET_NAME,
    STANDARD_DAILY_PRESET_VERSION as STANDARD_DAILY_PRESET_VERSION,
    build_dataset as build_dataset,
    build_standard_dataset as build_standard_dataset,
    load_spec as load_spec,
    open_dataset as open_dataset,
    standard_daily_spec as standard_daily_spec,
)

_PROVIDER_NAMES = {
    "close", "minute", "hour", "daily", "latest_bar", "daily_basic",
    "adj_factor", "stk_limit", "stock_st", "suspend_d", "trade_cal",
    "stock_list", "is_trading_day", "export",
}
_SYNC_NAMES = {
    "sync_all": "all",
    "sync_minute": "minute",
    "sync_daily": "daily",
    "sync_daily_basic": "daily_basic",
    "sync_adj_factor": "adj_factor",
    "sync_stk_limit": "stk_limit",
    "sync_stock_st": "stock_st",
    "sync_suspend_d": "suspend_d",
    "sync_trade_cal": "trade_cal",
    "sync_stock_list": "stock_list",
}
_INTERFACE_NAMES = {"DataSource", "AShareDataSource", "StandardBar"}
_CALENDAR_NAMES = {"TradingCalendar", "AlwaysOpenCalendar"}
_SCHEMA_NAMES = {
    "FREQ_MIN1", "FREQ_MIN60", "FREQ_DAY",
    "ADJ_NONE", "ADJ_QFQ", "ADJ_HFQ",
    "SEC_STOCK", "SEC_ETF", "SEC_CB", "SEC_CRYPTO",
}
_PACKAGE_VALUES = {
    "DatasetPackage": DatasetPackage,
    "DatasetSpec": DatasetSpec,
    "STANDARD_DAILY_PRESET_NAME": STANDARD_DAILY_PRESET_NAME,
    "STANDARD_DAILY_PRESET_VERSION": STANDARD_DAILY_PRESET_VERSION,
    "build_dataset": build_dataset,
    "build_standard_dataset": build_standard_dataset,
    "load_spec": load_spec,
    "open_dataset": open_dataset,
    "standard_daily_spec": standard_daily_spec,
}
_PACKAGE_NAMES = set(_PACKAGE_VALUES)

__all__ = sorted(
    _PROVIDER_NAMES
    | set(_SYNC_NAMES)
    | _INTERFACE_NAMES
    | _CALENDAR_NAMES
    | _SCHEMA_NAMES
    | _PACKAGE_NAMES
    | {"provider", "sync_runner"}
)


def __getattr__(name):
    if name in {"provider", "sync_runner"}:
        value = importlib.import_module(f"data.{name}")
    elif name in _PROVIDER_NAMES:
        value = getattr(importlib.import_module("data.provider"), name)
    elif name in _SYNC_NAMES:
        value = getattr(importlib.import_module("data.sync_runner"), _SYNC_NAMES[name])
    elif name in _INTERFACE_NAMES:
        value = getattr(importlib.import_module("data.datasource.interface"), name)
    elif name in _CALENDAR_NAMES:
        value = getattr(importlib.import_module("data.calendar"), name)
    elif name in _SCHEMA_NAMES:
        value = getattr(importlib.import_module("data.schema"), name)
    else:
        raise AttributeError(f"module 'data.data_cli' has no attribute {name!r}")
    globals()[name] = value
    return value
