"""从 zer0share 只读快照构建不可覆盖、原子发布的 Parquet 数据包。"""
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from data.dataset_package.package import (
    DatasetPackageError,
    arrow_schema_descriptor,
    make_dataset_id,
    open_dataset,
)
from data.dataset_package.schema import (
    BSE_START_DATE,
    BUILDER_VERSION,
    MANIFEST_VERSION,
    PRICE_COLUMNS,
    PRIMARY_KEYS,
    SCHEMA_VERSION,
    TABLES,
)
from data.dataset_package.spec import SpecInput, load_spec
from data.dataset_package.zer0share_reader import DatasetSourceError, Zer0shareReader


def build_dataset(spec: SpecInput, *, client=None) -> Path:
    """构建数据包并返回最终目录；已有相同 dataset_id 时拒绝覆盖。"""
    dataset_spec = load_spec(spec)
    reader = Zer0shareReader(dataset_spec, client=client)
    dataset_root = dataset_spec.output_dir / dataset_spec.name
    dataset_root.mkdir(parents=True, exist_ok=True)
    temp_path = dataset_root / f".build-pending-{uuid.uuid4().hex}"
    temp_path.mkdir()
    try:
        metadata = reader.read_metadata()
        codes = metadata["stock_basic"]["ts_code"].tolist()
        snapshot_states: Dict[str, Dict] = {}
        artifact_manifest: Dict[str, Dict] = {}
        files: List[Dict] = []
        empty_templates: Dict[str, Tuple[str, pd.DataFrame]] = {}

        for table in ("stock_basic", "trade_cal"):
            _add_snapshot_chunk(snapshot_states, table, metadata[table])
        _append_artifacts(
            temp_path,
            artifact_manifest,
            files,
            empty_templates,
            {table: ("table", metadata[table]) for table in ("stock_basic", "trade_cal")},
        )

        for period_start, period_end in _year_periods(
            dataset_spec.start_date,
            dataset_spec.end_date,
        ):
            period_frames = reader.read_period(period_start, period_end, codes)
            calendar = metadata["trade_cal"]
            period_calendar = calendar[
                (calendar["cal_date"] >= period_start)
                & (calendar["cal_date"] <= period_end)
            ].reset_index(drop=True)
            if (period_calendar["is_open"] == 1).any() and period_frames["daily"].empty:
                raise DatasetSourceError(
                    f"daily is empty for open-calendar period {period_start}..{period_end}"
                )
            for table in TABLES[2:]:
                _add_snapshot_chunk(snapshot_states, table, period_frames[table])
            _append_artifacts(
                temp_path,
                artifact_manifest,
                files,
                empty_templates,
                {table: ("table", period_frames[table]) for table in TABLES[2:]},
            )
            views = _build_views({
                "stock_basic": metadata["stock_basic"],
                "trade_cal": period_calendar,
                **period_frames,
            })
            _append_artifacts(
                temp_path,
                artifact_manifest,
                files,
                empty_templates,
                {name: ("view", frame) for name, frame in views.items()},
            )

        source_fingerprint, source_tables = _finalize_source_snapshot(snapshot_states)
        for required in (
            "stock_basic", "trade_cal", "daily", "adj_factor",
            "daily_basic", "stk_limit",
        ):
            if source_tables[required]["rows"] == 0:
                raise DatasetSourceError(f"required source table is empty: {required}")
        _write_missing_empty_artifacts(
            temp_path,
            artifact_manifest,
            files,
            empty_templates,
        )
        dataset_id = make_dataset_id(
            dataset_spec.name,
            dataset_spec.schema_version,
            dataset_spec.spec_hash,
            source_fingerprint,
        )
        final_path = dataset_root / dataset_id
        logical_spec = dataset_spec.logical_dict()
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "dataset_schema_version": SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "name": dataset_spec.name,
            "spec_hash": dataset_spec.spec_hash,
            "spec": logical_spec,
            "default_view": dataset_spec.default_view,
            "builder": {
                "version": BUILDER_VERSION,
                "code_version": _code_version(),
            },
            "zer0share_version": reader.version,
            "built_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "date_coverage": {
                "start": dataset_spec.start_date,
                "end": dataset_spec.end_date,
            },
            "universe_rule": logical_spec["universe"],
            "splits": logical_spec["splits"],
            "adjustment": logical_spec["adjustment"],
            "source_snapshot": {
                "fingerprint": source_fingerprint,
                "tables": source_tables,
            },
            "artifacts": artifact_manifest,
            "files": sorted(files, key=lambda item: item["path"]),
        }
        (temp_path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        open_dataset(temp_path)
        lock_path = dataset_root / f".{dataset_id}.publish.lock"
        lock_fd = None
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            if final_path.exists() or final_path.is_symlink():
                raise FileExistsError(f"immutable dataset already exists: {final_path}")
            try:
                os.rename(temp_path, final_path)
            except OSError as exc:
                if final_path.exists() or final_path.is_symlink():
                    raise FileExistsError(
                        f"immutable dataset appeared during publish: {final_path}"
                    ) from exc
                raise
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
                if lock_path.exists():
                    lock_path.unlink()
        return final_path
    except Exception:
        if temp_path.exists():
            shutil.rmtree(temp_path)
        raise


def _build_views(source: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    universe = _historical_universe(source["stock_basic"], source["trade_cal"])
    daily_hfq = _daily_hfq(source["daily"], source["adj_factor"])
    panel = universe.merge(
        daily_hfq.assign(has_daily=True),
        on=["trade_date", "ts_code"],
        how="left",
        validate="one_to_one",
    )
    panel["has_daily"] = panel["has_daily"].eq(True)

    factor_presence = source["adj_factor"][
        ["trade_date", "ts_code", "adj_factor"]
    ].rename(columns={"adj_factor": "_source_adj_factor"})
    factor_presence["has_adj_factor"] = True
    panel = panel.merge(
        factor_presence,
        on=["trade_date", "ts_code"],
        how="left",
        validate="one_to_one",
    )
    panel["has_adj_factor"] = panel["has_adj_factor"].eq(True)
    panel["adj_factor"] = panel["adj_factor"].combine_first(
        panel["_source_adj_factor"]
    )
    panel = panel.drop(columns="_source_adj_factor")

    daily_basic = source["daily_basic"].assign(has_daily_basic=True)
    panel = panel.merge(
        daily_basic,
        on=["trade_date", "ts_code"],
        how="left",
        validate="one_to_one",
    )
    panel["has_daily_basic"] = panel["has_daily_basic"].eq(True)

    panel = _join_presence(panel, source["stock_st"], "is_st")
    suspend_type = source["suspend_d"]["suspend_type"].astype("string")
    suspended = source["suspend_d"][
        suspend_type.str.upper().eq("S")
        | (
            suspend_type.str.contains("停牌", na=False)
            & ~suspend_type.str.contains("复牌", na=False)
        )
    ]
    panel = _join_presence(panel, suspended, "is_suspended")
    limit_columns = [
        column for column in ("trade_date", "ts_code", "up_limit", "down_limit")
        if column in source["stk_limit"].columns
    ]
    limits = source["stk_limit"][limit_columns].rename(
        columns={"up_limit": "raw_up_limit", "down_limit": "raw_down_limit"}
    )
    panel = panel.merge(
        limits,
        on=["trade_date", "ts_code"],
        how="left",
        validate="one_to_one",
    )
    raw_close = panel["close"] / panel["adj_factor"]
    panel["is_at_up_limit"] = (
        raw_close.notna()
        & panel["raw_up_limit"].notna()
        & (raw_close >= panel["raw_up_limit"])
    )
    panel["is_at_down_limit"] = (
        raw_close.notna()
        & panel["raw_down_limit"].notna()
        & (raw_close <= panel["raw_down_limit"])
    )
    panel = panel.sort_values(PRIMARY_KEYS["training_view_hfq"], kind="mergesort")
    _assert_primary_key(panel, "training_view_hfq")
    return {
        "universe_history": universe,
        "daily_hfq": daily_hfq,
        "training_view_hfq": panel.reset_index(drop=True),
    }


def _historical_universe(
    stock_basic: pd.DataFrame,
    trade_cal: pd.DataFrame,
) -> pd.DataFrame:
    dates = (
        trade_cal.loc[trade_cal["is_open"] == 1, ["cal_date"]]
        .drop_duplicates()
        .rename(columns={"cal_date": "trade_date"})
    )
    dates["_join"] = 1
    stocks = stock_basic.copy()
    stocks["_join"] = 1
    universe = dates.merge(stocks, on="_join", how="inner").drop(columns="_join")
    eligible = (
        (universe["list_date"] <= universe["trade_date"])
        & (
            universe["delist_date"].eq("")
            | (universe["delist_date"] >= universe["trade_date"])
        )
    )
    eligible &= (
        ~universe["ts_code"].str.endswith(".BJ")
        | (universe["trade_date"] >= BSE_START_DATE)
    )
    universe = universe.loc[eligible].copy()
    universe["is_listed"] = True
    universe = universe[["trade_date", "ts_code", "is_listed"]]
    universe = universe.sort_values(PRIMARY_KEYS["universe_history"], kind="mergesort")
    universe = universe.reset_index(drop=True)
    _assert_primary_key(universe, "universe_history")
    return universe


def _daily_hfq(daily: pd.DataFrame, adj_factor: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        result = daily.copy()
        result["adj_factor"] = pd.Series(dtype="float64")
        return result
    factor = adj_factor[["trade_date", "ts_code", "adj_factor"]]
    result = daily.merge(
        factor,
        on=["trade_date", "ts_code"],
        how="left",
        validate="one_to_one",
    )
    if result["adj_factor"].isna().any():
        missing = result.loc[
            result["adj_factor"].isna(), ["trade_date", "ts_code"]
        ].head(5)
        raise DatasetPackageError(
            f"daily rows missing adj_factor: {missing.to_dict('records')}"
        )
    for column in PRICE_COLUMNS:
        if column in result.columns:
            result[column] = result[column] * result["adj_factor"]
    if {"close", "pre_close", "change"}.issubset(result.columns):
        result["change"] = result["close"] - result["pre_close"]
    if {"close", "pre_close", "pct_chg"}.issubset(result.columns):
        result["pct_chg"] = np.where(
            result["pre_close"] != 0,
            (result["close"] / result["pre_close"] - 1.0) * 100.0,
            np.nan,
        )
    result = result.sort_values(PRIMARY_KEYS["daily_hfq"], kind="mergesort")
    result = result.reset_index(drop=True)
    _assert_primary_key(result, "daily_hfq")
    return result


def _join_presence(
    panel: pd.DataFrame,
    status: pd.DataFrame,
    column: str,
) -> pd.DataFrame:
    presence = status[["trade_date", "ts_code"]].drop_duplicates().assign(**{column: True})
    panel = panel.merge(
        presence,
        on=["trade_date", "ts_code"],
        how="left",
        validate="one_to_one",
    )
    panel[column] = panel[column].eq(True)
    return panel


def _write_artifacts(
    root: Path,
    artifacts: Dict[str, Tuple[str, pd.DataFrame]],
) -> Tuple[Dict, List[Dict]]:
    artifact_manifest: Dict[str, Dict] = {}
    files: List[Dict] = []
    for name in sorted(artifacts):
        kind, frame = artifacts[name]
        keys = PRIMARY_KEYS[name]
        frame = frame.sort_values(keys, kind="mergesort").reset_index(drop=True)
        _assert_primary_key(frame, name)
        date_column = "trade_date" if "trade_date" in frame.columns else (
            "cal_date" if "cal_date" in frame.columns else None
        )
        chunks: List[Tuple[Optional[str], pd.DataFrame]] = []
        if date_column is not None and not frame.empty:
            years = frame[date_column].astype("string").str[:4]
            for year in sorted(years.drop_duplicates().tolist()):
                chunks.append((str(year), frame.loc[years == year].reset_index(drop=True)))
        else:
            chunks.append((None, frame))
        schema = None
        artifact_files = []
        for year, chunk in chunks:
            base = "tables" if kind == "table" else "views"
            if year is None:
                relative = Path(base) / name / "part-00000.parquet"
            else:
                relative = Path(base) / name / f"year={year}" / "part-00000.parquet"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            chunk.to_parquet(
                path,
                index=False,
                compression="zstd",
                row_group_size=100_000,
            )
            parquet_schema = arrow_schema_descriptor(pq.ParquetFile(path).schema_arrow)
            if schema is None:
                schema = parquet_schema
            elif schema != parquet_schema:
                raise DatasetPackageError(f"{name} partition schemas differ")
            entry = {
                "path": relative.as_posix(),
                "artifact": name,
                "partition": {} if year is None else {"year": year},
                "rows": int(len(chunk)),
                "bytes": int(path.stat().st_size),
                "sha256": _file_sha256(path),
            }
            files.append(entry)
            artifact_files.append(entry["path"])
        artifact_manifest[name] = {
            "kind": kind,
            "primary_key": keys,
            "sort_order": keys,
            "row_count": int(len(frame)),
            "file_count": len(artifact_files),
            "partitioning": [] if date_column is None or frame.empty else ["year"],
            "schema": schema,
            "files": artifact_files,
        }
    return artifact_manifest, sorted(files, key=lambda item: item["path"])


def _add_snapshot_chunk(states: Dict[str, Dict], table: str, frame: pd.DataFrame) -> None:
    frame = frame.sort_values(PRIMARY_KEYS[table], kind="mergesort")
    columns = list(frame.columns)
    dtypes = [str(dtype) for dtype in frame.dtypes]
    if table not in states:
        states[table] = {
            "columns": columns,
            "dtypes": dtypes,
            "rows": 0,
            "row_digest": hashlib.sha256(),
            "date_start": None,
            "date_end": None,
        }
    state = states[table]
    if state["columns"] != columns or state["dtypes"] != dtypes:
        raise DatasetPackageError(f"{table} source chunk schema changed")
    if not frame.empty:
        row_hashes = pd.util.hash_pandas_object(frame, index=False).to_numpy(
            dtype="<u8", copy=False
        )
        state["row_digest"].update(row_hashes.tobytes())
        date_column = "trade_date" if "trade_date" in frame.columns else (
            "cal_date" if "cal_date" in frame.columns else None
        )
        if date_column is not None:
            chunk_start = str(frame[date_column].min())
            chunk_end = str(frame[date_column].max())
            state["date_start"] = min(
                value for value in (state["date_start"], chunk_start) if value is not None
            )
            state["date_end"] = max(
                value for value in (state["date_end"], chunk_end) if value is not None
            )
    state["rows"] += int(len(frame))


def _finalize_source_snapshot(states: Dict[str, Dict]) -> Tuple[str, Dict]:
    overall = hashlib.sha256()
    tables = {}
    for table in TABLES:
        state = states[table]
        digest = hashlib.sha256()
        schema_payload = json.dumps(
            {
                "table": table,
                "columns": state["columns"],
                "dtypes": state["dtypes"],
                "rows": state["rows"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(schema_payload)
        digest.update(state["row_digest"].digest())
        table_hash = digest.hexdigest()
        coverage = (
            {"start": state["date_start"], "end": state["date_end"]}
            if state["date_start"] is not None else None
        )
        tables[table] = {
            "rows": state["rows"],
            "logical_sha256": table_hash,
            "date_coverage": coverage,
        }
        overall.update(table.encode("utf-8"))
        overall.update(bytes.fromhex(table_hash))
    return overall.hexdigest(), tables


def _append_artifacts(
    root: Path,
    manifest: Dict[str, Dict],
    files: List[Dict],
    empty_templates: Dict[str, Tuple[str, pd.DataFrame]],
    artifacts: Dict[str, Tuple[str, pd.DataFrame]],
) -> None:
    for name, (kind, frame) in artifacts.items():
        empty_templates.setdefault(name, (kind, frame.iloc[:0].copy()))
        if frame.empty:
            continue
        partial, new_files = _write_artifacts(root, {name: (kind, frame)})
        current = partial[name]
        if name not in manifest:
            manifest[name] = current
        else:
            target = manifest[name]
            if target["schema"] != current["schema"] or target["kind"] != current["kind"]:
                raise DatasetPackageError(f"{name} artifact chunks are incompatible")
            target["row_count"] += current["row_count"]
            target["file_count"] += current["file_count"]
            target["files"].extend(current["files"])
            target["files"].sort()
            if current["partitioning"]:
                target["partitioning"] = current["partitioning"]
        files.extend(new_files)


def _write_missing_empty_artifacts(
    root: Path,
    manifest: Dict[str, Dict],
    files: List[Dict],
    empty_templates: Dict[str, Tuple[str, pd.DataFrame]],
) -> None:
    expected = set(TABLES) | {"universe_history", "daily_hfq", "training_view_hfq"}
    missing = sorted(expected - set(manifest))
    for name in missing:
        if name not in empty_templates:
            raise DatasetPackageError(f"no schema template available for empty artifact: {name}")
        partial, new_files = _write_artifacts(root, {name: empty_templates[name]})
        manifest[name] = partial[name]
        files.extend(new_files)


def _year_periods(start: str, end: str) -> List[Tuple[str, str]]:
    periods = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        period_start = max(start, f"{year}0101")
        period_end = min(end, f"{year}1231")
        periods.append((period_start, period_end))
    return periods


def _assert_primary_key(frame: pd.DataFrame, name: str) -> None:
    keys = PRIMARY_KEYS[name]
    if any(key not in frame.columns for key in keys):
        raise DatasetPackageError(f"{name} missing primary key columns: {keys}")
    if frame[keys].isna().any().any() or frame.duplicated(keys).any():
        raise DatasetPackageError(f"{name} primary key is invalid: {keys}")


def _code_version() -> str:
    repository = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return f"{commit}-dirty" if dirty else commit
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
