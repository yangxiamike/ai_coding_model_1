"""数据方维护的零选择 canonical dataset preset。"""
from pathlib import Path

from data.dataset_package.builder import build_dataset
from data.dataset_package.schema import DEFAULT_FIELDS, SCHEMA_VERSION
from data.dataset_package.spec import DatasetSpec

STANDARD_DAILY_PRESET_NAME = "ashare_daily_cross_section"
STANDARD_DAILY_PRESET_VERSION = "1.0.0"


def standard_daily_spec(config_path, output_dir) -> DatasetSpec:
    """返回 v1 标准日频截面基础包规格；调用方只提供两个机器本地路径。"""
    return DatasetSpec(
        name=f"{STANDARD_DAILY_PRESET_NAME}_v1",
        preset_name=STANDARD_DAILY_PRESET_NAME,
        preset_version=STANDARD_DAILY_PRESET_VERSION,
        schema_version=SCHEMA_VERSION,
        start_date="20100101",
        end_date="20251231",
        output_dir=Path(output_dir),
        config_path=Path(config_path),
        fields={table: tuple(fields) for table, fields in DEFAULT_FIELDS.items()},
        exchanges=("SSE", "SZSE", "BSE"),
        include_ts_codes=(),
        splits={
            "train": {"start": "20100101", "end": "20221230"},
            "validation": {"start": "20230201", "end": "20231229"},
            "test": {"start": "20240201", "end": "20251231"},
        },
        default_view="training_view_hfq",
    )


def build_standard_dataset(config_path, output_dir, *, client=None):
    """按 canonical v1 preset 构建；不向调用方暴露表、股票池或清洗选择。"""
    return build_dataset(
        standard_daily_spec(config_path=config_path, output_dir=output_dir),
        client=client,
    )
