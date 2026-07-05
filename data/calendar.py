"""交易日历抽象（多态，保留 Class）。

按 AGENTS.md §6：日历存在多态（A 股工作日开盘 vs BTC 7×24 无休），故保留 Class。
A 股基于本地 trade_cal（DuckDB，经 meta_store 模块读取），只在工作日开盘，
分钟 bar 仅存在于 9:30-11:30 / 13:00-15:00 交易时段。加密货币 7×24 无休，
日历退化为"自然日全开"，无交易时段裁剪。

鸭子类型：实现类无需继承，只要实现下列方法即可被 provider 组合使用。
"""
import datetime as dt
from typing import List

from data import meta_store

TZ_BJ = dt.timezone(dt.timedelta(hours=8))

_MINUTES_PER_PERIOD = 240
_TRADE_START = dt.time(9, 30)
_MORNING_END = dt.time(11, 30)
_AFTERNOON_START = dt.time(13, 0)
_AFTERNOON_END = dt.time(15, 0)


class TradingCalendar:
    """A 股交易日历实现，基于 meta_store 模块（DuckDB trade_cal 表）。"""

    def __init__(self) -> None:
        """无需注入；直接调用 meta_store 模块读取 trade_cal。

        meta_store 为惰性模块单例，首次调用其任一公开函数时自动开连接，
        故本类无需任何前置 init 步骤。
        """
        pass

    def is_trading_day(self, exchange: str, date: str) -> bool:
        """date(YYYYMMDD) 是否为该交易所交易日。未覆盖日期保守返回 True。"""
        return meta_store.is_trading_day(exchange, date)

    def trading_days(self, exchange: str, start: str, end: str) -> List[str]:
        """返回 [start, end] 内的交易日列表（YYYYMMDD，升序）。"""
        return meta_store.get_trading_days(exchange, start, end)

    def trading_minutes(self, date: str) -> List[dt.datetime]:
        """返回某交易日全部分钟 bar 的时间戳（北京时间整分钟，右闭）。

        A 股交易时段 9:30-11:30 / 13:00-15:00，1min 共 240 根。
        """
        year, month, day = int(date[:4]), int(date[4:6]), int(date[6:8])
        base = dt.datetime(year, month, day, tzinfo=TZ_BJ)
        minutes = []
        # 上午时段 9:30-11:30
        current = base.replace(hour=9, minute=30)
        morning_end = base.replace(hour=11, minute=30)
        while current < morning_end:
            minutes.append(current.replace(second=0, microsecond=0))
            current += dt.timedelta(minutes=1)
        # 下午时段 13:00-15:00
        current = base.replace(hour=13, minute=0)
        afternoon_end = base.replace(hour=15, minute=0)
        while current < afternoon_end:
            minutes.append(current.replace(second=0, microsecond=0))
            current += dt.timedelta(minutes=1)
        return minutes

    def today(self) -> str:
        """返回今日日期（YYYYMMDD，北京时间）。"""
        return dt.datetime.now(TZ_BJ).strftime("%Y%m%d")


class AlwaysOpenCalendar:
    """加密货币日历：7×24 无休，每日每分钟均开盘。"""

    def is_trading_day(self, exchange: str, date: str) -> bool:
        """恒为 True。"""
        return True

    def trading_days(self, exchange: str, start: str, end: str) -> List[str]:
        """返回区间内全部自然日（YYYYMMDD，升序）。"""
        start_dt = dt.datetime.strptime(start, "%Y%m%d")
        end_dt = dt.datetime.strptime(end, "%Y%m%d")
        days = []
        current = start_dt
        while current <= end_dt:
            days.append(current.strftime("%Y%m%d"))
            current += dt.timedelta(days=1)
        return days

    def trading_minutes(self, date: str) -> List[dt.datetime]:
        """返回该日 0:00~23:59 共 1440 根分钟（北京时间整分钟，右闭）。"""
        year, month, day = int(date[:4]), int(date[4:6]), int(date[6:8])
        base = dt.datetime(year, month, day, tzinfo=TZ_BJ)
        minutes = []
        current = base.replace(hour=0, minute=0)
        end = base.replace(hour=23, minute=59)
        while current <= end:
            minutes.append(current.replace(second=0, microsecond=0))
            current += dt.timedelta(minutes=1)
        return minutes

    def today(self) -> str:
        """返回今日日期（YYYYMMDD，北京时间）。"""
        return dt.datetime.now(TZ_BJ).strftime("%Y%m%d")
