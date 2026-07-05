"""数据模块包。

对外暴露两个对称面（双面共存）：
- **查询面 `provider`**：按需回源 + 本地缓存，对上层无感。import 即得数据，
  缺数据 provider 内部自动回源补齐，命中直读不回源。无 sync/refresh/status 入口。
- **同步面 `sync_runner`**：函数式对称的显式预热入口，供定期同步（cron /
  脚本触发，模块不内置调度器）或批量拉取。调后不返回 df，只落库。

二者共用 sync_jobs 补缺内核，差异仅在调用后是否读本地返回 df。

模块加载即就绪（AGENTS.md §6）：运行时状态由 sync_jobs 模块单例惰性组装，
配置由同层 config.py 用 __file__ 自定位 config.yaml 读取，无需 init。

统一入口为 `data.data_cli`（见 AGENTS.md 客户端规范）；本 `__init__` re-export
其公开符号，并暴露 `provider` / `sync_runner` 模块便于 `provider.fn()` 调用。

推荐用法：
    from data import provider, sync_runner
    df = provider.daily(["600000.SH"], "20240101", "20240601")  # 查询
    sync_runner.daily(["600000.SH"], "20240101", "20240601")    # 预热（可选）
"""
from data.data_cli import *  # noqa: F401,F403
from data.data_cli import __all__  # noqa: F401
from data import provider, sync_runner  # noqa: F401
