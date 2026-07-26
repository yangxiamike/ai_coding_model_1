import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pyarrow.parquet as pq

from data import build_standard_dataset, load_spec, open_dataset, standard_daily_spec
from data.dataset_package.package import DatasetPackageError, arrow_schema_descriptor
from data.dataset_package.zer0share_reader import DatasetSourceError, Zer0shareReader


class FakePro:
    zer0share_version = "test-1.0"

    def __init__(self, reverse=False):
        self.calls = []
        self.frames = _source_frames()
        if reverse:
            self.frames = {
                name: frame.iloc[::-1].reset_index(drop=True)
                for name, frame in self.frames.items()
            }

    def _read(self, name, **kwargs):
        self.calls.append((name, dict(kwargs)))
        frame = self.frames[name].copy(deep=True)
        if name == "trade_cal":
            frame = frame[frame["exchange"] == kwargs["exchange"]]
        fields = kwargs.get("fields", "").split(",")
        offset = int(kwargs.get("offset", 0))
        limit = int(kwargs.get("limit", len(frame)))
        return frame.iloc[offset:offset + limit].loc[:, fields]

    def stock_basic(self, **kwargs):
        if kwargs.get("list_status", "sentinel") is not None:
            raise AssertionError("stock_basic must request all historical statuses")
        if "exchange" in kwargs:
            raise AssertionError("stock_basic full-market query must omit exchange")
        return self._read("stock_basic", **kwargs)

    def trade_cal(self, **kwargs):
        return self._read("trade_cal", **kwargs)

    def daily(self, **kwargs):
        return self._read("daily", **kwargs)

    def adj_factor(self, **kwargs):
        return self._read("adj_factor", **kwargs)

    def daily_basic(self, **kwargs):
        return self._read("daily_basic", **kwargs)

    def stock_st(self, **kwargs):
        return self._read("stock_st", **kwargs)

    def suspend_d(self, **kwargs):
        return self._read("suspend_d", **kwargs)

    def stk_limit(self, **kwargs):
        return self._read("stk_limit", **kwargs)


class DatasetPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "private" / "zer0share.toml"
        self.output_dir = self.root / "packages"

    def tearDown(self):
        self.temp.cleanup()

    def build(self, client=None):
        return build_standard_dataset(
            self.config_path,
            self.output_dir,
            client=client or FakePro(),
        )

    def test_builds_canonical_package_and_reads_complete_panel(self):
        client = FakePro()
        path = self.build(client)
        package = open_dataset(path)
        self.assertEqual(package.manifest["spec"]["preset"]["version"], "1.0.0")
        self.assertEqual(package.default_view, "training_view_hfq")
        self.assertEqual(package.manifest["splits"], {})
        self.assertEqual(
            set(name for name, _ in client.calls),
            {
                "stock_basic", "trade_cal", "daily", "adj_factor",
                "daily_basic", "stock_st", "suspend_d", "stk_limit",
            },
        )

        raw = package.read_frame("daily")
        hfq = package.read_frame("daily_hfq")
        raw_open = raw.loc[
            (raw["trade_date"] == "20240202") & (raw["ts_code"] == "000001.SZ"),
            "open",
        ].item()
        hfq_open = hfq.loc[
            (hfq["trade_date"] == "20240202") & (hfq["ts_code"] == "000001.SZ"),
            "open",
        ].item()
        self.assertEqual(raw_open, 11.0)
        self.assertEqual(hfq_open, 22.0)

        panel = package.read()
        suspended = panel[
            (panel["trade_date"] == "20240202")
            & (panel["ts_code"] == "600000.SH")
        ].iloc[0]
        self.assertTrue(suspended["is_suspended"])
        self.assertFalse(suspended["has_daily"])
        self.assertTrue(suspended["has_adj_factor"])
        self.assertEqual(suspended["adj_factor"], 2.0)
        self.assertTrue(pd.isna(suspended["open"]))
        self.assertEqual(len(panel), 9)
        self.assertEqual(
            list(panel[["trade_date", "ts_code"]].itertuples(index=False, name=None)),
            sorted(panel[["trade_date", "ts_code"]].itertuples(index=False, name=None)),
        )
        projected = package.read(columns=["open"])
        self.assertEqual(len(projected), 9)
        self.assertEqual(list(projected.columns), ["open"])
        adjusted = hfq[
            (hfq["trade_date"] == "20240202") & (hfq["ts_code"] == "000001.SZ")
        ].iloc[0]
        self.assertEqual(adjusted["pre_close"], 21.0)
        self.assertEqual(adjusted["change"], 2.0)
        self.assertAlmostEqual(adjusted["pct_chg"], (23.0 / 21.0 - 1.0) * 100.0)
        not_limit = panel[
            (panel["trade_date"] == "20240202") & (panel["ts_code"] == "430001.BJ")
        ].iloc[0]
        self.assertFalse(not_limit["is_at_up_limit"])
        self.assertFalse(not_limit["is_suspended"])

    def test_manifest_redacts_machine_paths_and_records_choices(self):
        path = self.build()
        text = (path / "manifest.json").read_text(encoding="utf-8")
        self.assertNotIn(str(self.config_path), text)
        self.assertNotIn(str(self.output_dir), text)
        manifest = json.loads(text)
        self.assertEqual(
            set(manifest["spec"]["tables"]),
            {
                "stock_basic", "trade_cal", "daily", "adj_factor",
                "daily_basic", "stock_st", "suspend_d", "stk_limit",
            },
        )
        self.assertEqual(manifest["adjustment"]["formula"], "adjusted_price = raw_price * adj_factor")
        self.assertEqual(
            manifest["universe_rule"]["type"],
            "all_historical_a_shares",
        )

    def test_spec_hash_and_dataset_id_ignore_machine_paths_and_source_order(self):
        other_root = self.root / "other"
        left_spec = standard_daily_spec(self.config_path, self.output_dir)
        right_spec = standard_daily_spec(
            other_root / "config.toml",
            other_root / "packages",
        )
        self.assertEqual(left_spec.spec_hash, right_spec.spec_hash)
        left = self.build(FakePro())
        right = build_standard_dataset(
            other_root / "config.toml",
            other_root / "packages",
            client=FakePro(reverse=True),
        )
        self.assertEqual(left.name, right.name)

    def test_paginated_reader_produces_same_dataset_id(self):
        normal = self.build(FakePro())
        with patch.object(Zer0shareReader, "_PAGE_SIZE", 2):
            paginated = build_standard_dataset(
                self.config_path,
                self.root / "paginated",
                client=FakePro(reverse=True),
            )
        self.assertEqual(normal.name, paginated.name)

    def test_canonical_yaml_matches_code_preset(self):
        yaml_spec = load_spec(
            Path(__file__).parents[1]
            / "data"
            / "dataset_package"
            / "standard_daily_v1.yaml"
        )
        code_spec = standard_daily_spec(self.config_path, self.output_dir)
        self.assertEqual(yaml_spec.logical_dict(), code_spec.logical_dict())
        self.assertEqual(yaml_spec.spec_hash, code_spec.spec_hash)

    def test_existing_dataset_is_never_overwritten(self):
        path = self.build()
        manifest_before = (path / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(manifest_before, (path / "manifest.json").read_bytes())

    def test_open_rejects_tampered_file(self):
        path = self.build()
        package = open_dataset(path)
        first = path / package.manifest["files"][0]["path"]
        payload = bytearray(first.read_bytes())
        payload[-1] ^= 1
        first.write_bytes(payload)
        with self.assertRaisesRegex(DatasetPackageError, "checksum mismatch"):
            open_dataset(path)

    def test_open_rejects_missing_file_and_incompatible_version(self):
        path = self.build()
        package = open_dataset(path)
        first = path / package.manifest["files"][0]["path"]
        first.unlink()
        with self.assertRaisesRegex(DatasetPackageError, "package file missing"):
            open_dataset(path)

        other = build_standard_dataset(
            self.config_path,
            self.root / "incompatible",
            client=FakePro(),
        )
        manifest_path = other / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["dataset_schema_version"] = "2.0.0"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(DatasetPackageError, "unsupported dataset_schema_version"):
            open_dataset(other)

    def test_open_rejects_schema_change_even_with_updated_checksum(self):
        path = self.build()
        manifest_path = path / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        item = next(entry for entry in manifest["files"] if entry["artifact"] == "daily")
        parquet_path = path / item["path"]
        frame = pd.read_parquet(parquet_path).drop(columns="amount")
        frame.to_parquet(parquet_path, index=False)
        item["bytes"] = parquet_path.stat().st_size
        item["rows"] = len(frame)
        item["sha256"] = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        manifest["artifacts"]["daily"]["schema"] = arrow_schema_descriptor(
            pq.ParquetFile(parquet_path).schema_arrow
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(DatasetPackageError, "schema conflicts with logical spec"):
            open_dataset(path)

    def test_reader_rejects_duplicate_key_and_missing_factor(self):
        duplicate = FakePro()
        duplicate.frames["daily"] = pd.concat(
            [duplicate.frames["daily"], duplicate.frames["daily"].iloc[[0]]],
            ignore_index=True,
        )
        with self.assertRaisesRegex(DatasetSourceError, "duplicate primary key"):
            self.build(duplicate)

        missing = FakePro()
        missing.frames["adj_factor"] = missing.frames["adj_factor"].iloc[1:].reset_index(drop=True)
        with self.assertRaisesRegex(DatasetSourceError, "missing adj_factor"):
            build_standard_dataset(
                self.config_path,
                self.root / "missing-factor",
                client=missing,
            )

    def test_reader_rejects_missing_field_and_invalid_date(self):
        missing = FakePro()
        missing.daily = lambda **kwargs: missing.frames["daily"].drop(columns="close")
        with self.assertRaisesRegex(DatasetSourceError, "missing required fields"):
            self.build(missing)

        invalid = FakePro()
        invalid.frames["daily"].loc[0, "trade_date"] = "20240230"
        with self.assertRaisesRegex(DatasetSourceError, "daily.trade_date has invalid values"):
            build_standard_dataset(
                self.config_path,
                self.root / "invalid-date",
                client=invalid,
            )

        blank_list_date = FakePro()
        blank_list_date.frames["stock_basic"].loc[0, "list_date"] = ""
        with self.assertRaisesRegex(DatasetSourceError, "stock_basic.list_date"):
            build_standard_dataset(
                self.config_path,
                self.root / "blank-list-date",
                client=blank_list_date,
            )

        infinite_factor = FakePro()
        infinite_factor.frames["adj_factor"].loc[0, "adj_factor"] = float("inf")
        with self.assertRaisesRegex(DatasetSourceError, "adj_factor"):
            build_standard_dataset(
                self.config_path,
                self.root / "infinite-factor",
                client=infinite_factor,
            )

    def test_unknown_split_and_frame_fail_clearly(self):
        package = open_dataset(self.build())
        with self.assertRaisesRegex(KeyError, "unknown split"):
            package.read_split("future")
        with self.assertRaisesRegex(KeyError, "unknown frame"):
            package.read_frame("features")

    def test_delivered_directory_is_portable_and_open_is_zer0share_free(self):
        original = self.build()
        delivered = self.root / "delivered" / original.name
        delivered.parent.mkdir()
        shutil.copytree(original, delivered)
        sys.modules.pop("zer0share", None)
        package = open_dataset(delivered)
        self.assertNotIn("zer0share", sys.modules)
        self.assertEqual(len(package.read()), 9)
        from data.data_cli import open_dataset as cli_open_dataset
        self.assertEqual(cli_open_dataset(delivered).dataset_id, package.dataset_id)

    def test_committed_synthetic_demo_opens_offline(self):
        demo = (
            Path(__file__).parents[1]
            / "data"
            / "demo"
            / "ashare_daily_cross_section_demo_v1"
        )
        sys.modules.pop("zer0share", None)
        package = open_dataset(demo)
        panel = package.read()
        self.assertNotIn("zer0share", sys.modules)
        self.assertEqual(package.manifest["splits"], {})
        self.assertEqual(len(panel), 9)
        self.assertEqual(
            set(panel["ts_code"]),
            {"999001.SZ", "999002.SH", "999003.BJ"},
        )
        suspended = panel[
            (panel["trade_date"] == "20240104")
            & (panel["ts_code"] == "999002.SH")
        ].iloc[0]
        self.assertTrue(suspended["is_suspended"])
        self.assertFalse(suspended["has_daily"])
        self.assertTrue(pd.isna(suspended["open"]))

    def test_failed_final_validation_leaves_no_temp_or_final_package(self):
        output = self.root / "forced-failure"
        with patch(
            "data.dataset_package.builder.open_dataset",
            side_effect=DatasetPackageError("forced validation failure"),
        ):
            with self.assertRaisesRegex(DatasetPackageError, "forced validation failure"):
                build_standard_dataset(self.config_path, output, client=FakePro())
        dataset_root = output / "ashare_daily_cross_section_v1"
        if dataset_root.exists():
            self.assertEqual(list(dataset_root.iterdir()), [])

    def test_open_rejects_partition_metadata_tamper(self):
        path = self.build()
        manifest_path = path / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        item = next(entry for entry in manifest["files"] if entry["partition"])
        item["partition"]["year"] = "1999"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(DatasetPackageError, "partition/path mismatch"):
            open_dataset(path)


def _source_frames():
    codes = ["000001.SZ", "430001.BJ", "600000.SH"]
    dates = ["20240115", "20240201", "20240202"]
    stock_basic = pd.DataFrame([
        {
            "ts_code": "000001.SZ", "symbol": "000001", "name": "PingAn",
            "area": "Shenzhen", "industry": "Bank", "market": "Main",
            "exchange": "SZSE", "list_status": "L", "list_date": "19910403",
            "delist_date": "", "is_hs": "S",
        },
        {
            "ts_code": "430001.BJ", "symbol": "430001", "name": "Beijing",
            "area": "Beijing", "industry": "Tech", "market": "BSE",
            "exchange": "BSE", "list_status": "L", "list_date": "20200101",
            "delist_date": "", "is_hs": "N",
        },
        {
            "ts_code": "600000.SH", "symbol": "600000", "name": "Pudong",
            "area": "Shanghai", "industry": "Bank", "market": "Main",
            "exchange": "SSE", "list_status": "L", "list_date": "19991110",
            "delist_date": "", "is_hs": "H",
        },
    ])
    trade_cal_rows = [
        {"exchange": exchange, "cal_date": date, "is_open": 1, "pretrade_date": "20240131"}
        for exchange in ("SSE", "SZSE", "BSE")
        for date in dates
    ]
    trade_cal_rows.extend(
        {
            "exchange": exchange,
            "cal_date": date,
            "is_open": 0,
            "pretrade_date": "",
        }
        for exchange in ("SSE", "SZSE", "BSE")
        for date in ("20100101", "20251231")
    )
    trade_cal = pd.DataFrame(trade_cal_rows)
    daily_rows = []
    for code in codes:
        for date in dates:
            if code == "600000.SH" and date == "20240202":
                continue
            open_price = {
                "20240115": 9.0,
                "20240201": 10.0,
                "20240202": 11.0,
            }[date]
            daily_rows.append({
                "ts_code": code, "trade_date": date,
                "open": open_price, "high": open_price + 2,
                "low": open_price - 1, "close": open_price + 0.5,
                "pre_close": open_price - 0.5, "change": 1.0,
                "pct_chg": 10.0, "vol": 1000.0, "amount": 10000.0,
            })
    daily = pd.DataFrame(daily_rows)
    adj_factor = pd.DataFrame([
        {
            "ts_code": code,
            "trade_date": date,
            "adj_factor": 2.0 if date == "20240202" else 1.0,
        }
        for code in codes
        for date in dates
    ])
    daily_basic = pd.DataFrame([
        {
            "ts_code": code, "trade_date": date, "turnover_rate": 1.0,
            "turnover_rate_f": 1.1, "volume_ratio": 1.2, "pe": 10.0,
            "pe_ttm": 11.0, "pb": 1.0, "ps": 2.0, "ps_ttm": 2.1,
            "dv_ratio": 0.5, "dv_ttm": 0.6, "total_share": 100.0,
            "float_share": 80.0, "free_share": 70.0, "total_mv": 1000.0,
            "circ_mv": 800.0,
        }
        for code in codes
        for date in dates
    ])
    stock_st = pd.DataFrame([
        {
            "ts_code": "430001.BJ", "trade_date": "20240202", "name": "ST Beijing",
            "type": "S", "type_name": "ST",
        }
    ])
    suspend_d = pd.DataFrame([
        {
            "ts_code": "600000.SH", "trade_date": "20240202",
            "suspend_timing": "全天", "suspend_type": "S",
        },
        {
            "ts_code": "430001.BJ", "trade_date": "20240202",
            "suspend_timing": "盘中", "suspend_type": "R",
        },
    ])
    stk_limit = pd.DataFrame([
        {
            "ts_code": code, "trade_date": date, "pre_close": 10.0,
            "up_limit": 11.5 if code == "000001.SZ" and date == "20240202" else 99.0,
            "down_limit": 1.0,
        }
        for code in codes
        for date in dates
    ])
    return {
        "stock_basic": stock_basic,
        "trade_cal": trade_cal,
        "daily": daily,
        "adj_factor": adj_factor,
        "daily_basic": daily_basic,
        "stock_st": stock_st,
        "suspend_d": suspend_d,
        "stk_limit": stk_limit,
    }


if __name__ == "__main__":
    unittest.main()
