"""可复现 zer0share 数据包规格。"""
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union

import yaml

from data.dataset_package.schema import (
    BSE_START_DATE,
    DEFAULT_FIELDS,
    PRIMARY_KEYS,
    SCHEMA_VERSION,
    TABLES,
)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SUPPORTED_EXCHANGES = {"SSE", "SZSE", "BSE"}
_BUILDER_REQUIRED = {
    "stock_basic": {"ts_code", "name", "exchange", "list_status", "list_date", "delist_date"},
    "trade_cal": {"exchange", "cal_date", "is_open"},
    "daily": {
        "trade_date", "ts_code", "open", "high", "low", "close", "pre_close",
        "change", "pct_chg",
    },
    "adj_factor": {"trade_date", "ts_code", "adj_factor"},
    "daily_basic": {"trade_date", "ts_code"},
    "stock_st": {"trade_date", "ts_code"},
    "suspend_d": {"trade_date", "ts_code"},
    "stk_limit": {"trade_date", "ts_code", "up_limit", "down_limit"},
}


def _date(value: Any, field: str) -> str:
    text = str(value)
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"{field} must be YYYYMMDD")
    try:
        import datetime as dt
        dt.datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid date: {text}") from exc
    return text


@dataclass(frozen=True)
class DatasetSpec:
    """数据包的逻辑规格；机器路径不参与 spec_hash。"""

    name: str
    start_date: str
    end_date: str
    output_dir: Path
    config_path: Path
    fields: Dict[str, Tuple[str, ...]]
    exchanges: Tuple[str, ...] = ("SSE", "SZSE", "BSE")
    include_ts_codes: Tuple[str, ...] = ()
    splits: Dict[str, Dict[str, str]] = None  # type: ignore[assignment]
    default_view: str = "training_view_hfq"
    schema_version: str = SCHEMA_VERSION
    preset_name: Optional[str] = None
    preset_version: Optional[str] = None

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError("dataset name must contain only letters, digits, '.', '_' or '-'")
        start = _date(self.start_date, "start_date")
        end = _date(self.end_date, "end_date")
        if start > end:
            raise ValueError("start_date must not be after end_date")
        object.__setattr__(self, "start_date", start)
        object.__setattr__(self, "end_date", end)
        object.__setattr__(self, "output_dir", Path(self.output_dir).expanduser())
        object.__setattr__(self, "config_path", Path(self.config_path).expanduser())
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version}")
        if self.default_view != "training_view_hfq":
            raise ValueError("default_view must be training_view_hfq")
        if not self.exchanges or set(self.exchanges) - _SUPPORTED_EXCHANGES:
            raise ValueError("exchanges must be a non-empty subset of SSE/SZSE/BSE")
        if set(self.fields) != set(TABLES):
            missing = sorted(set(TABLES) - set(self.fields))
            extra = sorted(set(self.fields) - set(TABLES))
            raise ValueError(f"tables must contain exactly eight tables; missing={missing}, extra={extra}")
        normalized_fields: Dict[str, Tuple[str, ...]] = {}
        for table in TABLES:
            columns = tuple(self.fields[table])
            missing_keys = [key for key in PRIMARY_KEYS[table] if key not in columns]
            if missing_keys:
                raise ValueError(f"{table} fields missing primary key columns: {missing_keys}")
            missing_builder = sorted(_BUILDER_REQUIRED[table] - set(columns))
            if missing_builder:
                raise ValueError(
                    f"{table} fields missing columns required by package views: {missing_builder}"
                )
            if len(columns) != len(set(columns)):
                raise ValueError(f"{table} fields contain duplicates")
            normalized_fields[table] = columns
        object.__setattr__(self, "fields", normalized_fields)
        splits: Dict[str, Dict[str, str]] = {}
        for split_name, bounds in dict(self.splits or {}).items():
            if not isinstance(bounds, Mapping):
                raise ValueError(f"splits.{split_name} must contain start/end")
            split_start = _date(bounds.get("start"), f"splits.{split_name}.start")
            split_end = _date(bounds.get("end"), f"splits.{split_name}.end")
            if split_start > split_end:
                raise ValueError(f"splits.{split_name}.start must not be after end")
            if not start <= split_start <= split_end <= end:
                raise ValueError(f"splits.{split_name} must be inside date range")
            splits[str(split_name)] = {"start": split_start, "end": split_end}
        ordered = sorted(splits.items(), key=lambda item: item[1]["start"])
        for (_, left), (_, right) in zip(ordered, ordered[1:]):
            if left["end"] >= right["start"]:
                raise ValueError("dataset splits must not overlap")
        object.__setattr__(self, "splits", splits)
        object.__setattr__(
            self,
            "include_ts_codes",
            tuple(sorted({str(code).upper() for code in self.include_ts_codes})),
        )
        object.__setattr__(self, "exchanges", tuple(sorted(set(self.exchanges))))
        if self.preset_name is not None or self.preset_version is not None:
            if not self.preset_name or not self.preset_version:
                raise ValueError("preset_name and preset_version must be provided together")

    def logical_dict(self) -> Dict[str, Any]:
        """返回可写入 manifest 的无敏感、无机器路径逻辑规格。"""
        logical = {
            "name": self.name,
            "schema_version": self.schema_version,
            "date_range": {"start": self.start_date, "end": self.end_date},
            "universe": {
                "type": "all_historical_a_shares",
                "exchanges": list(self.exchanges),
                "include_ts_codes": list(self.include_ts_codes),
                "rule": "listed_on_trade_date; SH/SZ/BJ suffix; ST/suspend/limit retained",
                "bse_start_date": BSE_START_DATE,
            },
            "tables": {table: list(self.fields[table]) for table in TABLES},
            "splits": dict(sorted(self.splits.items())),
            "default_view": self.default_view,
            "adjustment": {
                "kind": "hfq",
                "price_columns": ["open", "high", "low", "close", "pre_close"],
                "formula": "adjusted_price = raw_price * adj_factor",
                "change_policy": "recomputed_from_adjusted_close_and_pre_close",
                "missing_policy": "no_forward_fill",
            },
        }
        if self.preset_name is not None or self.preset_version is not None:
            logical["preset"] = {
                "name": self.preset_name,
                "version": self.preset_version,
            }
        return logical

    @property
    def spec_hash(self) -> str:
        payload = json.dumps(
            self.logical_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


SpecInput = Union[DatasetSpec, str, Path, Mapping[str, Any]]


def load_spec(value: SpecInput) -> DatasetSpec:
    """从 DatasetSpec、映射或 YAML 文件读取规格。"""
    if isinstance(value, DatasetSpec):
        return value
    if isinstance(value, (str, Path)):
        path = Path(value)
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        if not isinstance(raw, Mapping):
            raise ValueError("dataset spec root must be a mapping")
        base_dir = path.parent
    elif isinstance(value, Mapping):
        raw = value
        base_dir = Path.cwd()
    else:
        raise TypeError("spec must be DatasetSpec, mapping or YAML path")

    date_range = raw.get("date_range") or {}
    universe = raw.get("universe") or {}
    zer0share = raw.get("zer0share") or {}
    fields = raw.get("tables") or DEFAULT_FIELDS
    output_dir = Path(str(raw.get("output_dir", "datasets")))
    raw_config_path = zer0share.get("config_path")
    if raw_config_path is None or not str(raw_config_path).strip():
        raise ValueError("zer0share.config_path is required")
    config_path = Path(str(raw_config_path))
    if not output_dir.is_absolute():
        output_dir = base_dir / output_dir
    if not config_path.is_absolute():
        config_path = base_dir / config_path
    return DatasetSpec(
        name=str(raw.get("name", "")),
        schema_version=str(raw.get("schema_version", SCHEMA_VERSION)),
        start_date=str(date_range.get("start", "")),
        end_date=str(date_range.get("end", "")),
        output_dir=output_dir,
        config_path=config_path,
        fields={str(table): tuple(columns) for table, columns in fields.items()},
        exchanges=tuple(universe.get("exchanges", ("SSE", "SZSE", "BSE"))),
        include_ts_codes=tuple(universe.get("include_ts_codes", ())),
        splits={
            str(name): dict(bounds)
            for name, bounds in dict(raw.get("splits") or {}).items()
        },
        default_view=str(raw.get("default_view", "training_view_hfq")),
        preset_name=(raw.get("preset") or {}).get("name"),
        preset_version=(raw.get("preset") or {}).get("version"),
    )
