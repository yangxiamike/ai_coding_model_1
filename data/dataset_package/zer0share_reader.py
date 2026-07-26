"""zer0share 只读适配器：查询八表并统一字段、dtype、日期、主键与排序。"""
import importlib.metadata
from typing import Any, Dict, Sequence

import numpy as np
import pandas as pd

from data.dataset_package.schema import (
    BSE_START_DATE,
    DATE_COLUMNS,
    FLOAT_COLUMNS,
    INTEGER_COLUMNS,
    PRIMARY_KEYS,
    SOURCE_ALIASES,
    SOURCE_FIELD_ALIASES,
)
from data.dataset_package.spec import DatasetSpec


class DatasetSourceError(RuntimeError):
    """zer0share 查询或返回契约错误。"""


class Zer0shareReader:
    """持有一个由 ``pro_api(config_path=...)`` 创建的只读 client。"""

    _PAGE_SIZE = 100_000

    def __init__(self, spec: DatasetSpec, client=None) -> None:
        self._spec = spec
        if client is None:
            try:
                import zer0share
                from zer0share import pro_api
            except ImportError as exc:
                raise DatasetSourceError(
                    "zer0share is required only when building a dataset package"
                ) from exc
            try:
                self._client = pro_api(config_path=str(spec.config_path))
            except Exception as exc:
                raise DatasetSourceError("zer0share pro_api client creation failed") from exc
            try:
                self.version = importlib.metadata.version("zer0share")
            except importlib.metadata.PackageNotFoundError:
                self.version = str(getattr(zer0share, "__version__", "unknown"))
        else:
            self._client = client
            self.version = str(getattr(client, "zer0share_version", "injected"))

    def read_all(self) -> Dict[str, pd.DataFrame]:
        """按确定顺序查询八表，不调用任何同步、更新或回源接口。"""
        metadata = self.read_metadata()
        codes = metadata["stock_basic"]["ts_code"].tolist()
        frames = {
            **metadata,
            **self.read_period(self._spec.start_date, self._spec.end_date, codes),
        }
        self.validate_required_tables(frames)
        return frames

    def read_metadata(self) -> Dict[str, pd.DataFrame]:
        """读取小型全局元数据；用于 builder 的分年构建。"""
        stock_basic = self._read_stock_basic()
        stock_basic = self._select_universe(stock_basic)
        trade_cal = self._read_trade_cal()
        for exchange in self._spec.exchanges:
            exchange_calendar = trade_cal[trade_cal["exchange"] == exchange]
            if exchange_calendar.empty:
                raise DatasetSourceError(f"trade_cal is empty for exchange: {exchange}")
            calendar_start = exchange_calendar["cal_date"].min()
            calendar_end = exchange_calendar["cal_date"].max()
            required_start = (
                max(self._spec.start_date, BSE_START_DATE)
                if exchange == "BSE" else self._spec.start_date
            )
            if calendar_start > required_start or calendar_end < self._spec.end_date:
                raise DatasetSourceError(
                    f"trade_cal {exchange} does not cover requested range: "
                    f"{calendar_start}..{calendar_end}; required={required_start}..{self._spec.end_date}"
                )
        return {"stock_basic": stock_basic, "trade_cal": trade_cal}

    def read_period(
        self,
        start_date: str,
        end_date: str,
        codes: Sequence[str],
    ) -> Dict[str, pd.DataFrame]:
        """读取一个日期块的六张大表；每块内部完成归一化与因子覆盖校验。"""
        frames = {
            "daily": self._read_range("daily", codes, start_date, end_date),
            "adj_factor": self._read_range("adj_factor", codes, start_date, end_date),
            "daily_basic": self._read_range("daily_basic", codes, start_date, end_date),
            "stock_st": self._read_range("stock_st", codes, start_date, end_date),
            "suspend_d": self._read_range("suspend_d", codes, start_date, end_date),
            "stk_limit": self._read_range("stk_limit", codes, start_date, end_date),
        }
        self._validate_daily_factor_coverage(frames["daily"], frames["adj_factor"])
        return frames

    @staticmethod
    def validate_required_tables(frames: Dict[str, pd.DataFrame]) -> None:
        """完整构建结束前确认非状态类必需表至少有一行。"""
        required = (
            "stock_basic", "trade_cal", "daily", "adj_factor",
            "daily_basic", "stk_limit",
        )
        for table in required:
            if frames[table].empty:
                raise DatasetSourceError(f"required source table is empty: {table}")

    def _read_stock_basic(self) -> pd.DataFrame:
        return self._normalize(
            "stock_basic",
            self._call_all("stock_basic", {"list_status": None}),
        )

    def _read_trade_cal(self) -> pd.DataFrame:
        parts = []
        for exchange in self._spec.exchanges:
            parts.extend(
                self._call_all(
                    "trade_cal",
                    {
                        "exchange": exchange,
                        "start_date": self._spec.start_date,
                        "end_date": self._spec.end_date,
                    },
                )
            )
        frame = self._normalize("trade_cal", parts)
        return frame[
            (frame["cal_date"] >= self._spec.start_date)
            & (frame["cal_date"] <= self._spec.end_date)
        ].reset_index(drop=True)

    def _read_range(
        self,
        table: str,
        codes: Sequence[str],
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        frame = self._normalize(
            table,
            self._call_all(
                table,
                {
                    "start_date": start_date,
                    "end_date": end_date,
                },
            ),
        )
        if frame.empty:
            return frame
        frame = frame[
            (frame["trade_date"] >= start_date)
            & (frame["trade_date"] <= end_date)
            & frame["ts_code"].isin(codes)
        ]
        return frame.reset_index(drop=True)

    def _call_all(self, table: str, parameters: Dict[str, Any]) -> Sequence[pd.DataFrame]:
        pages = []
        offset = 0
        while True:
            query = dict(parameters)
            query.update({"limit": self._PAGE_SIZE, "offset": offset})
            page = self._call(table, query)
            pages.append(page)
            if len(page) < self._PAGE_SIZE:
                return pages
            offset += self._PAGE_SIZE

    def _call(self, table: str, parameters: Dict[str, Any]) -> pd.DataFrame:
        method = getattr(self._client, table, None)
        if not callable(method):
            raise DatasetSourceError(f"zer0share client missing read method: {table}")
        source_aliases = SOURCE_FIELD_ALIASES.get(table, {})
        fields = [source_aliases.get(field, field) for field in self._spec.fields[table]]
        query = dict(parameters)
        query["fields"] = ",".join(fields)
        try:
            result = method(**query)
        except Exception as exc:
            safe_query = {key: value for key, value in query.items() if key != "fields"}
            raise DatasetSourceError(f"zer0share {table} query failed: {safe_query}") from exc
        if result is None:
            raise DatasetSourceError(f"zer0share {table} returned None")
        if not isinstance(result, pd.DataFrame):
            raise DatasetSourceError(f"zer0share {table} must return pandas.DataFrame")
        return result.copy(deep=True)

    def _normalize(self, table: str, parts: Sequence[pd.DataFrame]) -> pd.DataFrame:
        fields = list(self._spec.fields[table])
        usable = [part for part in parts if part is not None and not part.empty]
        if not usable:
            return _empty_frame(fields)
        frame = pd.concat(usable, ignore_index=True, sort=False)
        frame = frame.rename(columns=SOURCE_ALIASES.get(table, {}))
        missing = [column for column in fields if column not in frame.columns]
        if missing:
            raise DatasetSourceError(f"{table} missing required fields: {missing}")
        frame = frame.loc[:, fields].copy()
        for column in fields:
            try:
                frame[column] = _normalize_column(frame[column], column)
            except (TypeError, ValueError) as exc:
                raise DatasetSourceError(f"{table}.{column} has invalid values") from exc
        keys = PRIMARY_KEYS[table]
        if frame[keys].isna().any().any():
            raise DatasetSourceError(f"{table} primary key contains null: {keys}")
        for key in keys:
            if pd.api.types.is_string_dtype(frame[key].dtype):
                if frame[key].str.len().eq(0).any():
                    raise DatasetSourceError(f"{table} primary key contains empty value: {key}")
        duplicate = frame.duplicated(keys, keep=False)
        if duplicate.any():
            sample = frame.loc[duplicate, keys].head(3).to_dict("records")
            raise DatasetSourceError(f"{table} duplicate primary key {keys}: {sample}")
        if table == "adj_factor":
            invalid = (
                frame["adj_factor"].isna()
                | ~np.isfinite(frame["adj_factor"])
                | (frame["adj_factor"] <= 0)
            )
            if invalid.any():
                raise DatasetSourceError("adj_factor must be finite and positive")
        return frame.sort_values(keys, kind="mergesort").reset_index(drop=True)

    def _select_universe(self, frame: pd.DataFrame) -> pd.DataFrame:
        suffix_to_exchange = {".SH": "SSE", ".SZ": "SZSE", ".BJ": "BSE"}
        allowed_suffixes = {
            suffix for suffix, exchange in suffix_to_exchange.items()
            if exchange in self._spec.exchanges
        }
        mask = frame["ts_code"].str.endswith(tuple(sorted(allowed_suffixes)))
        frame = frame.loc[mask].copy()
        frame = frame[
            (frame["list_date"] <= self._spec.end_date)
            & (
                frame["delist_date"].isna()
                | frame["delist_date"].eq("")
                | (frame["delist_date"] >= self._spec.start_date)
            )
        ]
        if self._spec.include_ts_codes:
            frame = frame[frame["ts_code"].isin(self._spec.include_ts_codes)]
            missing = sorted(set(self._spec.include_ts_codes) - set(frame["ts_code"]))
            if missing:
                raise DatasetSourceError(f"requested include_ts_codes not found in stock_basic: {missing}")
        if frame.empty:
            raise DatasetSourceError("historical A-share universe is empty")
        return frame.sort_values(PRIMARY_KEYS["stock_basic"]).reset_index(drop=True)

    @staticmethod
    def _validate_daily_factor_coverage(daily: pd.DataFrame, adj: pd.DataFrame) -> None:
        if daily.empty:
            return
        factor_keys = adj[["trade_date", "ts_code"]].drop_duplicates()
        missing = daily[["trade_date", "ts_code"]].merge(
            factor_keys,
            on=["trade_date", "ts_code"],
            how="left",
            indicator=True,
        )
        missing = missing[missing["_merge"] == "left_only"]
        if not missing.empty:
            sample = missing[["trade_date", "ts_code"]].head(5).to_dict("records")
            raise DatasetSourceError(f"daily rows missing adj_factor: {sample}")


def _normalize_column(series: pd.Series, column: str) -> pd.Series:
    if column in DATE_COLUMNS:
        raw = series.astype("string").str.strip()
        optional = column in {"pretrade_date", "delist_date"}
        blank = raw.isna() | raw.eq("") | raw.eq("None") | raw.eq("nan")
        parsed = pd.to_datetime(raw.where(~blank), format="%Y%m%d", errors="coerce")
        invalid = ~blank & parsed.isna()
        if not optional:
            invalid = invalid | blank
        if invalid.any():
            raise ValueError(f"invalid date values: {raw[invalid].head(3).tolist()}")
        result = parsed.dt.strftime("%Y%m%d").astype("string")
        if optional:
            return result.fillna("")
        return result
    if column in FLOAT_COLUMNS:
        raw = series
        parsed = pd.to_numeric(raw, errors="coerce").astype("float64")
        invalid = raw.notna() & (parsed.isna() | ~np.isfinite(parsed))
        if invalid.any():
            raise ValueError(f"invalid numeric values: {raw[invalid].head(3).tolist()}")
        return parsed
    if column in INTEGER_COLUMNS:
        raw = pd.to_numeric(series, errors="coerce")
        invalid = raw.isna() | (raw % 1 != 0)
        if invalid.any():
            raise ValueError("invalid integer values")
        return raw.astype("int64")
    return series.astype("string").fillna("").str.strip()


def _empty_frame(fields: Sequence[str]) -> pd.DataFrame:
    data = {}
    for field in fields:
        if field in FLOAT_COLUMNS:
            data[field] = pd.Series(dtype="float64")
        elif field in INTEGER_COLUMNS:
            data[field] = pd.Series(dtype="int64")
        else:
            data[field] = pd.Series(dtype="string")
    return pd.DataFrame(data)
