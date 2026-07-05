"""数据源契约与标准格式定义。

DataSource 为鸭子类型契约（typing.Protocol），实现类无需继承。
任何实现下列方法的对象均可被 provider 模块作为数据源注入。
换源（如 tushare → binance）只需新增一个实现，storage / query 层零改动。

契约分两层：
- DataSource：核心方法，所有源必须（minute / daily / basic / trade_cal）。
- AShareDataSource：A 股特有辅助表（adj_factor / daily_basic / stock_st /
  suspend_d / stk_limit），仅 A 股源实现，BTC 源 supports_ashare_extras() 返回 False。
"""
import datetime as dt
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

import pandas as pd


@dataclass(frozen=True)
class StandardBar:
    """归一化后的单根标准 bar（契约示意，实际流通用 DataFrame）。"""
    ts_code: str
    datetime: dt.datetime  # 分钟线为北京时间整分钟(右闭)；日线为当日 00:00
    open: float
    high: float
    low: float
    close: float
    vol: float
    amount: Optional[float] = None


@runtime_checkable
class DataSource(Protocol):
    """数据源核心契约。实现类组合 normalizer 将原始数据转为标准格式输出。"""

    name: str

    def fetch_minute(self, ts_code: str, start: str, end: str, freq: str = "1min") -> pd.DataFrame:
        """拉取分钟 OHLCV，归一化为标准列
        (ts_code/trade_time/open/high/low/close/vol/amount)。

        trade_time 为北京时间整分钟、右闭语义。
        """
        pass

    def fetch_daily(self, ts_code: str, start: str, end: str) -> pd.DataFrame:
        """拉取日线 OHLCV，归一化为标准列
        (ts_code/trade_date/open/high/low/close/pre_close/change/pct_chg/vol/amount)。
        """
        pass

    def fetch_basic(self, sec_type: str = "stock") -> pd.DataFrame:
        """拉取标的清单（含 ts_code/name/list_date/delist_date 等）。"""
        pass

    def fetch_trade_cal(self, exchange: str, start: str, end: str) -> pd.DataFrame:
        """拉取交易日历。A 股源返回 trade_cal；BTC 源返回空（7×24 无休）。"""
        pass

    def supports_ashare_extras(self) -> bool:
        """是否支持 A 股特有辅助表。A 股源 True，BTC 源 False。"""
        pass


@runtime_checkable
class AShareDataSource(DataSource, Protocol):
    """A 股数据源契约，在 DataSource 基础上增加 A 股特有日级辅助表。"""

    def fetch_adj_factor(self, ts_code: str, start: str, end: str) -> pd.DataFrame:
        """复权因子（ts_code/trade_date/adj_factor）。"""
        pass

    def fetch_daily_basic(self, trade_date: str) -> pd.DataFrame:
        """每日指标（市值/估值等，日级横截面）。"""
        pass

    def fetch_stock_st(self, trade_date: str) -> pd.DataFrame:
        """当日 ST 股票列表。"""
        pass

    def fetch_suspend_d(self, trade_date: str) -> pd.DataFrame:
        """当日停复牌列表。"""
        pass

    def fetch_stk_limit(self, trade_date: str) -> pd.DataFrame:
        """当日涨跌停价。"""
        pass
