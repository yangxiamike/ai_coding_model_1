"""Tushare 数据源实现（首个实现）。

组合 tushare pro_api + normalizer，对外输出标准格式。
是整个模块唯一感知 tushare 的地方；换源时新增一个实现类即可，
storage / query / sync 零改动。

实现的接口契约见 data.datasource.interface.AShareDataSource（鸭子类型，不继承）。
"""
import logging
import time
from typing import Optional

import pandas as pd
import tushare as ts

from data import normalizer

logger = logging.getLogger(__name__)


class TushareSource:
    """Tushare Pro 数据源，实现 AShareDataSource 契约。"""

    name = "tushare"

    def __init__(self, token: str, fetch_interval_sec: float = 0.2) -> None:
        """注入 tushare token 与接口限速间隔（秒）。

        内部持有 ts.pro_api(token) 句柄。
        """
        ts.set_token(token)
        self._pro = ts.pro_api()
        self._interval = fetch_interval_sec

    def _rate_limit(self) -> None:
        """tushare 接口限速：每次调用前休眠 fetch_interval_sec 秒。"""
        time.sleep(self._interval)

    # ---- 核心行情 ----

    def fetch_minute(self, ts_code: str, start: str, end: str, freq: str = "1min") -> pd.DataFrame:
        """通过 tushare stk_mins 拉分钟，经 normalizer 归一化为标准格式。"""
        self._rate_limit()
        try:
            df = self._pro.stk_mins(ts_code=ts_code, start_date=start, end_date=end, freq=freq)
        except Exception:
            return pd.DataFrame()
        if df.empty:
            return df
        df["ts_code"] = ts_code
        return normalizer.normalize_minute_df(df, "tushare")

    def fetch_daily(self, ts_code: str, start: str, end: str) -> pd.DataFrame:
        """通过 tushare daily 拉日线，经 normalizer 归一化为标准格式。"""
        self._rate_limit()
        try:
            df = self._pro.daily(ts_code=ts_code, start_date=start, end_date=end)
        except Exception:
            return pd.DataFrame()
        if df.empty:
            return df
        return normalizer.normalize_daily_df(df, "tushare")

    def fetch_basic(self, sec_type: str = "stock") -> pd.DataFrame:
        """按类别拉标的清单：stock→stock_basic；etf→fund_basic；cb→cb_basic。"""
        self._rate_limit()
        try:
            if sec_type == "stock":
                df = self._pro.stock_basic(exchange="", list_status="L",
                                            fields="ts_code,symbol,name,area,industry,market,exchange,list_status,list_date,delist_date,is_hs")
            elif sec_type == "etf":
                df = self._pro.fund_basic(market="E")
            elif sec_type == "cb":
                df = self._pro.cb_basic()
            else:
                return pd.DataFrame()
        except Exception:
            return pd.DataFrame()
        return df

    def fetch_trade_cal(self, exchange: str, start: str, end: str) -> pd.DataFrame:
        """tushare trade_cal（交易所交易日历）。"""
        self._rate_limit()
        try:
            df = self._pro.trade_cal(exchange=exchange, start_date=start, end_date=end)
            if not df.empty:
                df["exchange"] = exchange
        except Exception:
            return pd.DataFrame()
        return df

    def supports_ashare_extras(self) -> bool:
        """True。"""
        return True

    # ---- A 股特有辅助表 ----

    def fetch_adj_factor(self, ts_code: str, start: str, end: str) -> pd.DataFrame:
        """tushare adj_factor（复权因子）。"""
        self._rate_limit()
        try:
            df = self._pro.adj_factor(ts_code=ts_code, start_date=start, end_date=end)
        except Exception:
            return pd.DataFrame()
        return df

    def fetch_daily_basic(self, trade_date: str) -> pd.DataFrame:
        """tushare daily_basic（市值/估值等，日级横截面）。"""
        self._rate_limit()
        try:
            df = self._pro.daily_basic(trade_date=trade_date)
        except Exception:
            return pd.DataFrame()
        return df

    def fetch_stock_st(self, trade_date: str) -> pd.DataFrame:
        """tushare stock_st（当日 ST 列表）。"""
        self._rate_limit()
        try:
            df = self._pro.stock_st(trade_date=trade_date)
        except Exception:
            return pd.DataFrame()
        return df

    def fetch_suspend_d(self, trade_date: str) -> pd.DataFrame:
        """tushare suspend_d（当日停复牌）。"""
        self._rate_limit()
        try:
            df = self._pro.suspend_d(trade_date=trade_date)
        except Exception:
            return pd.DataFrame()
        return df

    def fetch_stk_limit(self, trade_date: str) -> pd.DataFrame:
        """tushare stk_limit（当日涨跌停价）。"""
        self._rate_limit()
        try:
            df = self._pro.stk_limit(trade_date=trade_date)
        except Exception:
            return pd.DataFrame()
        return df
