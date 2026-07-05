# 长期记忆

> 用户强调事项精简存入此文件；每次会话优先读取并遵守。

## 角色与目标
- 量化交易开发员（执行）vs 领导（指令）；遵循 AGENTS.md。
- 基于用户已有序列模型，构建本地量化系统产出 A 股买卖信号，供用户**手动**下单（不接券商 API）。四模块：数据 / 离线训练 / 回测 / 实时预估。

## 工作流
- 文档先行：设计一旦确认，README 等文档立即同步，不等提醒不追问。
- 需求确认 → 变更清单 → 执行；无授权不改代码；改后同步相关 README（仅变动部分）。

## 硬环境约束（不可违背）
- 仅 `/root/anaconda3/envs/ldm/bin/python3.8`（3.8.5）；禁 pip/conda/新环境。
- 已装：duckdb 1.3.2、tushare 1.4.29、pyarrow 16.1、pandas 1.3.5、numpy 1.24、torch 2.3.1+cu121、click 8.1、yaml。缺 loguru/apscheduler/tensorflow → 用标准 logging；第一版无自动调度。

## 数据模块（已落地 2026-07-05）
- 三段式：DataSource(可插拔) → normalizer(归一化) → 标准存储/查询(不感源)。tushare+baostock 双实现，预留 binance；换源改 config.yaml 的 source。
- 存储：行情 Parquet 双层 `ts_code=XXXX/date=YYYYMMDD`；横截面单层 `date=YYYYMMDD`；清单单文件。DuckDB 只存元数据(sync_meta+trade_cal)。查询 DuckDB 直读 Parquet 谓词下推，**只读本地不回源**。
- 双面：查询面 `provider`（按需回源兜底，对上层无感，缺则自动拉，命中直读，无 sync/refresh/status 入口）+ 同步面 `sync_runner`（函数式对称显式预热，外部 cron/脚本触发，模块不内置调度器）。二者共用 `sync_jobs` 补缺内核（run_table），差异仅在读本地返回。运行时状态由 sync_jobs 模块单例持有，provider/sync_runner 无状态门面。
- 频率：1min(最细,tushare)/5min(最细,baostock)+日线；5/15/30/60min 由最细聚合不落库。北京时间整分钟右闭（bar 时间戳=区间右端成交）；tushare 默认此语义，币安用 closeTime 对齐。
- 标的/日历抽象兼容 A股(交易日历+交易时段) 与 BTC(7×24)。
- Adaptor 结构：`datasource/` 是数据源这一**类** Adaptor 的文件夹，`interface.py` + tushare/baostock/binance 多实现共享契约（不是"唯一 Adaptor"，是一类多实现）。
- Baostock 限制：无 1min（最细 5min），不支持 A 股辅助表（daily_basic/stock_st/suspend_d/stk_limit），调用报 NotImplementedError。
- 参考 zer0share 架构，因 py3.11+ 在 3.8 重写，不复用代码。

## 代码与文档原则
- 高内聚低耦合、组合不继承、鸭子类型(Protocol)、配置进 config.yaml 禁硬编码、标准 logging、3.8 兼容(Optional[X])。
- §6 模块模式（Module as Singleton）：工具/单例用 .py 模块承载函数+状态，不写 Class；仅多态(日历/数据源)与 dataclass(StandardBar/SyncTask) 保留 Class。无 init/is_initialized 入口，状态模块级惰性组装。
- 配置位置属模块内部知识，用 Path(__file__).parent 自定位，禁作参数外泄给上层；override 走传已加载对象/dict，不传文件名。
- 根 README=架构总览；子 README=模块设计逻辑，固定结构：①CLI 层方法列表(每方法两句：需求/功能/输入/返回) ②Adaptor 种类与实现 ③Domain 各文件(概括功能+缺失后果，禁列全部函数名)+依赖 mermaid 图。
- 维护 requirements.txt。

## 设计自检（设计/写公共入口前必过）
- **自足+不泄漏**：模块自知的(配置位置/内部布局/启动步骤)不得向调用方要；公共签名只接业务语义(标的/区间/频率)，不接模块操作(config路径/init/文件名/状态机步骤)。拎出来单看须自足。
- **替换自检**：换模块内部实现/布局/存储路径，调用方要改=耦合超标。
- **契约最小+门面契约最优先**：override/可测走"传已加载对象/改模块状态"，不往公共入口塞参。门面有明确契约(provider=对上层无感查询)，违反契约的函数(refresh/status/last_sync/coverage)不得塞进门面但不删除——归属独立对外面 sync_runner。命名一致次要，契约一致根本。
- **原则推到根**：用户指一处先问"该点所属抽象层是否整体错"，一次挖到底。原则优先级 > 行业惯例(pro_api/create_engine 等是反例)。

## 待领导拍板（设计未决，见 worklog/WORKLOG.md）
1. 第一版 A 股标的范围 2. tushare 积分等级(分钟 stk_mins≥5000) 3. 成本模型参数 4. 序列模型本机路径
