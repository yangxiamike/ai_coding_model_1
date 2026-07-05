"""Binance 数据源（预留，未实现）。

后续若做加密货币，实现 data.datasource.interface.DataSource 契约：
- fetch_minute / fetch_daily 通过币安 klines API，用 closeTime 对齐右闭、
  转北京时间整分钟。
- fetch_basic 返回交易对清单；fetch_trade_cal 返回空（7×24 无休）。
- supports_ashare_extras 返回 False（无 ST/停牌/涨跌停/复权因子）。
"""
from typing import Optional

import pandas as pd


class BinanceSource:
    """币安数据源（预留）。"""

    name = "binance"

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None) -> None:
        """注入币安 API 凭据（公开行情可空）。"""
        pass

    def fetch_minute(self, ts_code: str, start: str, end: str, freq: str = "1min") -> pd.DataFrame:
        """币安 klines 拉分钟，归一化为标准格式（closeTime 右闭对齐北京时间）。"""
        pass

    def fetch_daily(self, ts_code: str, start: str, end: str) -> pd.DataFrame:
        """币安 klines 拉日线，归一化为标准格式。"""
        pass

    def fetch_basic(self, sec_type: str = "crypto") -> pd.DataFrame:
        """返回交易对清单（ts_code=BTCUSDT 等）。"""
        pass

    def fetch_trade_cal(self, exchange: str, start: str, end: str) -> pd.DataFrame:
        """BTC 7×24 无休，返回空 DataFrame。"""
        pass

    def supports_ashare_extras(self) -> bool:
        """False。"""
        pass
