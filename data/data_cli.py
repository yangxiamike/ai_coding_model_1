"""数据模块统一入口（客户端层）。

按 AGENTS.md 规范：客户端文件以 `_cli.py` 结尾，作为模块统一入口，
`import data.data_cli` 即可调用本模块全部对外能力。

对外暴露两个对称面（双面共存）：
- **查询面 `provider`**：按需回源 + 本地缓存，对上层无感。import 即得数据，
  缺数据 provider 内部自动回源补齐，命中直读不回源。无 sync/refresh/status 入口。
- **同步面 `sync_runner`**：函数式对称的显式预热入口，供定期同步（cron /
  脚本触发，模块不内置调度器）或批量拉取。调后不返回 df，只落库。

二者共用 sync_jobs 补缺内核，差异仅在调用后是否读本地返回。

另导出：数据源契约（DataSource / AShareDataSource / StandardBar，供上层
注入自定义源）、日历（TradingCalendar / AlwaysOpenCalendar）、常量（频率 /
复权 / 标的类别）。

模块加载即就绪（AGENTS.md §6）：状态由 sync_jobs 模块单例惰性组装，配置
由同层 config.py 用 __file__ 自定位 config.yaml 读取，无需 init。

用法：
    from data import provider, sync_runner
    df = provider.daily(["600000.SH"], "20240101", "20240601")  # 查询面
    sync_runner.daily(["600000.SH"], "20240101", "20240601")    # 同步面（预热）
"""
from data.provider import (
    close,
    minute, hour, daily, latest_bar,
    daily_basic, adj_factor, stk_limit, stock_st, suspend_d,
    trade_cal, stock_list, is_trading_day,
    export,
)
from data.sync_runner import (
    all as sync_all,
    minute as sync_minute,
    daily as sync_daily,
    daily_basic as sync_daily_basic,
    adj_factor as sync_adj_factor,
    stk_limit as sync_stk_limit,
    stock_st as sync_stock_st,
    suspend_d as sync_suspend_d,
    trade_cal as sync_trade_cal,
    stock_list as sync_stock_list,
)
from data.datasource.interface import (
    DataSource,
    AShareDataSource,
    StandardBar,
)
from data.calendar import TradingCalendar, AlwaysOpenCalendar
from data.schema import (
    FREQ_MIN1, FREQ_MIN60, FREQ_DAY,
    ADJ_NONE, ADJ_QFQ, ADJ_HFQ,
    SEC_STOCK, SEC_ETF, SEC_CB, SEC_CRYPTO,
)

# provider 模块（便于 `from data import provider; provider.fn()`）
from data import provider, sync_runner  # noqa: F401

__all__ = [
    # 查询面
    "close",
    "minute", "hour", "daily", "latest_bar",
    "daily_basic", "adj_factor", "stk_limit", "stock_st", "suspend_d",
    "trade_cal", "stock_list", "is_trading_day",
    "export",
    # 同步面（带 sync_ 前缀，避免与查询面同名冲突）
    "sync_all",
    "sync_minute", "sync_daily", "sync_daily_basic",
    "sync_adj_factor", "sync_stk_limit", "sync_stock_st",
    "sync_suspend_d", "sync_trade_cal", "sync_stock_list",
    # 子模块
    "provider",
    "sync_runner",
    # 契约 / 常量
    "DataSource",
    "AShareDataSource",
    "StandardBar",
    "TradingCalendar",
    "AlwaysOpenCalendar",
    "FREQ_MIN1",
    "FREQ_MIN60",
    "FREQ_DAY",
    "ADJ_NONE",
    "ADJ_QFQ",
    "ADJ_HFQ",
    "SEC_STOCK",
    "SEC_ETF",
    "SEC_CB",
    "SEC_CRYPTO",
]
