"""数据公共入口。

zer0share 数据包入口保持轻量、离线可导入。旧 provider/sync_runner API 在首次
访问时才加载，避免 ``open_dataset`` 依赖旧 data/config.yaml 或外部数据源。
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

_PACKAGE_EXPORT_VALUES = {
    "DatasetPackage": DatasetPackage,
    "DatasetSpec": DatasetSpec,
    "build_dataset": build_dataset,
    "build_standard_dataset": build_standard_dataset,
    "load_spec": load_spec,
    "open_dataset": open_dataset,
    "standard_daily_spec": standard_daily_spec,
    "STANDARD_DAILY_PRESET_NAME": STANDARD_DAILY_PRESET_NAME,
    "STANDARD_DAILY_PRESET_VERSION": STANDARD_DAILY_PRESET_VERSION,
}
_PACKAGE_EXPORTS = set(_PACKAGE_EXPORT_VALUES)

_LEGACY_EXPORTS = {
    "close",
    "minute", "hour", "daily", "latest_bar",
    "daily_basic", "adj_factor", "stk_limit", "stock_st", "suspend_d",
    "trade_cal", "stock_list", "is_trading_day", "export",
    "sync_all", "sync_minute", "sync_daily", "sync_daily_basic",
    "sync_adj_factor", "sync_stk_limit", "sync_stock_st",
    "sync_suspend_d", "sync_trade_cal", "sync_stock_list",
    "DataSource", "AShareDataSource", "StandardBar",
    "TradingCalendar", "AlwaysOpenCalendar",
    "FREQ_MIN1", "FREQ_MIN60", "FREQ_DAY",
    "ADJ_NONE", "ADJ_QFQ", "ADJ_HFQ",
    "SEC_STOCK", "SEC_ETF", "SEC_CB", "SEC_CRYPTO",
}

__all__ = sorted(_PACKAGE_EXPORTS | _LEGACY_EXPORTS | {"provider", "sync_runner"})


def __getattr__(name):
    if name in {"provider", "sync_runner"}:
        module = importlib.import_module(f"data.{name}")
        globals()[name] = module
        return module
    if name in _LEGACY_EXPORTS:
        module = importlib.import_module("data.data_cli")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'data' has no attribute {name!r}")
