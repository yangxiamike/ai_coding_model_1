from torch.utils.tensorboard import SummaryWriter
from torch.utils.hooks import RemovableHandle
import torch
from typing import List
import torch.nn as nn
from typing import Dict, Optional
import os


class TorchTrainingVisualizer:
    """
    🎯 每次调用 log_metrics() 必须打一个点！不平均、不跳过、不降采样！
    专为调试训练动态设计：梯度爆炸、学习率震荡、loss突跳、过拟合苗头...
    100% 原始数据记录，TensorBoard 显示真实训练心跳。
    """

    def __init__(self,
                 log_dir: str = "./runs",
                 comment: str = "",
                 flush_secs: int = 10):
        """
        :param log_dir: TensorBoard 日志目录
        :param comment: 实验名（自动拼在 log_dir 后）
        :param flush_secs: 每隔多少秒刷盘（默认10秒，避免频繁IO）
        """
        self.log_dir = os.path.join(log_dir, comment) if comment else log_dir
        self.writer = SummaryWriter(log_dir=self.log_dir, flush_secs=flush_secs)
        self.step_count = 0  # 全局步数计数器（可选，用于自动递增）

    def log_metrics(self, metrics: Dict[str, float], step: Optional[int] = None):
        """
        ✅ 每次调用，必须打一个点！
        :param metrics: 字典，如 {'loss': 0.5, 'grad_norm': 2.1, 'lr': 0.001}
        :param step: 可选。如果你传了，就用你传的（如 batch_idx）。
                     如果没传，自动用 self.step_count 递增（推荐用于简单场景）
        """
        if step is None:
            step = self.step_count
            self.step_count += 1  # 自动递增，确保每个调用对应唯一 step

        for key, value in metrics.items():
            # ✅ 强制转换为 float，避免 int/np.float32 导致错误
            if not isinstance(value, float):
                value = float(value)
            self.writer.add_scalar(key, value, step)

        # 可选：打印调试信息（生产环境可删）
        # print(f"📊 Step {step}: {metrics}")

    def log_gradients(self, model: torch.nn.Module, step: Optional[int] = None):
        """
        记录所有参数的梯度分布（用于检测梯度爆炸）
        """
        if step is None:
            step = self.step_count
            self.step_count += 1

        for name, param in model.named_parameters():
            if param.grad is not None:
                self.writer.add_histogram(f"gradients/{name}", param.grad, step)
                self.writer.add_histogram(f"weights/{name}", param.data, step)

    def log_hparams(self, hparams: Dict, metrics: Dict):
        """记录超参数 + 最终指标（仅在训练结束时调用一次）"""
        self.writer.add_hparams(hparams, metrics)

    def close(self):
        self.writer.close()
        print(f"✅ TensorBoard 日志已保存至: {self.log_dir}")
        print("💡 在终端运行: tensorboard --logdir=./runs  查看实时曲线")
