"""单文件 Parquet 快照存储（模块单例工具）。

按 AGENTS.md §6 模块模式：各表仅差一个 file_path，作为函数参数传入，不写 Class。
用于基础信息等全量覆盖表（basic / fund_basic / cb_basic 等），每次同步整体覆盖。
"""
from pathlib import Path

import pandas as pd


def write(file_path: Path, df: pd.DataFrame) -> None:
    """全量覆盖写。"""
    if df.empty:
        return
    file_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(file_path, index=False)


def read(file_path: Path) -> pd.DataFrame:
    """读全部；无则返回空 DataFrame。"""
    if not file_path.exists():
        return pd.DataFrame()
    return pd.read_parquet(file_path)


def exists(file_path: Path) -> bool:
    """文件是否存在。"""
    return file_path.exists()
