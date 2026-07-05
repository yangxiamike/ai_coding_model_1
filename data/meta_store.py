"""DuckDB 元数据存储（模块单例）。

按 AGENTS.md §6 模块模式：本 .py 文件即单例，模块级持有 DuckDB 连接，
对外暴露函数，不写 Class。模块加载即就绪：连接在首次访问任一公开函数时
惰性打开（_ensure_conn），db_path 取自 data.config 并相对本模块目录解析，
不依赖 cwd。无 init / is_initialized 入口。

DuckDB 只存两类元数据：
- sync_meta：表名 → 最后同步日（驱动增量同步）。
- trade_cal：交易日历（驱动日历查询）。

行情数据本身存 Parquet 分区（partition_store / snapshot_store），
DuckDB 不存行情；查询时 DuckDB 直读 Parquet（query_engine），
元库仅作增量与日历索引。
"""
from pathlib import Path
from typing import List, Optional

import duckdb
import pandas as pd

from data import config

_conn: Optional[duckdb.DuckDBPyConnection] = None


def _ensure_conn() -> None:
    """惰性打开 DuckDB 连接并建表。

    db_path 取自 config.get("data.db_path")，相对 data 目录解析，不依赖 cwd。
    重复调用在已连接时为空操作。
    """
    global _conn
    if _conn is not None:
        return
    db_rel = config.get("data.db_path", "db/meta.duckdb")
    db_path = Path(db_rel)
    if not db_path.is_absolute():
        db_path = config.module_dir() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _conn = duckdb.connect(str(db_path))
    # 同步进度表：驱动增量回填的 last_date 锚点
    _conn.execute("CREATE TABLE IF NOT EXISTS sync_meta ("
                  "table_name VARCHAR PRIMARY KEY, last_date VARCHAR)")
    # 交易日历表：get_trading_days / is_trading_day 的查询索引
    _conn.execute("CREATE TABLE IF NOT EXISTS trade_cal ("
                  "exchange VARCHAR, cal_date VARCHAR, is_open INTEGER, "
                  "pretrade_date VARCHAR, "
                  "PRIMARY KEY (exchange, cal_date))")


# ---- 同步进度 ----

def get_last_date(table_name: str) -> Optional[str]:
    """某表最后同步到的交易日（YYYYMMDD），无记录则 None。"""
    _ensure_conn()
    r = _conn.execute("SELECT last_date FROM sync_meta WHERE table_name=?",
                      [table_name]).fetchone()
    return r[0] if r else None


def update_last_date(table_name: str, last_date: str) -> None:
    """更新某表最后同步日（UPSERT）。"""
    _ensure_conn()
    _conn.execute("INSERT INTO sync_meta (table_name, last_date) VALUES (?, ?) "
                  "ON CONFLICT (table_name) DO UPDATE SET last_date=excluded.last_date",
                  [table_name, last_date])


# ---- 交易日历 ----

def load_trade_cal(data_dir: Path, exchanges: Optional[List[str]] = None) -> None:
    """从 Parquet trade_cal 分区载入到 DuckDB trade_cal 表。"""
    _ensure_conn()
    glob_pattern = str(data_dir / "trade_cal" / "**" / "*.parquet")
    df = _conn.execute(f"SELECT * FROM read_parquet('{glob_pattern}')").fetchdf()
    if df.empty:
        return
    if exchanges:
        df = df[df["exchange"].isin(exchanges)]
    _conn.execute("DELETE FROM trade_cal")
    _conn.execute("INSERT INTO trade_cal SELECT * FROM df")


def replace_trade_cal(df: pd.DataFrame) -> None:
    """用 DataFrame 内容整体替换 trade_cal 表（provider 初始化时用）。"""
    _ensure_conn()
    _conn.execute("DELETE FROM trade_cal")
    _conn.execute("INSERT INTO trade_cal SELECT exchange, cal_date, is_open, pretrade_date FROM df")


def upsert_trade_cal(df: pd.DataFrame) -> None:
    """按 (exchange, cal_date) upsert trade_cal（区间刷新用，不丢其他区间）。"""
    _ensure_conn()
    if df is None or df.empty:
        return
    _conn.execute("CREATE TEMPORARY TABLE _tc_upsert AS SELECT * FROM df")
    _conn.execute(
        "INSERT INTO trade_cal SELECT exchange, cal_date, is_open, pretrade_date FROM _tc_upsert "
        "ON CONFLICT (exchange, cal_date) DO UPDATE SET "
        "is_open=excluded.is_open, pretrade_date=excluded.pretrade_date"
    )
    _conn.execute("DROP TABLE _tc_upsert")


def get_trading_days(exchange: str, start: str, end: str) -> List[str]:
    """返回区间交易日列表（YYYYMMDD，升序）。"""
    _ensure_conn()
    rows = _conn.execute(
        "SELECT cal_date FROM trade_cal "
        "WHERE exchange=? AND is_open=1 AND cal_date>=? AND cal_date<=? "
        "ORDER BY cal_date",
        [exchange, start, end],
    ).fetchall()
    return [r[0] for r in rows]


def is_trading_day(exchange: str, cal_date: str) -> bool:
    """是否交易日；未覆盖日期保守返回 True。"""
    _ensure_conn()
    r = _conn.execute(
        "SELECT is_open FROM trade_cal WHERE exchange=? AND cal_date=?",
        [exchange, cal_date],
    ).fetchone()
    if r is None:
        return True  # 无记录时保守返回 True，避免意外停盘
    return bool(r[0])


# ---- 生命周期 ----

def close() -> None:
    """关闭 DuckDB 连接。"""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
