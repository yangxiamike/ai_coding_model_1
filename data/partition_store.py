"""Parquet 分区存储（模块单例工具）。

支持两种分区布局（同一套工具函数，按业务表语义选用）：
- 双层分区 `ts_code=XXXX/date=YYYYMMDD/data.parquet`：per 标的时序表
  （minute_kline / daily_kline / adj_factor），单标的序列查询最高效。
- 单层分区 `date=YYYYMMDD/data.parquet`：per 交易日的全市场横截面表
  （daily_basic / stock_st / suspend_d / stk_limit），单日切片高效。

按 AGENTS.md §6 模块模式：各表仅差一个 table_dir 路径，作为函数参数传入，
不写 Class。DuckDB hive_partitioning 谓词下推，单标的查询 <100ms，
全市场单日切片 <500ms。
"""
from pathlib import Path
from typing import List, Optional

import pandas as pd
import pyarrow.parquet as pq


# ===== 双层分区 ts_code/date（per 标的时序） =====

def partition_dir(table_dir: Path, ts_code: str, trade_date: str) -> Path:
    """返回某标的某日的双层分区目录路径。"""
    return table_dir / f"ts_code={ts_code}" / f"date={trade_date}"


def write(table_dir: Path, ts_code: str, trade_date: str, df: pd.DataFrame) -> None:
    """写单标的单日分区（覆盖写）。"""
    if df.empty:
        return
    out_dir = partition_dir(table_dir, ts_code, trade_date)
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / "data.parquet"
    df.to_parquet(file_path, index=False)


def exists(table_dir: Path, ts_code: str, trade_date: str) -> bool:
    """该标的该日分区是否存在。"""
    file_path = partition_dir(table_dir, ts_code, trade_date) / "data.parquet"
    return file_path.exists()


def read(table_dir: Path, ts_code: str, trade_date: str) -> pd.DataFrame:
    """读单标的单日分区；无则返回空 DataFrame。"""
    file_path = partition_dir(table_dir, ts_code, trade_date) / "data.parquet"
    if not file_path.exists():
        return pd.DataFrame()
    return pd.read_parquet(file_path)


def partition_dates(table_dir: Path, ts_code: Optional[str] = None) -> List[str]:
    """列出已存在的分区日期（YYYYMMDD）；可按标的筛。"""
    if not table_dir.exists():
        return []
    if ts_code:
        ts_dir = table_dir / f"ts_code={ts_code}"
        if not ts_dir.exists():
            return []
        return sorted(d.name.split("=")[1] for d in ts_dir.iterdir()
                      if d.is_dir() and d.name.startswith("date="))
    # 遍历所有 ts_code 子目录收集日期
    dates = set()
    if not table_dir.exists():
        return []
    for ts_dir in table_dir.iterdir():
        if ts_dir.is_dir() and ts_dir.name.startswith("ts_code="):
            for d in ts_dir.iterdir():
                if d.is_dir() and d.name.startswith("date="):
                    dates.add(d.name.split("=")[1])
    return sorted(dates)


# ===== 单层分区 date（per 交易日全市场横截面） =====

def partition_dir_date(table_dir: Path, trade_date: str) -> Path:
    """返回某交易日的单层分区目录路径。"""
    return table_dir / f"date={trade_date}"


def write_date(table_dir: Path, trade_date: str, df: pd.DataFrame) -> None:
    """写单日全市场横截面分区（覆盖写）。"""
    if df.empty:
        return
    out_dir = partition_dir_date(table_dir, trade_date)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / "data.parquet", index=False)


def exists_date(table_dir: Path, trade_date: str) -> bool:
    """该交易日的横截面分区是否存在。"""
    return (partition_dir_date(table_dir, trade_date) / "data.parquet").exists()


def read_date(table_dir: Path, trade_date: str) -> pd.DataFrame:
    """读单日横截面分区；无则返回空 DataFrame。"""
    file_path = partition_dir_date(table_dir, trade_date) / "data.parquet"
    if not file_path.exists():
        return pd.DataFrame()
    return pd.read_parquet(file_path)


def partition_dates_date(table_dir: Path) -> List[str]:
    """列出已存在的单层分区日期（YYYYMMDD，升序）。"""
    if not table_dir.exists():
        return []
    return sorted(d.name.split("=")[1] for d in table_dir.iterdir()
                  if d.is_dir() and d.name.startswith("date="))
