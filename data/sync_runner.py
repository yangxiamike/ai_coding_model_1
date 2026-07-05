"""数据模块同步门面（函数式对称，可选定期预热）。

与 provider 查询面对称的"同步面"：调用方说标的 / 区间 / 频率，sync_runner
触发补缺落库，但不返回 df。供定期预热（cron / 脚本触发）或显式批量拉取用。
模块不内置定时调度器（环境无 apscheduler），定期与否由外部决定。

二者共用 sync_jobs.run_table 补缺内核：provider 调后读本地返回 df，
sync_runner 调后不读。命中已存在分区跳过不回源，缺则回源→落库→更新进度。

无状态门面：运行时状态由 sync_jobs 模块单例持有。模块加载即就绪，无 init。

用法：
    from data import sync_runner
    sync_runner.daily(["600000.SH"], "20240101", "20240601")   # 预热日线
    sync_runner.all(codes=["600000.SH"], start="20240101")    # 全量预热
"""
import logging
from typing import List, Optional

from data import config, snapshot_store, sync_jobs

logger = logging.getLogger(__name__)


def minute(codes: List[str], start: str, end: str) -> None:
    """预热分钟线（per 标的时序，双层 ts_code/date 分区）。"""
    sync_jobs.run_table("minute_kline", codes, start, end)


def daily(codes: List[str], start: str, end: str) -> None:
    """预热日线（per 标的时序，双层 ts_code/date 分区）。"""
    sync_jobs.run_table("daily_kline", codes, start, end)


def daily_basic(start: str, end: str) -> None:
    """预热每日指标（per 交易日全市场横截面，单层 date 分区）。"""
    sync_jobs.run_table("daily_basic", None, start, end)


def adj_factor(codes: List[str], start: str, end: str) -> None:
    """预热复权因子（per 标的时序）。"""
    sync_jobs.run_table("adj_factor", codes, start, end)


def stk_limit(date: str) -> None:
    """预热当日涨跌停价。"""
    sync_jobs.run_table("stk_limit", None, date, date)


def stock_st(date: str) -> None:
    """预热当日 ST 列表。"""
    sync_jobs.run_table("stock_st", None, date, date)


def suspend_d(date: str) -> None:
    """预热当日停复牌。"""
    sync_jobs.run_table("suspend_d", None, date, date)


def trade_cal(start: str, end: str, exchange: str = "SSE") -> None:
    """刷新交易日历（区间 upsert 到 DuckDB，不丢其他区间）。

    供节假日调整后定期刷新（每年一次）。_ensure_ready 阶段已确保有基础覆盖，
    此处为强制区间刷新。
    """
    sync_jobs.refresh_trade_cal(start, end, exchange)


def stock_list(sec_type: str = "stock") -> None:
    """刷新标的清单快照（全量覆盖单文件）。

    sec_type 由 config.basic_sec_type 注入（sync_jobs._build_tasks 绑定），
    此处不重复传参；多类别预热改 config 后重新触发。
    """
    sync_jobs.run_table("basic", None, "", "")


def all(codes: Optional[List[str]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None) -> None:
    """全量预热所有表。

    codes 为 None 时从已落库 basic 快照取；start 缺省取 config.first_date；
    end 缺省取今日。顺序：trade_cal → basic → 行情 → 辅助表。
    """
    sync_jobs._ensure_ready()
    cal = sync_jobs.get_calendar()
    today = cal.today()
    first = config.get("data.first_date", "20160101") if start is None else start
    last = today if end is None else end

    trade_cal(first, last)
    stock_list()
    if codes is None:
        df = snapshot_store.read(sync_jobs.get_table_path("basic"))
        codes = df["ts_code"].tolist() if not df.empty and "ts_code" in df.columns else []
    if codes:
        daily(codes, first, last)
        adj_factor(codes, first, last)
        minute(codes, first, last)
    daily_basic(first, last)
    _date_range_each(stk_limit, first, last)
    _date_range_each(stock_st, first, last)
    _date_range_each(suspend_d, first, last)


def _date_range_each(fn, start: str, end: str) -> None:
    """对 per 交易日同步函数逐交易日调用，单日失败不中断。"""
    days = sync_jobs._trading_days(start, end) or sync_jobs._natural_days(start, end)
    for d in days:
        try:
            fn(d)
        except Exception as e:
            logger.warning(f"{fn.__name__} {d} failed: {e}")
