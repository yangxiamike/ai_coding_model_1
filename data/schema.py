"""数据模块标准字段与常量定义。

所有数据源归一化后统一使用此处的字段名与常量；storage/query 层只认这些定义，
不感知具体数据源（tushare / binance）。换源时差异在 normalizer 层吸收，此处不变。
"""
from typing import List

# ===== 行情频率 =====
# 分钟线为最细粒度，5/15/30/60min 由 1min 聚合得到，不单独落库。
FREQ_MIN1 = "1min"   # 1 分钟线（最细粒度，落库）
FREQ_MIN60 = "60min" # 小时线（由 1min 聚合，不单独落库）
FREQ_DAY = "day"     # 日线（天线）

# ===== 复权类型 =====
ADJ_NONE = "none"    # 不复权
ADJ_QFQ = "qfq"      # 前复权
ADJ_HFQ = "hfq"      # 后复权

# ===== 标的类别（sec_type） =====
SEC_STOCK = "stock"    # A 股普通股
SEC_ETF = "etf"        # ETF / LOF / 基金
SEC_CB = "cb"          # 可转债
SEC_CRYPTO = "crypto"  # 加密货币（预留）

# ===== 标准行情列 =====
# 分钟线时间列：trade_time（北京时间整分钟，右闭语义，形如 2024-01-02 09:31:00）
# 日线时间列：trade_date（YYYYMMDD 字符串）
MINUTE_COLS: List[str] = [
    "ts_code", "trade_time",
    "open", "high", "low", "close", "vol", "amount",
]
DAILY_COLS: List[str] = [
    "ts_code", "trade_date",
    "open", "high", "low", "close", "pre_close",
    "change", "pct_chg", "vol", "amount",
]

# ===== 基础信息与 A 股特有辅助表 =====
# 这些表为日级横截面数据，用于标的可买性筛选与特征；加密货币源不提供。
BASIC_COLS: List[str] = [
    "ts_code", "symbol", "name", "area", "industry",
    "market", "exchange", "list_status", "list_date", "delist_date", "is_hs",
]
ADJ_FACTOR_COLS: List[str] = ["ts_code", "trade_date", "adj_factor"]
DAILY_BASIC_COLS: List[str] = [
    "ts_code", "trade_date",
    "turnover_rate", "pe", "pe_ttm", "pb", "ps", "ps_ttm",
    "dv_ratio", "dv_ttm", "total_share", "float_share", "free_share",
    "total_mv", "circ_mv",
]
STOCK_ST_COLS: List[str] = ["ts_code", "name", "trade_date", "type", "type_name"]
SUSPEND_D_COLS: List[str] = ["ts_code", "trade_date", "suspend_timing", "suspend_type"]
STK_LIMIT_COLS: List[str] = ["trade_date", "ts_code", "pre_close", "up_limit", "down_limit"]
TRADE_CAL_COLS: List[str] = ["exchange", "cal_date", "is_open", "pretrade_date"]
