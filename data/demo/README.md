# 纯合成离线 demo 数据包

`ashare_daily_cross_section_demo_v1/` 是一个已经构建完成、可直接携带和
离线读取的数据集目录。它不需要安装 zer0share，也不会连接任何数据库。

从仓库根目录运行：

```python
from data import open_dataset

package = open_dataset("data/demo/ashare_daily_cross_section_demo_v1")
panel = package.read()
print(panel)
```

demo 只有 3 个交易日和 3 个虚构代码：

- `999001.SZ`：测试涨停状态和后复权价格。
- `999002.SH`：最后一天停牌、保留截面行但没有日线价格。
- `999003.BJ`：测试 ST 与复牌状态。

所有名称、代码和数值均为人工合成，不代表真实证券或真实市场数据。目录仍完整
包含八张源表、原始日线、复权因子、HFQ 视图、状态面板、manifest、schema 和
SHA256 校验和。标准交付不预设 train/validation/test；合作方读取完整面板后按
自己的标签前瞻窗口和实验方案切分。
