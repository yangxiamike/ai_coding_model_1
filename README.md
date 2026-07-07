# 量化交易系统 设计文档 v1

## 1. 项目定位

基于用户已有的序列模型，构建本地量化交易系统，产出 A 股买卖信号，由用户**手动**执行下单获利。系统不接券商交易 API，输出面向人读的买卖清单。

四个模块：数据模块、离线训练模块、回测模块、实时预估模块。

## 2. 环境约束（不可违背）

- 解释器：仅 `/root/anaconda3/envs/ldm/bin/python3.8`（Python 3.8.5），禁止新建环境、禁止 `pip install`。
- 已装：duckdb 1.3.2、tushare 1.4.29、pyarrow 16.1、pandas 1.3.5、numpy 1.24、torch 2.3.1+cu121(GPU)、click 8.1、yaml。
- 缺失：loguru、apscheduler、tensorflow → 日志用标准库 `logging`；第一版同步靠手动/脚本触发，不做定时调度。

## 3. 技术栈

- 数据：Tushare Pro（付费）或 Baostock（免费）拉取 → Parquet 分区存储 → DuckDB 查询（元数据 + 直读 Parquet 谓词下推）。
- 训练/推断：torch 2.3.1（GPU）。
- 参考 `/media/xavier/Samsumg/codes/zer0share` 的架构与字段定义，但因 zer0share 需 py3.11+ 且本机无产物/venv，**在本项目 3.8 环境重写，不复用其代码**。

## 4. 整体架构

依赖方向单向：`data` 为底座；`algo` 是核心算法模块（不依赖 `data`，对外暴露预测类契约 + `DataRequirement` 数据需求声明，业务壳据此取数喂 `predict`）；`training` / `live_predict` / `backtest` 依赖 `data` + `algo`（取数 + 调算法）；`common` 被所有模块依赖。算法以**注入**方式接入预估与回测，不绑定具体框架。

```
agent_coding/
├── config.yaml          # 全局参数（库/回测/模型路径；各模块配置见各自 config.yaml）
├── common/              # 日志、配置加载、日历等公共工具
├── data/                # 数据模块（详见 data/README.md）
├── algo/                # 算法模块（核心，预测类契约，详见 algo/README.md）
├── training/            # 离线训练模块（调 algo）
├── backtest/            # 回测模块
├── live_predict/        # 实时预估模块（调 algo）
├── MEMORY.md            # 长期记忆
├── worklog/             # 短期记忆（WORKLOG.md）
├── requirements.txt
└── README.md            # 本文件（架构总览）
```

## 5. 模块概览（职责 / 边界 / 数据来源 / 性能）

### 5.1 数据模块 `data/`
- **职责**：取（DataSource）、存（Parquet 分区）、查（DuckDB 直读 Parquet 谓词下推）、导出 df。**双面共存**：查询面 `provider` 按需回源兜底（缺则自动拉，对上层无感）；同步面 `sync_runner` 函数式对称可选预热（定期由外部 cron/脚本触发，模块不内置调度器）。
- **架构**：三段式 DataSource(可插拔) → normalizer(归一化) → 标准存储/查询(不感知数据源)；查询面与同步面共用 sync_jobs 补缺内核，差异仅在是否读本地返回。tushare + baostock 双实现，预留 binance。
- **粒度**：分钟线 1min + 日线，双粒度；北京时间整分钟右闭；5/15/30/60min 由最细粒度聚合不落库。
- **边界**：只做数据搬运与缓存。不做特征/策略/下单。复权与小时线聚合在查询层内存拼，不污染原始落库。查询面缺数据自动回源补齐，命中直读不回源。
- **来源**：Tushare Pro（付费）或 Baostock（免费），通过 `data/config.yaml` 的 `source` 字段切换。标的覆盖 A 股普通股，带 `sec_type`；预留 BTC。
- **性能**：单标的分钟序列 <100ms / 日线 <50ms；增量回填日线 10–30 分钟（受 Tushare 限速或 Baostock 免费接口）。
- 详见 `data/README.md`。

### 5.2 算法模块 `algo/`（核心）
- **职责**：把 OHLCV df 喂序列模型，输出"未来 k 步内涨/跌穿阈值"的概率。**核心模块，不走三层**：每类算法独立文件夹（含指标/特征/预处理/模型/训练/预测类），对外只暴露预测类契约（`__init__(model_file)` + `predict(df)` + `data_requirement` 成员变量）。指标库并入算法特征层。首实现双层 BertEncoder（参考 `transformer_user` BTC AUC 0.7）。
- **边界**：不取数、不下单、不撮合。不 import `data`——靠 `data_requirement` 声明需要哪些标的的哪些信息，由 `training`/`live_predict`/`backtest` 据此向 `data` 取数喂 `predict`，保证训练/推断/回测取数一致。
- **来源**：df 由业务壳从 `data` 取传入；模型文件由 `training` 调算法训练过程产出。
- **性能**：单次推断毫秒~秒级（窗长+模型层数决定）；训练时长由数据量+epoch 决定。
- 详见 `algo/README.md`。

### 5.3 离线训练模块 `training/`
- **职责**：从 `data` 取 df → 调 `algo/<算法>/train.py` 训练 → 落可复现模型文件（含 `DataRequirement` 数据口径）。是算法训练的薄业务壳（算法管特征/预处理/模型/训练循环，training 管取数 + 调度 + 落盘）。
- **边界**：不碰数据获取细节（`data` 管）、不碰算法实现（`algo` 管）、不碰实盘/回测撮合。
- **来源**：`data` 的 `export` 本地 Parquet 读盘 + `algo` 训练入口。
- **性能**：数据 IO 非瓶颈；瓶颈在 `algo` 训练时长（数据量+epoch 决定）。

### 5.4 回测模块 `backtest/`
- **职责**：用历史数据 + 一个策略契约，按 bar 推进模拟交易，产出净值曲线、交易明细、绩效指标（年化/回撤/夏普/胜率/换手）。
- **边界**：不训练、不下实盘单。策略为鸭子类型契约：`on_bar(bar, ctx) → 目标持仓权重`；撮合含佣金/印花税/滑点/T+1 成本模型。模型驱动的信号可包成 `Strategy` 复用回测。
- **来源**：`data` 历史行情，回测前一次性载入所需标的+区间。
- **性能**：全市场日线 30 年约 4000 万 bar，向量化撮合数分钟内跑完一轮；单标的策略秒级。

### 5.5 实时预估模块 `live_predict/`
- **职责**：`algo.load(model_file)` 加载预测类 → 读 `data_requirement` 向 `data` 取最新 bar + 历史窗口 → `predict` 出概率 → 转成给用户手动下单的清单（code / 买卖方向 / 数量 / 原因或得分）。是算法推断的薄业务壳。
- **边界**：不训练、不自动下单、不撮合。只做"加载预测类 → 按 data_requirement 取数 → predict → 信号 → 清单"。持仓输入由用户手动维护。
- **来源**：实时行情走 `data` 的增量更新 + 最新 bar 快照；历史窗口从本地库取；算法走 `algo.load` + `predict`。
- **性能**：盘中取最新 bar + 模型输入窗口（几十到几百根），`algo` 单次推断毫秒~秒级；全市场信号扫描 1–2 秒出清单。

## 6. 设计原则

- 高内聚低耦合，模块间依赖最小化。
- 组合优于继承（复用功能通过组合实现，禁用继承复用）。
- 鸭子类型：基于行为契约设计接口。
- 配置分离：参数进 `config.yaml`，禁止硬编码。
- 日志统一用标准库 `logging`（环境无 loguru）。

## 7. 待决策点（下次讨论）

1. 第一版 A 股标的范围（仅股票 / +ETF / +ETF+可转债 / 全可买含逆回购）。
2. Tushare 积分等级（分钟 `stk_mins` 需 ≥5000，决定可拉取的表）。
3. 成本模型参数（初始资金/佣金率/印花税/滑点/T+1）。
4. ~~序列模型本机路径~~（已定：参考 `transformer_user` 重写为 `algo` 模块，见 `algo/README.md`）。

> 频率与数据源已定：分钟 1min + 日线双粒度，baostock/tushare + duckdb，预留 BTC。数据模块已落地（双面共存：查询面按需回源兜底 + 同步面可选预热，见 `data/README.md`）。算法模块已设计（`algo` 纯内核 + training/live_predict 薄壳，见 `algo/README.md`）。本文档随讨论迭代。
