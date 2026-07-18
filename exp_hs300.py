import sys
sys.path.insert(0, "/media/xavier/Samsumg/codes/agent_coding")

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader
from transformers import get_cosine_schedule_with_warmup
from tqdm import tqdm

from data import provider
from seq_model.indicators import compute_all_kline_indicators, calculate_rates
from seq_model.trade_label import compute_trailing_stop_target
from seq_model.field_meta import get_meta_process_info_from_dataframe, get_preprocess_function
from seq_model.builder import make_whole_transformer, SeqDataset
from seq_model.utils import TorchTrainingVisualizer
from seq_model.algo_pack import save_to_fold, load_from_fold


TS_CODE = "510300.SH"
TRAIN_START = "20260105"
TRAIN_END = "20260525"
TEST_START = "20260601"
TEST_END = "20260701"
DIM = 64
BATCH = 2
LEN = 120
EPOCHS = 20


def feature_function(df):
    feature = pd.merge(compute_all_kline_indicators(df), df, 'inner', 'time')
    feature = pd.merge(calculate_rates(df), feature, 'inner', 'time')
    feature.dropna(axis=1, how='any', inplace=True)
    feature.drop(columns=['open', 'high', 'low', 'close', 'volume'], inplace=True, errors='ignore')
    return feature


def _prepare(df):
    df = df.rename(columns={"trade_time": "time", "vol": "volume"})
    df = df[["time", "open", "high", "low", "close", "volume"]].copy()
    df = df.sort_values("time").reset_index(drop=True)
    return df


print("=== 加载数据 ===")
train_raw = _prepare(provider.minute([TS_CODE], TRAIN_START, TRAIN_END, adjust="qfq"))
test_raw = _prepare(provider.minute([TS_CODE], TEST_START, TEST_END, adjust="qfq"))

print("=== 特征 ===")
train_feature = feature_function(train_raw)
test_feature = feature_function(test_raw)

print("=== 标签 ===")
train_target = compute_trailing_stop_target(
    train_raw, trailing_pct=0.009, max_days=3, profit_threshold=0.01, trade_amount=10000)
test_target = compute_trailing_stop_target(
    test_raw, trailing_pct=0.009, max_days=3, profit_threshold=0.01, trade_amount=10000)

train_df = pd.merge(train_feature, train_target[['time', 'target']], 'inner', 'time')
test_df = pd.merge(test_feature, test_target[['time', 'target']], 'inner', 'time')
train_df.dropna(axis=1, how='any', inplace=True)
test_df.dropna(axis=1, how='any', inplace=True)
train_df.dropna(subset=['target'], inplace=True)
test_df.dropna(subset=['target'], inplace=True)

common_cols = [c for c in train_df.columns if c in test_df.columns]
test_df = test_df[common_cols]
train_df = train_df[common_cols]

fea_col = [col for col in train_df.columns if col not in ['time', 'target'] and 'target' not in col]
print(f"训练: {train_df.shape}, 正样本: {train_df['target'].mean():.3f}")
print(f"测试: {test_df.shape}, 正样本: {test_df['target'].mean():.3f}")
print(f"特征列数: {len(fea_col)}")

fm, pi = get_meta_process_info_from_dataframe(train_df[fea_col])
preprocess_func = get_preprocess_function(fm, pi)

train_set = SeqDataset(train_df, preprocess_func, LEN)
test_set = SeqDataset(test_df, preprocess_func, LEN)

print("=== 训练 ===")
train_loader = DataLoader(train_set, BATCH, True, drop_last=True)

model = make_whole_transformer(fm, pi, DIM, LEN, num_clf_tokens=1, output_dims=[1])
device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)

opt = torch.optim.AdamW(model.parameters(), lr=3e-5, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01)
bce = torch.nn.BCEWithLogitsLoss()
scheduler = get_cosine_schedule_with_warmup(
    opt, num_warmup_steps=2 * len(train_set) // BATCH,
    num_training_steps=EPOCHS * len(train_set) // BATCH)
ttv = TorchTrainingVisualizer("worklog/runs", "hs300_trailing_stop")

for e in range(EPOCHS):
    print('epoch: ', e)
    for di, dm, cv, ci, cm, gt in tqdm(train_loader):
        opt.zero_grad()
        out = model(di.to(device), dm.to(device), cv.to(device),
                    ci.to(device), cm.to(device), batch=BATCH)
        loss = bce(out, gt.float().to(device).view(-1, 1))
        ttv.log_metrics({"loss": loss.detach().cpu().float(), "lr": scheduler.get_last_lr()[0]})
        loss.backward()
        opt.step()
        scheduler.step()
    torch.save(model.state_dict(), f"worklog/runs/hs300_model_e{e}.pt")
ttv.close()

print("=== 测试 ===")
test_loader = DataLoader(test_set, BATCH, False, drop_last=True)
model.eval()

y_gt, y_pred = [], []
with torch.no_grad():
    for di, dm, cv, ci, cm, gt in tqdm(test_loader):
        out = torch.sigmoid(model(di.to(device), dm.to(device), cv.to(device),
                                  ci.to(device), cm.to(device), batch=BATCH))
        y_pred.append(out.detach().cpu().numpy()[:, 0])
        y_gt.append(gt.numpy())

from sklearn.metrics import roc_auc_score, classification_report
y_gt = np.concatenate(y_gt)
y_pred = np.concatenate(y_pred)
print(f"AUC: {roc_auc_score(y_gt, y_pred):.4f}")
print(classification_report(y_gt, (y_pred > 0.5).astype(int), digits=4))
