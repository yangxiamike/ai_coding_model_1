"""查询引擎（模块单例工具）：DuckDB read_parquet 谓词下推。

按 AGENTS.md §6 模块模式：无状态工具，直接用模块级函数，不写 Class。
直读 Parquet 分区目录，按 ts_code + 日期区间过滤，只扫需要的分区与列，
返回 DataFrame。

职责边界：本引擎只读本地 Parquet，不回源、不感知数据源。"本地是否已补缺"
由调用方（provider）在调用前经 sync_jobs.run_table 保证；本引擎假定调用时
本地覆盖已就绪，缺失返回空 df（不报错、不阻塞）。这保证查询路径积分可控、
行为可预测、结果可复现。
"""
from pathlib import Path
from typing import List, Optional

import duckdb
import pandas as pd


def _glob_source(source: Path) -> str:
    """将目录/文件路径转为 DuckDB read_parquet 可识别的 glob 模式。"""
    if source.is_file():
        return str(source)
    if source.is_dir():
        # **/*.parquet 递归匹配所有子目录下的 parquet 文件
        return str(source / "**" / "*.parquet")
    return str(source)


def select(
    source: Path,
    columns: List[str],
    ts_codes: Optional[List[str]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    date_column: str = "trade_date",
    hive_partitioning: bool = True,
    order_by: str = "ts_code, trade_date",
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """对分区目录执行谓词下推查询。

    source 为分区根目录（含 ts_code=*/date=* 子目录）或其 glob。
    返回过滤后的 DataFrame。日期列默认 trade_date；分钟表传 date（hive 分区列）。
    """
    if not source.exists():
        return pd.DataFrame(columns=columns)
    col_str = ", ".join(columns)
    path_str = _glob_source(source)
    # DuckDB read_parquet 直接按分区目录剪枝，只扫匹配的分区
    sql_parts = [f"SELECT {col_str} FROM read_parquet('{path_str}', hive_partitioning={str(hive_partitioning).lower()})"]
    wheres = []
    if ts_codes:
        quoted = [f"'{c}'" for c in ts_codes]
        wheres.append(f"ts_code IN ({', '.join(quoted)})")
    if start:
        wheres.append(f"{date_column} >= '{start}'")
    if end:
        wheres.append(f"{date_column} <= '{end}'")
    if wheres:
        sql_parts.append("WHERE " + " AND ".join(wheres))
    sql_parts.append(f"ORDER BY {order_by}")
    if limit is not None:
        sql_parts.append(f"LIMIT {limit}")
    sql = " ".join(sql_parts)
    return duckdb.query(sql).fetchdf()


def select_one(
    source: Path,
    ts_code: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    columns: Optional[List[str]] = None,
    date_column: str = "trade_date",
) -> pd.DataFrame:
    """单标的跨日查询的便捷封装。"""
    if columns is None:
        columns = ["*"]
    return select(source, columns, ts_codes=[ts_code],
                  start=start, end=end, date_column=date_column)


def execute(sql: str, params: Optional[list] = None) -> pd.DataFrame:
    """执行任意 DuckDB SQL 并返回 DataFrame（高级用法）。"""
    # 修复 2026-07-14: 原内层 if not params 恒为 False（死代码），简化为直接分派。
    if params:
        return duckdb.execute(sql, params).fetchdf()
    return duckdb.query(sql).fetchdf()
