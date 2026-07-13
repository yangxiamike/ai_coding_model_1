# 通讯记录

## 2026-07-10 回测模块策略声明数据结构设计对齐

- 输入: `dict{bars: list[dict], fetch: callable}`
- 每条 bar dict: `name/ts_code/freq/window`（ohlcv 声明）
- fetch: 单函数，柯里化，签名 `fetch(t)->任意类型`，框架透传不处理
- 运行时每决策点 t 输出: `dict{ohlcv_df: df[name,ts,open,high,low,close,vol,amount], fetch: 透传值}`
- 每决策点取 t-window 到 t 时序窗口数据，不是单时刻截面
- 预估模块输出: 目标数量 `dict[ts_code]->int`（预估模块完全控制仓位，引擎只执行差额撮合）
- 预估模块输入(ctx): `dict{ohlcv_df, fetch, positions, cash}`（账户极简，手续费撮合时自动从cash扣除）
- 撮合时点: 下一根开盘价成交（严格避免未来信息泄漏）
- 手续费: 比例+印花税（卖出额外加0.05%），默认实现A股真实费用结构；支持输入函数替换佣金/印花税计算逻辑，不硬编码
- 撮合过滤: 硬过滤——涨停不买、跌停不卖、停牌跳过，持仓维持不变
- 决策时间轴: 按策略声明的freq生成决策时刻，只遍历实际需要的时刻，不跑无效时间点
- 多频率对齐: 策略在declare里显式声明决策freq，bars里其他freq为辅助特征，框架按决策freq生成轴，其他freq数据每决策点取最近值配对
- 数据加载: 复用torch DataLoader，Dataset adapter返回某决策点ohlcv窗口df，collate_fn保持df格式，batch_size+prefetch_factor控内存
- 引擎启动接口: 生成器式，类似torch训练循环逐步推进；yield+send交互——ctx=next(gen), target=strategy.decide(ctx), next_ctx=gen.send(target)，引擎只做数据供给+撮合记账，预估模块可替换（策略/模型/RL agent）
- yield内容: 裸ctx dict{ohlcv_df, fetch, positions, cash}，与预估模块输入一致，不附带trades/nav/元信息
- 净值/绩效: 上层自己累积，引擎不维护任何历史，纯粹作为RL环境（env），无状态
