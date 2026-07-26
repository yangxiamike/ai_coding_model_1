# zer0share 标准日频截面训练基础包

## 主流程：数据方构建并交付，合作方只读

本仓库定义并版本化维护 canonical preset：
`ashare_daily_cross_section` v1.0.0。数据方按该 preset 构建完整目录并整体交付；合作方日常不选股票池、表、复权或清洗规则，也不查询 zer0share。

```python
from data import open_dataset

package = open_dataset("/delivered/ashare_daily_cross_section_v1/<dataset_id>")
train_df = package.read_split("train")
validation_df = package.read_split("validation")
test_df = package.read_split("test")
```

交付物是整个 `<dataset_id>/` 目录，包含 canonical panel、八张源表、三个
split 边界、manifest、字段 schema 和全部 Parquet 文件校验和。目录可以复制或传输到另一台机器；不要只发送其中部分文件。

`open_dataset()` 会在返回句柄前完成完整性与兼容性校验。它只读取该目录，不导入、不连接 zer0share，也不回源、同步或修改文件。

返回值是按 `(trade_date, ts_code)` 稳定排序的 pandas DataFrame。这里不生成模型特征、标签、张量、PyTorch Dataset 或 DataLoader。

## 可选流程：一键复现或更新

需要独立复现时，合作方仍无需理解数据表选择，只提供本机 zer0share 配置与输出目录：

```python
from data import build_standard_dataset

package_path = build_standard_dataset(
    config_path="/local/private/zer0share-config.toml",
    output_dir="/local/dataset-packages",
)
```

等价命令：

```bash
python3.11 -m data.dataset_package.cli build-standard \
  --config-path /local/private/zer0share-config.toml \
  --output-dir /local/dataset-packages
```

zer0share 仅在 build/reproduce/update 阶段需要。得到相同 dataset ID 表示逻辑 preset 与规范化源快照一致；源快照变化会产生新 ID 和新目录，不覆盖旧包。

## 前置条件与边界

- 运行时统一为 Python 3.11。
- 双方各自安装、配置和维护 zer0share；模型仓库不携带 zer0share 数据库或真实数据包。
- builder 只调用 `from zer0share import pro_api` 和八个只读查询方法，不调用同步、更新、下载或回源接口。
- zer0share `config_path`、token、密码、输出绝对路径不写入 manifest，也不参与 spec hash 或 dataset ID。
- 构建/复现/更新阶段才需要 zer0share。`open_dataset` 和 `read_split` 完全离线，不导入、不连接 zer0share。

依赖由使用方安装：

```bash
python3.11 -m pip install -r requirements.txt
```

zer0share 是双方独立维护的外部前置条件，不作为公开 PyPI 依赖写进本仓库 requirements。安装后可只验证 client 能打开：

```python
from zer0share import pro_api
client = pro_api(config_path="/local/private/zer0share-config.toml")
```

## canonical preset v1 数据选择

版本化定义同时存在于代码 `standard_daily_spec()` 和
`data/dataset_package/standard_daily_v1.yaml`：

- preset 名称：`ashare_daily_cross_section`，preset 版本 `1.0.0`；实际 dataset/目录名称为 `ashare_daily_cross_section_v1`，dataset schema 为 `1.0.0`。
- 日期覆盖：2010-01-01 至 2025-12-31，端点包含。
- 股票池：SSE、SZSE、BSE 全部历史时点已上市 A 股；由交易日与 `list_date/delist_date` 构造，不从有行情的股票反推，因此无幸存者偏差。北交所股票最早从 2021-11-15 开市日起进入股票池。
- 八表：`stock_basic`、`trade_cal`、`daily`、`adj_factor`、`daily_basic`、`stock_st`、`suspend_d`、`stk_limit`。
- 状态：ST、停牌、触及涨跌停股票不删除，只附布尔标记。
- 缺失：历史时点已上市但当日无日线仍保留，价格为空；价格、状态和复权因子均不前向填充。
- 原始层：`daily` 保存统一字段/dtype 后的未复权日线，`adj_factor` 单独保存。
- HFQ：`open/high/low/close/pre_close × 当日 adj_factor`；`change/pct_chg` 按复权后的 close/pre_close 重算，`vol/amount` 保持源值。
- 默认消费视图：`training_view_hfq`。
- splits：train `20100101..20221230`，validation `20230201..20231229`，test `20240201..20251231`。区间端点包含且互不重叠，间隔预留给后续标签逻辑。

训练侧生成标签时仍需按具体标签最大前瞻窗口检查 split 间隔，本包不替训练侧决定标签泄漏边界。

## DataFrame 契约

`training_view_hfq` 的逻辑主键为 `(trade_date, ts_code)`，日期是 `YYYYMMDD` 字符串，价格/估值/复权字段是 float64，状态字段是非空 bool。重要状态列：

- `is_listed`：该交易日处于上市区间。
- `has_daily` / `has_adj_factor` / `has_daily_basic`：当日源表是否有对应行。
- `is_st` / `is_suspended`：当日状态。
- `is_at_up_limit` / `is_at_down_limit`：当日收盘价是否触及对应限制价。
- `raw_up_limit` / `raw_down_limit`：未复权限制价，仅用于状态追溯；不要与 HFQ 价格直接比较。

所有原始表和派生视图都可显式读取：

```python
raw_daily = package.read_frame("daily")
factors = package.read_frame("adj_factor")
hfq_daily = package.read_frame("daily_hfq")
universe = package.read_frame("universe_history")
```

没有任何价格或复权因子填充。某只停牌股缺日线时，默认视图仍有该主键，`is_suspended=True`、`has_daily=False`，价格为缺失值。

## 不可变目录与 manifest

```text
<output_dir>/
  ashare_daily_cross_section_v1/
    <dataset_id>/
      manifest.json
      tables/
        stock_basic/...
        trade_cal/year=YYYY/...
        daily/year=YYYY/...
        adj_factor/year=YYYY/...
        daily_basic/year=YYYY/...
        stock_st/year=YYYY/...
        suspend_d/year=YYYY/...
        stk_limit/year=YYYY/...
      views/
        universe_history/year=YYYY/...
        daily_hfq/year=YYYY/...
        training_view_hfq/year=YYYY/...
```

builder 按自然年读取六张大表、派生 panel 并立即写分区，避免全历史八表同时常驻内存；stock_basic 与 trade_cal 作为小型全局元数据常驻。它在输出目录同一文件系统的临时目录完成写入，流式累计源快照指纹，生成 manifest 后调用 loader 全量验证，再通过排他发布锁原子发布。相同 dataset ID 已存在时直接拒绝，绝不覆盖。

dataset ID 由数据集名称、schema 版本、无机器路径的 spec hash 和八表规范化源快照指纹组成。相同 preset、builder/schema 与源快照得到相同 ID 和逻辑行/schema；不同 PyArrow 版本不承诺 Parquet 文件逐字节一致。

manifest 记录 builder/git/zer0share 版本、UTC 构建时间、日期覆盖、股票池、splits、HFQ 契约、字段 schema、每文件/分区行数、字节数和 SHA256。`open_dataset` 会立即拒绝不兼容版本、缺失/额外文件、行数或 schema 不一致、文件校验和错误和不安全路径。

## 通用 spec（高级用法）

通用 `build_dataset(spec)` 仍保留给数据方开发新 preset，不是合作方默认入口：

```python
from data import build_dataset
path = build_dataset("data/dataset_package/standard_daily_v1.yaml")
```

改动任何逻辑字段会产生不同 spec hash 和 dataset ID。机器本地的 `output_dir` 与 `zer0share.config_path` 不属于逻辑字段。
