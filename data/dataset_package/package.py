"""不可变数据包的只读校验与 DataFrame 读取接口。"""
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd
import pyarrow.parquet as pq

from data.dataset_package.schema import (
    FLOAT_COLUMNS,
    INTEGER_COLUMNS,
    MANIFEST_VERSION,
    PRIMARY_KEYS,
    SCHEMA_VERSION,
    TABLES,
)

_VIEW_NAMES = {"universe_history", "daily_hfq", "training_view_hfq"}


class DatasetPackageError(RuntimeError):
    """数据包不存在、不兼容或完整性校验失败。"""


class DatasetPackage:
    """已完整校验的数据包只读句柄。"""

    def __init__(self, path: Path, manifest: Dict) -> None:
        self.path = path
        self.manifest = manifest

    @property
    def dataset_id(self) -> str:
        return str(self.manifest["dataset_id"])

    @property
    def default_view(self) -> str:
        return str(self.manifest["default_view"])

    @property
    def available_frames(self) -> List[str]:
        return sorted(self.manifest["artifacts"])

    def read_frame(
        self,
        name: Optional[str] = None,
        columns: Optional[Sequence[str]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        ts_codes: Optional[Sequence[str]] = None,
    ) -> pd.DataFrame:
        """读取一个表/视图；默认读取 manifest 声明的 HFQ 训练视图。"""
        artifact_name = name or self.default_view
        artifact = self.manifest["artifacts"].get(artifact_name)
        if artifact is None:
            raise KeyError(
                f"unknown frame {artifact_name!r}; available={self.available_frames}"
            )
        available_columns = [field["name"] for field in artifact["schema"]]
        if columns is not None:
            unknown = sorted(set(columns) - set(available_columns))
            if unknown:
                raise KeyError(f"{artifact_name} unknown columns: {unknown}")
            output_columns = list(columns)
        else:
            output_columns = available_columns
        internal_columns = list(output_columns)
        for required in artifact["sort_order"]:
            if required not in internal_columns:
                internal_columns.append(required)
        for required in ("trade_date", "cal_date"):
            if required in available_columns and required not in internal_columns:
                internal_columns.append(required)
        if ts_codes is not None and "ts_code" in available_columns:
            if "ts_code" not in internal_columns:
                internal_columns.append("ts_code")
        files = _artifact_files(self.manifest["files"], artifact_name, start, end)
        parquet_filters = []
        date_filter_column = "trade_date" if "trade_date" in available_columns else (
            "cal_date" if "cal_date" in available_columns else None
        )
        if date_filter_column is not None and start is not None:
            parquet_filters.append((date_filter_column, ">=", str(start)))
        if date_filter_column is not None and end is not None:
            parquet_filters.append((date_filter_column, "<=", str(end)))
        if ts_codes is not None and "ts_code" in available_columns:
            parquet_filters.append(("ts_code", "in", list(ts_codes)))
        frames = [
            pq.read_table(
                self.path / item["path"],
                columns=internal_columns,
                filters=parquet_filters or None,
            ).to_pandas()
            for item in files
        ]
        if not frames:
            return pd.DataFrame(columns=output_columns)
        frame = pd.concat(frames, ignore_index=True)
        date_column = "trade_date" if "trade_date" in frame.columns else (
            "cal_date" if "cal_date" in frame.columns else None
        )
        if date_column is not None:
            if start is not None:
                frame = frame[frame[date_column] >= str(start)]
            if end is not None:
                frame = frame[frame[date_column] <= str(end)]
        if ts_codes is not None:
            if "ts_code" not in frame.columns:
                raise ValueError(f"{artifact_name} has no ts_code column")
            frame = frame[frame["ts_code"].isin(list(ts_codes))]
        sort_columns = [
            column for column in artifact["sort_order"] if column in frame.columns
        ]
        if sort_columns:
            frame = frame.sort_values(sort_columns, kind="mergesort")
        return frame.loc[:, output_columns].reset_index(drop=True)

    read = read_frame

    def read_split(
        self,
        split: str,
        name: Optional[str] = None,
        columns: Optional[Sequence[str]] = None,
        ts_codes: Optional[Sequence[str]] = None,
    ) -> pd.DataFrame:
        """按 manifest 固化的 split 读取；默认返回标准 HFQ 截面视图。"""
        bounds = self.manifest.get("splits", {}).get(split)
        if bounds is None:
            available = sorted(self.manifest.get("splits", {}))
            raise KeyError(f"unknown split {split!r}; available={available}")
        return self.read_frame(
            name=name,
            columns=columns,
            start=bounds["start"],
            end=bounds["end"],
            ts_codes=ts_codes,
        )


def open_dataset(path: Path) -> DatasetPackage:
    """只读打开并立即校验 manifest、schema、文件、行数与 SHA256。"""
    root = Path(path)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise DatasetPackageError(f"manifest not found: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetPackageError("manifest.json is not valid JSON") from exc
    _validate_manifest(root, manifest)
    return DatasetPackage(root, manifest)


def _validate_manifest(root: Path, manifest: Dict) -> None:
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise DatasetPackageError(
            f"unsupported manifest_version: {manifest.get('manifest_version')}"
        )
    if manifest.get("dataset_schema_version") != SCHEMA_VERSION:
        raise DatasetPackageError(
            f"unsupported dataset_schema_version: {manifest.get('dataset_schema_version')}"
        )
    logical_spec = manifest.get("spec")
    if not isinstance(logical_spec, dict):
        raise DatasetPackageError("manifest spec must be a mapping")
    actual_spec_hash = _json_sha256(logical_spec)
    if manifest.get("spec_hash") != actual_spec_hash:
        raise DatasetPackageError("manifest spec_hash mismatch")
    source_snapshot = manifest.get("source_snapshot")
    if not isinstance(source_snapshot, dict) or not _is_sha256(source_snapshot.get("fingerprint")):
        raise DatasetPackageError("source snapshot fingerprint is invalid")
    expected_id = make_dataset_id(
        str(logical_spec.get("name", "")),
        str(manifest["dataset_schema_version"]),
        str(manifest["spec_hash"]),
        str(source_snapshot["fingerprint"]),
    )
    if manifest.get("dataset_id") != expected_id:
        raise DatasetPackageError("dataset_id mismatch")
    expected_mirrors = {
        "name": logical_spec.get("name"),
        "default_view": logical_spec.get("default_view"),
        "date_coverage": logical_spec.get("date_range"),
        "universe_rule": logical_spec.get("universe"),
        "splits": logical_spec.get("splits"),
        "adjustment": logical_spec.get("adjustment"),
    }
    for field, expected in expected_mirrors.items():
        if manifest.get(field) != expected:
            raise DatasetPackageError(f"manifest {field} conflicts with logical spec")

    artifacts = manifest.get("artifacts")
    files = manifest.get("files")
    if not isinstance(artifacts, dict) or not isinstance(files, list):
        raise DatasetPackageError("manifest artifacts/files are invalid")
    if manifest.get("default_view") not in artifacts:
        raise DatasetPackageError("default_view is not present in artifacts")
    if set(artifacts) != set(TABLES) | _VIEW_NAMES:
        raise DatasetPackageError("artifact set is incompatible with schema v1")

    expected_paths = set()
    per_artifact_rows: Dict[str, int] = {name: 0 for name in artifacts}
    per_artifact_files: Dict[str, int] = {name: 0 for name in artifacts}
    for item in files:
        _validate_file_entry(root, item, artifacts)
        relative = str(item["path"])
        if relative in expected_paths:
            raise DatasetPackageError(f"duplicate manifest file path: {relative}")
        expected_paths.add(relative)
        artifact_name = str(item["artifact"])
        per_artifact_rows[artifact_name] += int(item["rows"])
        per_artifact_files[artifact_name] += 1
    actual_paths = {
        path.relative_to(root).as_posix() for path in root.rglob("*.parquet")
    }
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        unexpected = sorted(actual_paths - expected_paths)
        raise DatasetPackageError(
            f"package file set mismatch; missing={missing}, unexpected={unexpected}"
        )

    for name, artifact in artifacts.items():
        primary_key = artifact.get("primary_key")
        if primary_key != PRIMARY_KEYS.get(name):
            raise DatasetPackageError(f"{name} incompatible primary key")
        schema = artifact.get("schema")
        if not isinstance(schema, list) or not schema:
            raise DatasetPackageError(f"{name} schema is empty")
        schema_names = [field.get("name") for field in schema]
        if any(key not in schema_names for key in primary_key):
            raise DatasetPackageError(f"{name} schema missing primary key")
        for field in schema:
            expected_type = _expected_arrow_type(field["name"])
            if field.get("type") != expected_type:
                raise DatasetPackageError(
                    f"{name}.{field['name']} incompatible type: "
                    f"{field.get('type')} != {expected_type}"
                )
        if int(artifact.get("row_count", -1)) != per_artifact_rows[name]:
            raise DatasetPackageError(f"{name} row_count mismatch")
        if int(artifact.get("file_count", -1)) != per_artifact_files[name]:
            raise DatasetPackageError(f"{name} file_count mismatch")
        declared_files = sorted(artifact.get("files", []))
        actual_artifact_files = sorted(
            item["path"] for item in files if item["artifact"] == name
        )
        if declared_files != actual_artifact_files:
            raise DatasetPackageError(f"{name} artifact file list mismatch")
        expected_partitioning = (
            ["year"]
            if any(
                item.get("partition", {}).get("year") is not None
                for item in files
                if item["artifact"] == name
            )
            else []
        )
        if artifact.get("partitioning") != expected_partitioning:
            raise DatasetPackageError(f"{name} partitioning declaration mismatch")
        expected_kind = "table" if name in TABLES else "view"
        if artifact.get("kind") != expected_kind:
            raise DatasetPackageError(f"{name} artifact kind mismatch")
        if name in TABLES:
            expected_columns = logical_spec["tables"][name]
            if schema_names != expected_columns:
                raise DatasetPackageError(f"{name} schema conflicts with logical spec")

    _validate_view_schemas(artifacts, logical_spec)

    source_tables = source_snapshot.get("tables")
    expected_source_tables = set(manifest["spec"].get("tables", {}))
    if not isinstance(source_tables, dict) or set(source_tables) != expected_source_tables:
        raise DatasetPackageError("source snapshot table set mismatch")
    for name, snapshot in source_tables.items():
        if int(snapshot.get("rows", -1)) != int(artifacts[name]["row_count"]):
            raise DatasetPackageError(f"{name} source snapshot row count mismatch")
        if not _is_sha256(snapshot.get("logical_sha256")):
            raise DatasetPackageError(f"{name} source snapshot hash is invalid")
    recomputed_fingerprint = _snapshot_fingerprint(source_tables)
    if source_snapshot["fingerprint"] != recomputed_fingerprint:
        raise DatasetPackageError("source snapshot fingerprint mismatch")


def _validate_file_entry(root: Path, item: Dict, artifacts: Dict) -> None:
    relative = str(item.get("path", ""))
    pure = PurePosixPath(relative)
    if not relative or pure.is_absolute() or ".." in pure.parts or pure.suffix != ".parquet":
        raise DatasetPackageError(f"unsafe package path: {relative}")
    artifact_name = str(item.get("artifact", ""))
    if artifact_name not in artifacts:
        raise DatasetPackageError(f"file references unknown artifact: {artifact_name}")
    path = root.joinpath(*pure.parts)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise DatasetPackageError(f"package path must not contain symlinks: {relative}")
    if not path.is_file():
        raise DatasetPackageError(f"package file missing: {relative}")
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise DatasetPackageError(f"package path escapes root: {relative}") from exc
    digest = _file_sha256(path)
    if digest != item.get("sha256"):
        raise DatasetPackageError(f"checksum mismatch: {relative}")
    if path.stat().st_size != int(item.get("bytes", -1)):
        raise DatasetPackageError(f"file size mismatch: {relative}")
    parquet = pq.ParquetFile(path)
    if parquet.metadata.num_rows != int(item.get("rows", -1)):
        raise DatasetPackageError(f"file row count mismatch: {relative}")
    actual_schema = arrow_schema_descriptor(parquet.schema_arrow)
    if actual_schema != artifacts[artifact_name].get("schema"):
        raise DatasetPackageError(f"Parquet schema mismatch: {relative}")
    _validate_partition(path, pure, item, parquet)


def _validate_partition(path: Path, pure: PurePosixPath, item: Dict, parquet) -> None:
    partition = item.get("partition")
    if not isinstance(partition, dict):
        raise DatasetPackageError(f"invalid partition metadata: {item.get('path')}")
    year = partition.get("year")
    path_years = [part[5:] for part in pure.parts if part.startswith("year=")]
    if year is None:
        if path_years:
            raise DatasetPackageError(f"partition/path mismatch: {item.get('path')}")
        return
    if path_years != [str(year)]:
        raise DatasetPackageError(f"partition/path mismatch: {item.get('path')}")
    schema_names = parquet.schema_arrow.names
    date_column = "trade_date" if "trade_date" in schema_names else (
        "cal_date" if "cal_date" in schema_names else None
    )
    if date_column is None:
        raise DatasetPackageError(f"year partition has no date column: {item.get('path')}")
    column_index = schema_names.index(date_column)
    stats_available = True
    for row_group_index in range(parquet.metadata.num_row_groups):
        statistics = parquet.metadata.row_group(row_group_index).column(column_index).statistics
        if statistics is None or not statistics.has_min_max:
            stats_available = False
            break
        if str(statistics.min)[:4] != str(year) or str(statistics.max)[:4] != str(year):
            raise DatasetPackageError(f"partition values mismatch: {item.get('path')}")
    if not stats_available:
        values = parquet.read(columns=[date_column]).column(0).to_pylist()
        if any(value is None or str(value)[:4] != str(year) for value in values):
            raise DatasetPackageError(f"partition values mismatch: {item.get('path')}")


def _validate_view_schemas(artifacts: Dict, logical_spec: Dict) -> None:
    schema_names = {
        name: [field["name"] for field in artifacts[name]["schema"]]
        for name in _VIEW_NAMES
    }
    if schema_names["universe_history"] != ["trade_date", "ts_code", "is_listed"]:
        raise DatasetPackageError("universe_history schema is incompatible with schema v1")
    expected_hfq = list(logical_spec["tables"]["daily"]) + ["adj_factor"]
    if schema_names["daily_hfq"] != expected_hfq:
        raise DatasetPackageError("daily_hfq schema is incompatible with schema v1")
    required_panel = {
        "trade_date", "ts_code", "is_listed", "open", "high", "low", "close",
        "pre_close", "adj_factor", "has_daily", "has_adj_factor",
        "has_daily_basic", "is_st", "is_suspended", "raw_up_limit", "raw_down_limit",
        "is_at_up_limit", "is_at_down_limit",
    }
    if not required_panel.issubset(schema_names["training_view_hfq"]):
        raise DatasetPackageError("training_view_hfq schema is incompatible with schema v1")


def _snapshot_fingerprint(source_tables: Dict) -> str:
    digest = hashlib.sha256()
    for table in TABLES:
        digest.update(table.encode("utf-8"))
        digest.update(bytes.fromhex(source_tables[table]["logical_sha256"]))
    return digest.hexdigest()


def _expected_arrow_type(column: str) -> str:
    if (
        column == "is_listed"
        or column.startswith("has_")
        or column.startswith("is_at_")
        or column in {"is_st", "is_suspended"}
    ):
        return "bool"
    if column in FLOAT_COLUMNS:
        return "double"
    if column in INTEGER_COLUMNS:
        return "int64"
    return "string"


def _artifact_files(
    files: Iterable[Dict],
    artifact_name: str,
    start: Optional[str],
    end: Optional[str],
) -> List[Dict]:
    selected = []
    start_year = str(start)[:4] if start else None
    end_year = str(end)[:4] if end else None
    for item in files:
        if item["artifact"] != artifact_name:
            continue
        year = item.get("partition", {}).get("year")
        if year is not None and start_year is not None and str(year) < start_year:
            continue
        if year is not None and end_year is not None and str(year) > end_year:
            continue
        selected.append(item)
    return sorted(selected, key=lambda item: item["path"])


def arrow_schema_descriptor(schema) -> List[Dict]:
    return [
        {"name": field.name, "type": str(field.type), "nullable": bool(field.nullable)}
        for field in schema
    ]


def make_dataset_id(
    name: str,
    schema_version: str,
    spec_hash: str,
    source_fingerprint: str,
) -> str:
    version = schema_version.replace(".", "_")
    return f"{name}-{version}-{spec_hash[:12]}-{source_fingerprint[:12]}"


def _json_sha256(value: Dict) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
