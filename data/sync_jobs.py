"""补缺执行器与运行时状态（模块单例）。

按 AGENTS.md §6 模块模式：本 .py 即单例，模块级持有运行时状态
（source / calendar / tasks / table_paths），首次访问任一公开函数时惰性
组装（_ensure_ready），配置取自 data.config，无 init 入口。

职责：
1. 运行时状态组装：根据 config.source 构造数据源、日历、各表 SyncTask、
   table_paths；并确保 trade_cal 已落 DuckDB（否则日历查询恒空，补缺无法推进）。
2. SyncTask（dataclass）补缺执行：给定表名 + 标的 + 区间，只拉本地缺失部分
   → 归一化 → 落库 → 更新 meta_store 进度，命中跳过。
3. run_table 对外入口：供 provider（查询面按需回源兜底）与 sync_runner
   （同步面显式预热）共用，二者差异仅在调用后是否读本地返回 df。

设计要点（相对旧版的修正）：
- 删除 `runtime` 对象注入（旧版让调用方传 runtime.calendar/runtime.meta/
  runtime.codes，属耦合泄漏，违反 §6 模块自足性）。source/calendar/tasks
  均为模块级状态，内部组合 meta_store/calendar/partition_store/snapshot_store
  模块，调用方只传业务语义（table/codes/start/end）。
- fetch 绑定由 _build_tasks 在组装时用各源方法引用直接绑定，run_* 按统一
  契约调用（partition: fetch(ts_code,start,end)；date_section: fetch(date)；
  snapshot: fetch()）。
"""
import datetime as dt
import logging
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from data import config, meta_store, normalizer, partition_store, snapshot_store
from data.calendar import AlwaysOpenCalendar, TradingCalendar
from data.datasource.binance import BinanceSource
from data.datasource.baostock import BaostockSource
from data.datasource.interface import DataSource
from data.datasource.tushare import TushareSource

logger = logging.getLogger(__name__)


# ===== 运行时状态（模块单例，惰性组装） =====

_source: Optional[DataSource] = None
_calendar: Optional[object] = None        # TradingCalendar | AlwaysOpenCalendar
_tasks: Dict[str, "SyncTask"] = {}
_table_paths: Dict[str, Path] = {}
_ready: bool = False


def _resolve_data_dir() -> Path:
    """data_dir 相对 data 目录解析，不依赖 cwd。"""
    data_dir_rel = config.get("data.data_dir", "market_data")
    data_dir = Path(data_dir_rel)
    if not data_dir.is_absolute():
        data_dir = config.module_dir() / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _build_source() -> DataSource:
    """按 config.source 构造数据源。换源只改 config + 新增 datasource 实现。"""
    name = config.get("data.source", "tushare")
    if name == "tushare":
        token = config.get("data.tushare_token", "")
        interval = float(config.get("data.fetch_interval_sec", 0.2))
        return TushareSource(token=token, fetch_interval_sec=interval)
    if name == "baostock":
        return BaostockSource()
    if name == "binance":
        return BinanceSource()
    raise ValueError(f"unknown data source: {name}")


def _build_calendar(src: DataSource) -> object:
    """BTC 源用 7×24 无休日历；A 股源用交易日历。"""
    if src.name == "binance":
        return AlwaysOpenCalendar()
    return TradingCalendar()


def _build_table_paths(data_dir: Path) -> Dict[str, Path]:
    """各表存储路径。双层/单层分区为目录，快照为 .parquet 文件。"""
    return {
        # per 标的时序（双层 ts_code/date 分区）
        "minute_kline": data_dir / "minute_kline",
        "daily_kline": data_dir / "daily_kline",
        "adj_factor": data_dir / "adj_factor",
        # per 交易日全市场横截面（单层 date 分区）
        "daily_basic": data_dir / "daily_basic",
        "stock_st": data_dir / "stock_st",
        "suspend_d": data_dir / "suspend_d",
        "stk_limit": data_dir / "stk_limit",
        # 全量快照（单文件）
        "basic": data_dir / "basic.parquet",
    }


def _build_tasks(src: DataSource, table_paths: Dict[str, Path],
                 first_date: str, retry_delays: tuple) -> Dict[str, "SyncTask"]:
    """构造各表 SyncTask。fetch 绑定源方法引用，run_* 按统一契约调用。

    A 股辅助表（daily_basic/stock_st/suspend_d/stk_limit/adj_factor）仅
    A 股源支持（baostock/binance 的这些方法返回空 df），故无差别绑定；
    若源 supports_ashare_extras() 为 False，相关 task 仍存在但补缺恒空。
    """
    sec_type = config.get("data.basic_sec_type", "stock")
    return {
        "minute_kline": SyncTask("minute_kline", "partition",
                                  src.fetch_minute,
                                  store_dir=table_paths["minute_kline"],
                                  first_date=first_date, retry_delays=retry_delays),
        "daily_kline": SyncTask("daily_kline", "partition",
                                 src.fetch_daily,
                                 store_dir=table_paths["daily_kline"],
                                 first_date=first_date, retry_delays=retry_delays),
        "adj_factor": SyncTask("adj_factor", "partition",
                                src.fetch_adj_factor,
                                store_dir=table_paths["adj_factor"],
                                first_date=first_date, retry_delays=retry_delays),
        "daily_basic": SyncTask("daily_basic", "date_section",
                                 src.fetch_daily_basic,
                                 store_dir=table_paths["daily_basic"],
                                 first_date=first_date, retry_delays=retry_delays),
        "stock_st": SyncTask("stock_st", "date_section",
                              src.fetch_stock_st,
                              store_dir=table_paths["stock_st"],
                              first_date=first_date, retry_delays=retry_delays),
        "suspend_d": SyncTask("suspend_d", "date_section",
                               src.fetch_suspend_d,
                               store_dir=table_paths["suspend_d"],
                               first_date=first_date, retry_delays=retry_delays),
        "stk_limit": SyncTask("stk_limit", "date_section",
                               src.fetch_stk_limit,
                               store_dir=table_paths["stk_limit"],
                               first_date=first_date, retry_delays=retry_delays),
        "basic": SyncTask("basic", "snapshot",
                           partial(src.fetch_basic, sec_type=sec_type),
                           store_file=table_paths["basic"],
                           first_date=first_date, retry_delays=retry_delays),
    }


def _ensure_trade_cal() -> None:
    """确保 trade_cal 已落 DuckDB。无则回源拉取并 replace_trade_cal。

    trade_cal 是补缺推进的前置依赖（calendar.trading_days 依赖它），故在
    _ensure_ready 阶段先确保覆盖。trade_cal 直存 DuckDB（数据量小），不落 Parquet。
    """
    exchange = config.get("data.exchange", "SSE")
    today = _calendar.today()  # type: ignore[union-attr]
    first_date = config.get("data.first_date", "20160101")
    # 探测是否已有任意 trade_cal 记录
    days = meta_store.get_trading_days(exchange, first_date, today)
    if days:
        return
    # 无记录则回源拉取并整体替换
    try:
        df = _source.fetch_trade_cal(exchange, first_date, today)  # type: ignore[union-attr]
    except Exception as e:
        logger.warning(f"fetch_trade_cal failed: {e}; 日历将退化为保守'全开'")
        return
    if df is None or df.empty:
        return
    meta_store.replace_trade_cal(df)


def refresh_trade_cal(start: str, end: str, exchange: str = "SSE") -> None:
    """强制刷新 trade_cal 区间（upsert 到 DuckDB，不丢其他区间）。

    供 sync_runner.trade_cal 调用：定期刷新节假日变更（每年调整）。
    """
    _ensure_ready()
    try:
        df = _source.fetch_trade_cal(exchange, start, end)  # type: ignore[union-attr]
    except Exception as e:
        logger.warning(f"refresh_trade_cal {exchange} {start}-{end} failed: {e}")
        return
    if df is None or df.empty:
        return
    meta_store.upsert_trade_cal(df)
    logger.info(f"trade_cal {exchange} {start}-{end} refreshed rows={len(df)}")


def _ensure_ready() -> None:
    """惰性组装运行时状态。重复调用空操作。"""
    global _source, _calendar, _tasks, _table_paths, _ready
    if _ready:
        return
    _source = _build_source()
    _calendar = _build_calendar(_source)
    data_dir = _resolve_data_dir()
    _table_paths = _build_table_paths(data_dir)
    first_date = str(config.get("data.first_date", "20160101"))
    retry_delays = tuple(config.get("data.retry_delays", [5, 15, 45]))
    _tasks = _build_tasks(_source, _table_paths, first_date, retry_delays)
    _ensure_trade_cal()
    _ready = True


# ===== 状态访问器（供 provider 查询时取） =====

def get_source() -> DataSource:
    """当前数据源（查询层用其 supports_ashare_extras 判能力）。"""
    _ensure_ready()
    assert _source is not None
    return _source


def get_calendar() -> object:
    """当前日历（查询层判交易日/交易时段用）。"""
    _ensure_ready()
    assert _calendar is not None
    return _calendar


def get_table_path(table: str) -> Path:
    """某表存储路径（分区目录或快照文件）。"""
    _ensure_ready()
    return _table_paths[table]


def get_task(table: str) -> "SyncTask":
    """某表 SyncTask。"""
    _ensure_ready()
    return _tasks[table]


# ===== SyncTask 定义 =====

@dataclass
class SyncTask:
    """一张表的补缺配置。

    fetch 绑定源方法，run_* 按统一契约调用：
    - kind="partition"：fetch(ts_code, start, end) → df（per 标的时序，双层分区）
    - kind="date_section"：fetch(trade_date) → df（per 交易日横截面，单层 date 分区）
    - kind="snapshot"：fetch() → df（全量覆盖，单文件）
    """
    table_name: str
    kind: str                                # "partition" | "date_section" | "snapshot"
    fetch: Callable[..., pd.DataFrame]
    store_dir: Optional[Path] = None         # 分区表用
    store_file: Optional[Path] = None        # 快照表用
    exchange: str = "SSE"
    first_date: str = "20160101"
    retry_delays: tuple = (5, 15, 45)
    write_empty: bool = False


# ===== 补缺执行 =====

def _retry_fetch(fetch_fn: Callable, retry_delays: tuple, **kwargs) -> pd.DataFrame:
    """按 retry_delays 间隔重试 fetch_fn，均失败则抛最后一个异常。"""
    last_err: Optional[Exception] = None
    for delay in retry_delays:
        time.sleep(delay)
        try:
            return fetch_fn(**kwargs)
        except Exception as e:
            last_err = e
            logger.warning(f"retry after {delay}s failed: {e}")
    raise last_err if last_err is not None else RuntimeError("retry exhausted")


def _trading_days(start: str, end: str) -> List[str]:
    """区间交易日列表（YYYYMMDD，升序）。依赖 _calendar 已组装。"""
    assert _calendar is not None
    exchange = config.get("data.exchange", "SSE")
    return _calendar.trading_days(exchange, start, end)


def run_partition_sync(task: SyncTask, codes: Optional[List[str]],
                       start: str, end: str) -> None:
    """per 标的时序补缺（minute_kline / daily_kline / adj_factor）。

    按交易日 × 标的循环，跳过已存在分区；fetch(ts_code, date, date) 拉单日 →
    归一化已由 datasource 内部完成 → 落双层分区 → 更新 last_date。
    """
    if not codes:
        return
    trading_days = _trading_days(start, end)
    if not trading_days:
        # 非交易日区间或 trade_cal 缺失，退化为按自然日逐日尝试
        trading_days = _natural_days(start, end)
    last_done: Optional[str] = None
    for trade_date in trading_days:
        for ts_code in codes:
            if partition_store.exists(task.store_dir, ts_code, trade_date):  # type: ignore[arg-type]
                continue
            df = pd.DataFrame()
            try:
                df = task.fetch(ts_code, trade_date, trade_date)
            except Exception as e:
                logger.warning(f"{task.table_name} fetch {ts_code} {trade_date}: {e}")
                try:
                    df = _retry_fetch(task.fetch, task.retry_delays,
                                      ts_code=ts_code, start=trade_date, end=trade_date)
                except Exception as e2:
                    logger.error(f"{task.table_name} {ts_code} {trade_date} retry failed: {e2}")
                    continue
            if df is None or (df.empty and not task.write_empty):
                continue
            partition_store.write(task.store_dir, ts_code, trade_date, df)  # type: ignore[arg-type]
            logger.info(f"{task.table_name} {ts_code} {trade_date} synced rows={len(df)}")
        last_done = trade_date
    if last_done is not None:
        meta_store.update_last_date(task.table_name, last_done)


def run_date_section_sync(task: SyncTask, start: str, end: str) -> None:
    """per 交易日全市场横截面补缺（daily_basic / stock_st / suspend_d / stk_limit）。

    按交易日循环，跳过已存在 date 分区；fetch(trade_date) 拉全市场 →
    落单层 date 分区 → 更新 last_date。
    """
    trading_days = _trading_days(start, end)
    if not trading_days:
        trading_days = _natural_days(start, end)
    last_done: Optional[str] = None
    for trade_date in trading_days:
        if partition_store.exists_date(task.store_dir, trade_date):  # type: ignore[arg-type]
            last_done = trade_date
            continue
        df = pd.DataFrame()
        try:
            df = task.fetch(trade_date)
        except Exception as e:
            logger.warning(f"{task.table_name} fetch {trade_date}: {e}")
            try:
                df = _retry_fetch(task.fetch, task.retry_delays, trade_date=trade_date)
            except Exception as e2:
                logger.error(f"{task.table_name} {trade_date} retry failed: {e2}")
                continue
        if df is None or (df.empty and not task.write_empty):
            last_done = trade_date
            continue
        partition_store.write_date(task.store_dir, trade_date, df)  # type: ignore[arg-type]
        logger.info(f"{task.table_name} {trade_date} synced rows={len(df)}")
        last_done = trade_date
    if last_done is not None:
        meta_store.update_last_date(task.table_name, last_done)


def run_snapshot_sync(task: SyncTask) -> None:
    """全量快照补缺（basic）。fetch() → 整体覆盖写单文件。"""
    try:
        df = task.fetch()
    except Exception as e:
        logger.warning(f"{task.table_name} fetch: {e}")
        try:
            df = _retry_fetch(task.fetch, task.retry_delays)
        except Exception as e2:
            logger.error(f"{task.table_name} retry failed: {e2}")
            return
    if df is None or df.empty:
        logger.info(f"{task.table_name} empty fetch, skip")
        return
    snapshot_store.write(task.store_file, df)  # type: ignore[arg-type]
    meta_store.update_last_date(task.table_name, dt.datetime.now().strftime("%Y%m%d"))
    logger.info(f"{task.table_name} snapshot synced rows={len(df)}")


def run_table(table: str, codes: Optional[List[str]], start: str, end: str) -> None:
    """对外补缺入口：按表名分派到对应 run_*。

    供 provider（查询面按需回源兜底）与 sync_runner（同步面显式预热）共用。
    命中已存在分区则跳过不回源；缺则回源→落库→更新进度。
    """
    _ensure_ready()
    task = _tasks[table]
    if task.kind == "partition":
        run_partition_sync(task, codes, start, end)
    elif task.kind == "date_section":
        run_date_section_sync(task, start, end)
    elif task.kind == "snapshot":
        run_snapshot_sync(task)
    else:
        raise ValueError(f"unknown task kind: {task.kind}")


# ===== 辅助 =====

def _natural_days(start: str, end: str) -> List[str]:
    """自然日列表（YYYYMMDD，升序）。trade_cal 缺失时退化用。"""
    s = dt.datetime.strptime(start, "%Y%m%d")
    e = dt.datetime.strptime(end, "%Y%m%d")
    days: List[str] = []
    cur = s
    while cur <= e:
        days.append(cur.strftime("%Y%m%d"))
        cur += dt.timedelta(days=1)
    return days


def close() -> None:
    """重置运行时状态（供 provider.close 调用，便于重新惰性组装）。"""
    global _source, _calendar, _tasks, _table_paths, _ready
    _source = None
    _calendar = None
    _tasks = {}
    _table_paths = {}
    _ready = False
