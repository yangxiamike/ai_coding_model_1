"""zer0share 日频数据包的稳定字段契约。"""
from typing import Dict, List

SCHEMA_VERSION = "1.0.0"
MANIFEST_VERSION = 1
BUILDER_VERSION = "1.0.0"
BSE_START_DATE = "20211115"

TABLES = (
    "stock_basic",
    "trade_cal",
    "daily",
    "adj_factor",
    "daily_basic",
    "stock_st",
    "suspend_d",
    "stk_limit",
)

DEFAULT_FIELDS: Dict[str, List[str]] = {
    "stock_basic": [
        "ts_code", "symbol", "name", "area", "industry", "market",
        "exchange", "list_status", "list_date", "delist_date", "is_hs",
    ],
    "trade_cal": ["exchange", "cal_date", "is_open", "pretrade_date"],
    "daily": [
        "ts_code", "trade_date", "open", "high", "low", "close",
        "pre_close", "change", "pct_chg", "vol", "amount",
    ],
    "adj_factor": ["ts_code", "trade_date", "adj_factor"],
    "daily_basic": [
        "ts_code", "trade_date", "turnover_rate", "turnover_rate_f",
        "volume_ratio", "pe", "pe_ttm", "pb", "ps", "ps_ttm",
        "dv_ratio", "dv_ttm", "total_share", "float_share", "free_share",
        "total_mv", "circ_mv",
    ],
    "stock_st": ["ts_code", "trade_date", "name", "type", "type_name"],
    "suspend_d": [
        "ts_code", "trade_date", "suspend_timing", "suspend_type",
    ],
    "stk_limit": [
        "ts_code", "trade_date", "pre_close", "up_limit", "down_limit",
    ],
}

PRIMARY_KEYS: Dict[str, List[str]] = {
    "stock_basic": ["ts_code"],
    "trade_cal": ["exchange", "cal_date"],
    "daily": ["trade_date", "ts_code"],
    "adj_factor": ["trade_date", "ts_code"],
    "daily_basic": ["trade_date", "ts_code"],
    "stock_st": ["trade_date", "ts_code"],
    "suspend_d": ["trade_date", "ts_code", "suspend_type", "suspend_timing"],
    "stk_limit": ["trade_date", "ts_code"],
    "universe_history": ["trade_date", "ts_code"],
    "daily_hfq": ["trade_date", "ts_code"],
    "training_view_hfq": ["trade_date", "ts_code"],
}

DATE_COLUMNS = {"trade_date", "cal_date", "pretrade_date", "list_date", "delist_date"}
INTEGER_COLUMNS = {"is_open"}
FLOAT_COLUMNS = {
    "open", "high", "low", "close", "pre_close", "change", "pct_chg",
    "vol", "amount", "adj_factor", "turnover_rate", "turnover_rate_f",
    "volume_ratio", "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ratio",
    "dv_ttm", "total_share", "float_share", "free_share", "total_mv",
    "circ_mv", "up_limit", "down_limit", "raw_up_limit", "raw_down_limit",
}

SOURCE_ALIASES: Dict[str, Dict[str, str]] = {}
SOURCE_FIELD_ALIASES: Dict[str, Dict[str, str]] = {}

PRICE_COLUMNS = ["open", "high", "low", "close", "pre_close"]
