# 2026-07-26 zer0share 数据包验证

- Python: `/Users/ml/anaconda3/bin/python3.11`，版本 3.11.8
- 单元测试: `python3.11 -m unittest -v tests.test_dataset_package`
- 结果: 15/15 通过
- 覆盖: 八表 mock reader、官方字段/分页、canonical preset 一致性、HFQ、历史股票池、ST/停复牌/涨跌停、无前填、分年构建、稳定 ID、敏感路径脱敏、原子失败清理、不可覆盖、离线可携带读取、split 投影过滤、manifest/schema/分区/文件/SHA256 篡改拒绝
- 静态检查: `compileall` 通过，`git diff --check` 通过
- 真实只读冒烟: 未执行；本机未设置 `ZER0SHARE_CONFIG_PATH`，Python 3.11 环境未安装 zer0share。未探查、同步或修改任何本地数据库。
