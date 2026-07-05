# 2026-07 归档（已完成事项详情）

> 从 WORKLOG.md 剥离的已完成/已调研事项，保留备查。WORKLOG.md 只留当前未决重点。

## [完成 2026-07-05] 数据模块双面重写
- 状态：按用户需求"import 即得数据（不感缓存/API）+ 保留同步接口（可选定期）"重写，双面共存设计落地并通过 baostock 600900 小时线 demo 验证。
- 设计：
  - **查询面 `provider`**（按需回源兜底，对上层无感）：调 `sync_jobs.run_table` 补缺 + `query_engine` 读返回 + `normalizer` 复权/聚合 → df。无 sync/refresh/status 入口。
  - **同步面 `sync_runner`**（函数式对称，可选定期）：调 `sync_jobs.run_table` 补缺不读返回。无内置调度器（环境无 apscheduler），定期由外部 cron/脚本，可有可无。
  - **共享内核 `sync_jobs`**：模块单例持有运行时状态（source/calendar/tasks/table_paths）+ `SyncTask`(dataclass) + `run_partition/date_section/snapshot_sync` + `run_table` 分派 + `refresh_trade_cal`。去掉旧 `runtime` 对象注入（耦合泄漏），改模块组合。
- 关键改动：
  - 重写 `provider.py`（旧版全 `pass`，现真正实现按需回源兜底；无状态门面，状态移至 sync_jobs）。
  - 重写 `sync_jobs.py`（去 runtime 注入，改模块组合；理清 fetch 绑定；加 `_ensure_trade_cal`/`refresh_trade_cal`/`run_table` 分派）。
  - 新建 `sync_runner.py`（对外同步面，函数式对称：minute/daily/daily_basic/adj_factor/stk_limit/stock_st/suspend_d/trade_cal/stock_list/all）。
  - 扩展 `partition_store.py` 加 date 单层分区（per 交易日横截面表 daily_basic/stock_st/suspend_d/stk_limit 用）。
  - 加 `meta_store.upsert_trade_cal`（区间刷新 upsert，不丢其他区间）。
  - 改 `query_engine.py` docstring（去旧"缺数据报错提示去 sync"，改为"由 provider 调用前保证已补缺"）。
  - 更新 `data_cli.py`/`__init__.py` re-export 查询面+同步面（`sync_` 前缀避免同名）。
  - `config.yaml` source 改 baostock（tushare token 占位不可用），加 exchange/basic_sec_type，删 minute_freq。
  - 重写 `data/README.md`（双面设计）；根 README §5.1/§7、MEMORY 同步。
- 验证：`compileall` + `import data` 通过；`tmp_test.py` baostock 查 600900 近一周小时线，5 交易日 × 6 bar = 30 行，数据正常。
- 推翻旧决策：MEMORY 原"删 sync_runner，无 sync 入口" → 现双面共存，sync_runner 重新作为对外同步面。

## [完成 2026-07-05] data 模块按需回源 + 本地缓存（被双面重写覆盖，留作决策脉络）
- 核心契约：上层只管"要数据"，provider 内部查本地缺口 → 缺则回源拉取 → 归一化 → 落库 → 更新进度 → 读本地返回，命中不回源。
- 触发：用户明确"外部只管要数据，本地有从本地拿，没的请求接口拿，拿到了存本地，客户端只感知拉数据一件事"。
- 后续在双面重写中扩展为"查询面 + 同步面"共存（见上条）。

## [完成 2026-07-04] data 模块去 init 体系（消除 Class 单例残留）
- 删除 `provider.init/is_initialized`、`meta_store.init/is_initialized/init_schema`、`sync_runner.init/is_initialized`；改为各模块内部 `_ensure_ready`/`_ensure_conn` 惰性组装，公开函数首调触发。
- 新增 `data/config.py`（模块单例）：`__file__` 自定位同层 config.yaml，import 时读缓存，暴露 `get/cfg/reload/module_dir`；其他模块经此取配置，不感知文件位置、不依赖 cwd。
- 相对路径（data_dir/db_path）相对 data 目录解析（`config.module_dir()`）。
- `config.yaml` 加 `source: tushare` 字段（换源只改值 + 新增 datasource 实现）。
- `calendar.TradingCalendar.__init__` docstring 去"前置 meta_store.init()"。
- 同步 `data/README.md` §2/§4/§5/§6/§7、`data_cli`/`__init__` 导出与示例去 init。
- 设计教训与高内聚低耦合四条自检已写入 `MEMORY.md`。
- 验证：`compileall` + `import data` 通过；`init`/`is_initialized` 已从 provider/meta_store/sync_runner 全部清除，`config.get("data.source")` 可读。

## [完成 2026-07-03] data 模块按 AGENTS.md §6 模块模式重构（消除多余 Class）
- 转 module functions + 模块级状态：`meta_store`(MetaStore) / `query_engine`(ParquetQueryEngine) / `partition_store`(PartitionStore, table_dir 作参数) / `snapshot_store`(SnapshotStore, file_path 作参数) / `sync_runner`(SyncRuntime+SyncRunner) / `provider`(DataProvider+get_provider → `init`+模块函数)。
- 保留 Class（多态/dataclass）：`calendar`(TradingCalendar/AlwaysOpenCalendar) / `datasource.tushare|binance`(TushareSource/BinanceSource) / `datasource.interface`(DataSource/AShareDataSource Protocol + StandardBar) / `sync_jobs`(SyncTask dataclass)。
- `calendar.TradingCalendar.__init__` 改为直接调 `meta_store` 模块函数（去注入）。
- `data_cli`/`__init__` 导出改为 re-export `provider` 模块函数；用法 `from data import provider; provider.init(...); provider.daily(...)`。
- 同步 `data/README.md` §2/§4/§5；验证 `compileall` + `import data` 通过，剩余 Class 全部为多态/记录型。

## [完成 2026-07-02] data 模块按 AGENTS.md 模块规范重构（功能签名不变）
- 新增 `data_cli.py` 统一入口（re-export DataProvider/契约/常量）+ `data/config.yaml`（与 _cli 平铺）。
- Domain 平铺：`normalizer.py`/`query_engine.py`/`meta_store.py`/`partition_store.py`/`snapshot_store.py`/`sync_jobs.py`/`sync_runner.py`。
- Adaptor：`datasource/`（interface.py 接口契约 + tushare.py/binance.py 实现），tushare/binance 是同一 adaptor 的不同实现。
- 删除旧子包 `sources/`/`storage/`/`query/`/`sync/`；更新 data/README.md §2/§7/§13、根 README §4。
- 验证：`compileall` + `import data`/`data.data_cli` 通过。

## zer0share 调研结论（参考用，不复用代码）
- 路径：`/media/xavier/Samsumg/codes/zer0share`（本地，刚 clone，干净源码，无 data/ db/ venv）。
- 架构：Tushare→fetcher；行情按 `date=YYYYMMDD/data.parquet` 分区；DuckDB 只存 `sync_meta`(表→最后同步日) + `trade_cal`(交易日历)；查询用 DuckDB `read_parquet(hive_partitioning=true)` 谓词下推返回 df。
- 关键文件：
  - `api.py`：查询门面 `LocalPro`（Tushare-like，`pro_api()` 工厂）。
  - `storage.py`：`MetaStore`(DuckDB 元数据) / `DailyPartitionStore`(按日分区) / `SnapshotStore`(单文件快照) / `IndexWeightStore`。
  - `query/repository.py`：`ParquetQueryEngine`(谓词下推) + `BaseParquetRepository` / `DailyPartitionRepository`。
  - `fetcher.py`：`TushareFetcher`（封装 stock_basic/daily/adj_factor/daily_basic/stock_st/suspend_d/stk_limit/index_*/fut_*/opt_*/sw_*/ci_*）。
  - `sync/_jobs.py`：`DailySyncJob`(增量按交易日循环+重试 5/15/45s) / `SnapshotSyncJob`(全量覆盖)。
  - `universe.py`：股票池过滤（剔除 ST/停牌/低流动性/低市值/一字涨跌停），只覆盖 A 股普通股。
  - `schema.py`：字段定义（照搬 tushare 标准字段，已列全 BASIC_COLS/DAILY_COLS/ADJ_FACTOR_COLS/DAILY_BASIC_COLS 等）。
  - `config.py`：toml + dataclass `Config`（我们改 yaml）。
- 配置/依赖：toml + loguru + apscheduler（我们改 yaml + 标准 logging + 手动调度）。

## 标的范围 gap（需扩展，待第一版标的范围拍板后处理）
zer0share fetcher 只覆盖：股票、指数、期货、期权。
未覆盖（证券账户可买但需扩展）：ETF/LOF(`fund_basic`/`fund_daily`/`fund_adj`)、可转债(`cb_basic`/`cb_daily`)、基金、逆回购。
