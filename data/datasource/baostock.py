"""Baostock 数据源实现（免费数据源）。

组合 baostock 免费接口 + normalizer，对外输出标准格式。
是整个模块第二个数据源实现；换源时新增实现类即可，
storage / query / sync 零改动。

实现的接口契约见 data.datasource.interface.DataSource（鸭子类型，不继承）。

与 tushare 的差异：
- 无 1min 数据，最细粒度为 5min（frequency="5"）。
- 无 A 股辅助表（daily_basic/stock_st/suspend_d/stk_limit），
  supports_ashare_extras 返回 False。
- 免费使用，无需 token，仅需 login/logout。
"""
import logging
from typing import Optional

import baostock as bs
import pandas as pd

from data import normalizer

logger = logging.getLogger(__name__)

# baostock 分钟 K 线字段
_KLINE_FIELDS = "date,time,open,high,low,close,volume,amount"
# baostock 日 K 线字段（包含前收盘价）
_DAILY_FIELDS = "date,open,high,low,close,preclose,volume,amount"

_ADJUST_MAP = {
    "none": "3",   # 不复权
    "qfq": "1",    # 前复权
    "hfq": "2",    # 后复权
}


def _to_baostock_code(ts_code: str) -> str:
    """将统一 ts_code（600000.SH）转为 baostock 格式（sh.600000）。"""
    parts = ts_code.split(".")
    if len(parts) != 2:
        return ts_code
    num, market = parts
    market_lower = market.lower()
    if market_lower == "sh":
        return f"sh.{num}"
    elif market_lower == "sz":
        return f"sz.{num}"
    elif market_lower == "bj":
        return f"bj.{num}"
    return ts_code


class BaostockSource:
    """Baostock 免费数据源，实现 DataSource 契约。"""

    name = "baostock"

    def __init__(self, user_id: str = "anonymous", password: str = "123456") -> None:
        """注入 baostock 登录凭据（默认匿名即可）。"""
        self._user_id = user_id
        self._password = password
        self._ensure_login()

    def _ensure_login(self) -> None:
        """确保 baostock 已登录。"""
        lg = bs.login(self._user_id, self._password)
        if lg.error_code != "0":
            raise RuntimeError(f"Baostock login failed: {lg.error_msg}")

    # ---- 核心行情 ----

    def fetch_minute(self, ts_code: str, start: str, end: str, freq: str = "5min") -> pd.DataFrame:
        """通过 baostock query_history_k_data_plus 拉分钟线。

        注意：baostock 不提供 1min，最细粒度 5min。
        freq 支持：5min/15min/30min/60min。
        数据已归一化为标准格式（trade_time 北京整分钟右闭）。
        """
        bs_code = _to_baostock_code(ts_code)
        # baostock 日期格式 YYYY-MM-DD
        start_date = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        end_date = f"{end[:4]}-{end[4:6]}-{end[6:8]}"
        freq_map = {"5min": "5", "15min": "15", "30min": "30", "60min": "60"}
        bs_freq = freq_map.get(freq, "5")
        rs = bs.query_history_k_data_plus(bs_code, _KLINE_FIELDS,
                                           start_date=start_date, end_date=end_date,
                                           frequency=bs_freq, adjustflag="3")
        if rs.error_code != "0":
            return pd.DataFrame()
        df = rs.get_data()
        if df is None or df.empty:
            return pd.DataFrame()
        df["ts_code"] = ts_code
        return normalizer.normalize_minute_df(df, "baostock")

    def fetch_daily(self, ts_code: str, start: str, end: str) -> pd.DataFrame:
        """通过 baostock query_history_k_data_plus 拉日线。

        包含 preclose 字段，归一化为 pre_close；自动计算 change/pct_chg。
        """
        bs_code = _to_baostock_code(ts_code)
        start_date = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        end_date = f"{end[:4]}-{end[4:6]}-{end[6:8]}"
        rs = bs.query_history_k_data_plus(bs_code, _DAILY_FIELDS,
                                           start_date=start_date, end_date=end_date,
                                           frequency="d", adjustflag="3")
        if rs.error_code != "0":
            return pd.DataFrame()
        df = rs.get_data()
        if df is None or df.empty:
            return pd.DataFrame()
        df["ts_code"] = ts_code
        return normalizer.normalize_daily_df(df, "baostock")

    def fetch_basic(self, sec_type: str = "stock") -> pd.DataFrame:
        """通过 baostock query_stock_basic 拉标的信息。

        type=1 为股票，status=1 为上市中。
        返回 ts_code/name/code/ipoDate/outDate/type/status。
        """
        rs = bs.query_stock_basic()
        if rs.error_code != "0":
            return pd.DataFrame()
        df = rs.get_data()
        if df is None or df.empty:
            return pd.DataFrame()
        df["ts_code"] = df["code"].apply(lambda c: normalizer.map_ts_code(c, "baostock"))
        df["name"] = df["code_name"]
        if sec_type == "stock":
            # type=1 股票, status=1 上市中
            stk = df[df["type"] == "1"].copy()
            stk = stk[stk["status"] == "1"]
            return stk[["ts_code", "name", "code", "ipoDate", "outDate", "type", "status"]]
        return df[["ts_code", "name", "code", "ipoDate", "outDate", "type", "status"]]

    def fetch_trade_cal(self, exchange: str, start: str, end: str) -> pd.DataFrame:
        """通过 baostock query_trade_dates 获取交易日历。"""
        start_date = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        end_date = f"{end[:4]}-{end[4:6]}-{end[6:8]}"
        rs = bs.query_trade_dates(start_date=start_date, end_date=end_date)
        if rs.error_code != "0":
            return pd.DataFrame()
        df = rs.get_data()
        if df is None or df.empty:
            return pd.DataFrame()
        df["exchange"] = exchange
        df.rename(columns={"calendar_date": "cal_date", "is_trading_day": "is_open"}, inplace=True)
        df["cal_date"] = pd.to_datetime(df["cal_date"]).dt.strftime("%Y%m%d")
        df["is_open"] = df["is_open"].astype(int)
        df["pretrade_date"] = ""
        return df[["exchange", "cal_date", "is_open", "pretrade_date"]]

    def supports_ashare_extras(self) -> bool:
        """False：baostock 不支持 A 股辅助表。"""
        return False

    # ---- A 股特有辅助表（均不支持） ----

    def fetch_adj_factor(self, ts_code: str, start: str, end: str) -> pd.DataFrame:
        return pd.DataFrame()

    def fetch_daily_basic(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame()

    def fetch_stock_st(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame()

    def fetch_suspend_d(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame()

    def fetch_stk_limit(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame()
