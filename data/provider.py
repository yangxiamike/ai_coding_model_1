"""数据模块查询门面（按需回源 + 本地缓存，对上层无感）。

对上层（training / backtest / live_predict）只暴露"要数据"语义：调用方说
标的 / 区间 / 频率 / 字段，provider 返回 df，全程无感本地缓存 / 回源 / 落库 /
同步。缺数据 provider 内部自动回源补齐（调 sync_jobs.run_table），命中直读
本地 Parquet 不回源。复权与小时线聚合在查询层内存拼，不污染落库。

无 sync / refresh / status / last_sync / coverage 对外入口（违反"上层无感"
契约）。显式同步预热走独立面 sync_runner，与本门面解耦。

无状态门面：运行时状态（source / calendar / tasks / table_paths）由
sync_jobs 模块单例持有，本模块经 sync_jobs 取用。模块加载即就绪，无 init。

用法：
    from data import provider
    provider.daily(["600000.SH"], "20240101", "20240601")
"""
import datetime as dt
from typing import List, Optional

import pandas as pd

from data import meta_store, normalizer, query_engine, snapshot_store, sync_jobs
from data.schema import (
    ADJ_FACTOR_COLS, ADJ_NONE, ADJ_QFQ,
    DAILY_COLS, MINUTE_COLS,
    FREQ_DAY, FREQ_MIN1, FREQ_MIN60,
)


# ===== 行情 =====

def minute(codes: List[str], start: str, end: str, adjust: str = ADJ_QFQ) -> pd.DataFrame:
    """分钟 OHLCV（北京时间整分钟右闭）。本地缺自动回源补齐，复权在查询层拼。"""
    sync_jobs.run_table("minute_kline", codes, start, end)
    path = sync_jobs.get_table_path("minute_kline")
    df = query_engine.select(path, MINUTE_COLS, ts_codes=codes,
                             start=start, end=end,
                             date_column="date", order_by="ts_code, trade_time")
    if adjust != ADJ_NONE and not df.empty:
        df = normalizer.apply_adjust(df, adj_factor(codes, start, end), adjust)
    return df


def hour(codes: List[str], start: str, end: str, adjust: str = ADJ_QFQ) -> pd.DataFrame:
    """小时线 OHLCV（60min），由 1min 聚合得到，不单独落库。

    所需 1min 缺则自动回源补齐；复权在聚合前拼（价格调整后再重采样）。
    """
    m = minute(codes, start, end, adjust=ADJ_NONE)
    if adjust != ADJ_NONE and not m.empty:
        m = normalizer.apply_adjust(m, adj_factor(codes, start, end), adjust)
    return normalizer.aggregate_bars(m, FREQ_MIN60)


def daily(codes: List[str], start: str, end: str, adjust: str = ADJ_QFQ) -> pd.DataFrame:
    """日线 OHLCV。本地缺自动回源补齐，复权在查询层拼。"""
    sync_jobs.run_table("daily_kline", codes, start, end)
    path = sync_jobs.get_table_path("daily_kline")
    df = query_engine.select(path, DAILY_COLS, ts_codes=codes,
                             start=start, end=end,
                             date_column="date", order_by="ts_code, trade_date")
    if adjust != ADJ_NONE and not df.empty:
        df = normalizer.apply_adjust(df, adj_factor(codes, start, end), adjust)
    return df


def latest_bar(codes: List[str], freq: str = FREQ_MIN1) -> pd.DataFrame:
    """最新可得 bar。补近若干日 → 读本地 → 取每标的最新一根。"""
    cal = sync_jobs.get_calendar()
    today = cal.today()
    start = _shift_days(today, 10)
    if freq == FREQ_MIN1:
        sync_jobs.run_table("minute_kline", codes, start, today)
        path = sync_jobs.get_table_path("minute_kline")
        df = query_engine.select(path, MINUTE_COLS, ts_codes=codes,
                                 date_column="date", order_by="ts_code, trade_time")
    else:
        sync_jobs.run_table("daily_kline", codes, start, today)
        path = sync_jobs.get_table_path("daily_kline")
        df = query_engine.select(path, DAILY_COLS, ts_codes=codes,
                                 date_column="date", order_by="ts_code, trade_date")
    if df.empty:
        return df
    return df.groupby("ts_code", as_index=False).tail(1)


# ===== A 股日级辅助表 =====

def daily_basic(codes: Optional[List[str]], start: str, end: str) -> pd.DataFrame:
    """每日指标（市值/估值/换手等，日级横截面）。本地缺自动回源补齐。"""
    sync_jobs.run_table("daily_basic", None, start, end)
    path = sync_jobs.get_table_path("daily_basic")
    df = query_engine.select(path, _DAILY_BASIC_COLS(), ts_codes=codes,
                             start=start, end=end, date_column="date",
                             order_by="ts_code, trade_date")
    return df


def adj_factor(codes: List[str], start: str, end: str) -> pd.DataFrame:
    """复权因子。本地缺自动回源补齐。"""
    sync_jobs.run_table("adj_factor", codes, start, end)
    path = sync_jobs.get_table_path("adj_factor")
    return query_engine.select(path, ADJ_FACTOR_COLS, ts_codes=codes,
                               start=start, end=end,
                               date_column="date", order_by="ts_code, trade_date")


def stk_limit(date: str) -> pd.DataFrame:
    """当日涨跌停价。本地缺自动回源补齐。"""
    sync_jobs.run_table("stk_limit", None, date, date)
    path = sync_jobs.get_table_path("stk_limit")
    return query_engine.select(path, _STK_LIMIT_COLS(), start=date, end=date,
                               date_column="date", order_by="ts_code")


def stock_st(date: str) -> pd.DataFrame:
    """当日 ST 列表。本地缺自动回源补齐。"""
    sync_jobs.run_table("stock_st", None, date, date)
    path = sync_jobs.get_table_path("stock_st")
    return query_engine.select(path, _STOCK_ST_COLS(), start=date, end=date,
                               date_column="date", order_by="ts_code")


def suspend_d(date: str) -> pd.DataFrame:
    """当日停复牌。本地缺自动回源补齐。"""
    sync_jobs.run_table("suspend_d", None, date, date)
    path = sync_jobs.get_table_path("suspend_d")
    return query_engine.select(path, _SUSPEND_D_COLS(), start=date, end=date,
                               date_column="date", order_by="ts_code")


# ===== 元信息 =====

def trade_cal(start: str, end: str, exchange: str = "SSE") -> pd.DataFrame:
    """交易日历。本地 DuckDB 缺则 _ensure_ready 阶段已自动回源补齐。"""
    sync_jobs._ensure_ready()
    days = meta_store.get_trading_days(exchange, start, end)
    return pd.DataFrame({"exchange": exchange, "cal_date": days, "is_open": 1})


def stock_list(sec_type: Optional[str] = None) -> pd.DataFrame:
    """可买标的清单。本地无快照则回源拉取；有则直读（不强制刷新，刷新走 sync）。"""
    sync_jobs._ensure_ready()
    path = sync_jobs.get_table_path("basic")
    if not snapshot_store.exists(path):
        sync_jobs.run_table("basic", None, "", "")
    df = snapshot_store.read(path)
    if sec_type and not df.empty and "sec_type" in df.columns:
        df = df[df["sec_type"] == sec_type]
    return df


def is_trading_day(date: str, exchange: str = "SSE") -> bool:
    """是否交易日。本地 trade_cal 缺则 _ensure_ready 阶段已自动回源补齐。"""
    sync_jobs._ensure_ready()
    return meta_store.is_trading_day(exchange, date)


# ===== 训练导出（training 唯一交接点） =====

def export(codes: List[str], start: str, end: str, freq: str = FREQ_DAY,
           fields: Optional[List[str]] = None, adjust: str = ADJ_QFQ) -> pd.DataFrame:
    """导出干净面板 df，列对齐模型输入。freq 取 FREQ_MIN1 / FREQ_MIN60 / FREQ_DAY。"""
    if freq == FREQ_DAY:
        df = daily(codes, start, end, adjust)
    elif freq == FREQ_MIN1:
        df = minute(codes, start, end, adjust)
    elif freq == FREQ_MIN60:
        df = hour(codes, start, end, adjust)
    else:
        raise ValueError(f"unsupported freq: {freq}")
    if fields and not df.empty:
        df = df[[c for c in fields if c in df.columns]]
    return df


# ===== 生命周期 =====

def close() -> None:
    """释放底层连接并重置就绪状态以便重新惰性组装。"""
    sync_jobs.close()
    meta_store.close()


# ===== 内部辅助 =====

def _shift_days(date_str: str, n: int) -> str:
    d = dt.datetime.strptime(date_str, "%Y%m%d")
    return (d - dt.timedelta(days=n)).strftime("%Y%m%d")


def _DAILY_BASIC_COLS() -> List[str]:
    from data.schema import DAILY_BASIC_COLS
    return DAILY_BASIC_COLS


def _STK_LIMIT_COLS() -> List[str]:
    from data.schema import STK_LIMIT_COLS
    return STK_LIMIT_COLS


def _STOCK_ST_COLS() -> List[str]:
    from data.schema import STOCK_ST_COLS
    return STOCK_ST_COLS


def _SUSPEND_D_COLS() -> List[str]:
    from data.schema import SUSPEND_D_COLS
    return SUSPEND_D_COLS
