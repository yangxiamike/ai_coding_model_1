"""归一化工具：把各数据源原始数据转为标准格式。

所有源的差异（时区、时间戳语义、字段名、标的代码）在此层吸收，
storage / query 层只接触归一化后的标准格式。

时间规范：
- 统一北京时间（Asia/Shanghai, UTC+8）。
- bar 时间戳右闭整分钟：09:31:00 这根 bar 覆盖 (09:30:00, 09:31:00] 成交。
  tushare 1min 默认即此语义（零平移）；币安 klines 用 closeTime 对齐。
"""
import datetime as dt
from typing import Optional

import pandas as pd

from data.schema import (
    DAILY_COLS, MINUTE_COLS,
    ADJ_NONE, ADJ_QFQ, ADJ_HFQ,
)

# 字段名映射表：tushare 原始列名 → 标准列名
_TUSHARE_DAILY_MAP = {
    "ts_code": "ts_code", "trade_date": "trade_date",
    "open": "open", "high": "high", "low": "low", "close": "close",
    "pre_close": "pre_close", "change": "change", "pct_chg": "pct_chg",
    "vol": "vol", "amount": "amount",
}
_TUSHARE_MINUTE_MAP = {
    "ts_code": "ts_code", "trade_time": "trade_time",
    "open": "open", "high": "high", "low": "low", "close": "close",
    "vol": "vol", "amount": "amount",
}

# 字段名映射表：baostock 原始列名 → 标准列名
_BAOSTOCK_DAILY_MAP = {
    "date": "trade_date",
    "open": "open", "high": "high", "low": "low", "close": "close",
    "preclose": "pre_close",
    "volume": "vol", "amount": "amount",
}
_BAOSTOCK_MINUTE_MAP = {
    "date": "trade_date",
    "time": "trade_time",
    "open": "open", "high": "high", "low": "low", "close": "close",
    "volume": "vol", "amount": "amount",
}

TZ_BJ = dt.timezone(dt.timedelta(hours=8))

# baostock 交易所后缀映射：sh→SH, sz→SZ, bj→BJ
_BAO_CODE_PREFIX = {"sh": "SH", "sz": "SZ", "bj": "BJ"}


def to_beijing(when: dt.datetime) -> dt.datetime:
    """将任意时区 datetime 转为北京时间（Asia/Shanghai, UTC+8）。"""
    if when.tzinfo is None:
        return when.replace(tzinfo=TZ_BJ)
    return when.astimezone(TZ_BJ).replace(tzinfo=None)


def align_right_close(raw_time: dt.datetime) -> dt.datetime:
    """将 bar 时间戳对齐到右闭整分钟（截断秒/微秒为 00）。"""
    return raw_time.replace(second=0, microsecond=0)


def map_ts_code(raw_code: str, source: str) -> str:
    """将源原始代码映射为统一 ts_code。

    A 股：000001.SZ / 600000.SH。
    tushare 已是标准格式；baostock 的 sh.600000 → 600000.SH。
    """
    if source == "tushare":
        return raw_code
    if source == "baostock":
        parts = raw_code.split(".")
        if len(parts) == 2:
            market, num = parts
            suffix = _BAO_CODE_PREFIX.get(market, market.upper())
            return f"{num}.{suffix}"
    return raw_code


def _convert_numeric(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """将指定列转为数值类型（baostock 返回字符串，需转换）。"""
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _parse_baostock_time(time_val) -> dt.datetime:
    """解析 baostock 的时间格式：20240102093500000 → datetime。"""
    s = str(time_val)
    if len(s) >= 17:
        return dt.datetime.strptime(s[:14], "%Y%m%d%H%M%S")
    return pd.NaT


def normalize_minute_df(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """把源原始分钟 df 归一化为标准列。

    输出列：ts_code/trade_time/open/high/low/close/vol/amount，
    与 schema.MINUTE_COLS 对齐。trade_time 转北京时间整分钟右闭。
    """
    if source == "tushare":
        rename_map = {k: v for k, v in _TUSHARE_MINUTE_MAP.items() if k in df.columns}
        df = df.rename(columns=rename_map)
        if "trade_time" in df.columns:
            df["trade_time"] = pd.to_datetime(df["trade_time"])
    elif source == "baostock":
        rename_map = {k: v for k, v in _BAOSTOCK_MINUTE_MAP.items() if k in df.columns}
        df = df.rename(columns=rename_map)
        if "trade_time" in df.columns:
            # baostock 时间格式 20240102093500000 → datetime
            df["trade_time"] = df["trade_time"].apply(_parse_baostock_time)
        if "ts_code" not in df.columns:
            df["ts_code"] = ""
    _convert_numeric(df, ["open", "high", "low", "close", "vol", "amount"])
    out_cols = [c for c in MINUTE_COLS if c in df.columns]
    return df[out_cols]


def normalize_daily_df(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """把源原始日线 df 归一化为标准列，与 schema.DAILY_COLS 对齐。

    自动计算 change（涨跌额）和 pct_chg（涨跌幅%），若源不提供。
    """
    if source == "tushare":
        rename_map = {k: v for k, v in _TUSHARE_DAILY_MAP.items() if k in df.columns}
        df = df.rename(columns=rename_map)
        if "trade_date" in df.columns:
            df["trade_date"] = df["trade_date"].astype(str)
    elif source == "baostock":
        rename_map = {k: v for k, v in _BAOSTOCK_DAILY_MAP.items() if k in df.columns}
        df = df.rename(columns=rename_map)
        if "trade_date" in df.columns:
            # baostock 日期 YYYY-MM-DD → YYYYMMDD
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")
        if "ts_code" not in df.columns:
            df["ts_code"] = ""
    _convert_numeric(df, ["open", "high", "low", "close", "vol", "amount",
                          "pre_close", "change", "pct_chg"])
    # 若源未提供 change/pct_chg，用 close - pre_close 计算
    if "close" in df.columns and "pre_close" in df.columns:
        if "change" not in df.columns:
            df["change"] = df["close"] - df["pre_close"]
        if "pct_chg" not in df.columns:
            df["pct_chg"] = (df["close"] / df["pre_close"] - 1) * 100
    out_cols = [c for c in DAILY_COLS if c in df.columns]
    return df[out_cols]


def apply_adjust(df: pd.DataFrame, adj: pd.DataFrame, kind: str) -> pd.DataFrame:
    """对行情 df 按复权因子做复权，返回复权后 df。

    复权在查询层完成，不污染原始落库。
    - none：不调整
    - qfq：前复权，价格 × 当日 adj_factor
    - hfq：后复权，价格 × (adj_factor / 首个 adj_factor)
    """
    if kind == ADJ_NONE:
        return df
    if adj.empty:
        return df
    price_cols = ["open", "high", "low", "close"]
    if kind == ADJ_QFQ:
        df = df.merge(adj, on=["ts_code", "trade_date"], how="left")
        for col in price_cols:
            df[col] = df[col] * df["adj_factor"]
        df = df.drop(columns=["adj_factor"], errors="ignore")
    elif kind == ADJ_HFQ:
        # 后复权：因子统一除以首个因子，得到相对首日的倍数
        first_adj = adj.groupby("ts_code")["adj_factor"].transform("first")
        adj = adj.copy()
        adj["adj_factor"] = adj["adj_factor"] / first_adj
        df = df.merge(adj, on=["ts_code", "trade_date"], how="left")
        for col in price_cols:
            df[col] = df[col] * df["adj_factor"]
        df = df.drop(columns=["adj_factor"], errors="ignore")
    return df


def aggregate_bars(minute_df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """把 1min df 聚合为 N 分钟 OHLCV。

    open=首 / close=末 / high=max / low=min / vol/amount=sum；
    按 freq 重采样，bar 时间戳右闭整分钟。
    仅在查询层使用，不落库。
    """
    if minute_df.empty:
        return minute_df
    df = minute_df.copy()
    df.set_index("trade_time", inplace=True)
    ohlc_dict = {
        "open": "first", "high": "max", "low": "min", "close": "last",
        "vol": "sum", "amount": "sum",
    }
    resample_rule = {"1min": "1T", "5min": "5T", "15min": "15T",
                     "30min": "30T", "60min": "60T"}.get(freq, freq)
    # 多标的同时分组聚合：按 ts_code + 时间窗口
    group_keys = [pd.Grouper(freq=resample_rule)]
    if "ts_code" in df.columns:
        group_keys.insert(0, df["ts_code"])
    grouped = df.groupby(group_keys)
    result = grouped.agg(ohlc_dict).dropna(how="all")
    result.reset_index(inplace=True)
    if "ts_code" in df.columns and "ts_code" not in result.columns:
        result["ts_code"] = df["ts_code"].iloc[0]
    return result
