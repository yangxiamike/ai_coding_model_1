import logging
from typing import Callable, Dict, List, Optional

import pandas as pd
from torch.utils.data import DataLoader

from data import provider, meta_store
from data.schema import FREQ_DAY, FREQ_MIN1, FREQ_MIN60
from engine.dataset import BarDataset

logger = logging.getLogger(__name__)


def load_backtest(bars: List[Dict], decision_freq: str,
                  start: str, end: str,
                  batch_size: int = 1, prefetch_factor: int = 2) -> DataLoader:
    decision_times = _generate_decision_times(decision_freq, start, end)
    dataset = BarDataset(bars, decision_times, decision_freq)
    loader = DataLoader(dataset, batch_size=batch_size,
                        shuffle=False, prefetch_factor=prefetch_factor,
                        num_workers=0, collate_fn=_collate_fn)
    return loader, decision_times


def load_live(bars: List[Dict], decision_freq: str,
              current_ts: str, fetch_fn: Callable) -> pd.DataFrame:
    freq_func_map = {
        "1min": provider.minute,
        "60min": provider.hour,
        "day": provider.daily,
    }
    parts = []
    for bar in bars:
        freq = bar["freq"]
        window = bar["window"]
        name = bar["name"]
        ts_code = bar["ts_code"]
        shift_start = _shift_window(current_ts, window, freq)
        # 修复 2026-07-14: 原为 fetch_fn = ... 与形参 fetch_fn 重名遮蔽，
        # 导致策略自定义抓取逻辑在实盘中从未生效。
        provider_fn = freq_func_map.get(freq)
        if provider_fn is None:
            raise ValueError(f"不支持频率: {freq}")
        df = provider_fn([ts_code], shift_start, current_ts, adjust="qfq")
        ts_col = "trade_date" if freq == "day" else "trade_time"
        df = df[df[ts_col] <= current_ts].tail(window)
        result = df[["name", ts_col, "open", "high", "low",
                     "close", "vol", "amount"]].copy()
        result = result.rename(columns={ts_col: "ts"})
        parts.append(result)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def load_aux_filters(date: str) -> Dict:
    result = {}
    try:
        result["limit"] = provider.stk_limit(date)
    except Exception:
        result["limit"] = pd.DataFrame()
    try:
        result["suspend"] = provider.suspend_d(date)
    except Exception:
        result["suspend"] = pd.DataFrame()
    try:
        result["st"] = provider.stock_st(date)
    except Exception:
        result["st"] = pd.DataFrame()
    return result


def load_next_open(bars: List[Dict], next_ts: str) -> pd.DataFrame:
    freq_func_map = {
        "1min": provider.minute,
        "60min": provider.hour,
        "day": provider.daily,
    }
    parts = []
    for bar in bars:
        freq = bar["freq"]
        ts_code = bar["ts_code"]
        name = bar["name"]
        fetch_fn = freq_func_map.get(freq)
        if fetch_fn is None:
            continue
        df = fetch_fn([ts_code], next_ts, next_ts, adjust="qfq")
        if not df.empty:
            df = df.head(1)
            ts_col = "trade_date" if freq == "day" else "trade_time"
            result = df[["ts_code", ts_col, "open"]].copy()
            result = result.rename(columns={ts_col: "ts"})
            result["name"] = name
            parts.append(result)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _generate_decision_times(freq: str, start: str, end: str) -> List[str]:
    exchange = "SSE"
    if freq == "day":
        return meta_store.get_trading_days(exchange, start, end)
    elif freq in ("1min", "60min"):
        trading_days = meta_store.get_trading_days(exchange, start, end)
        if freq == "60min":
            # 修复 2026-07-14: 原为 30 分钟间隔 8 个/天，改为 60 分钟间隔 4 个/天。
            times = []
            for d in trading_days:
                for h in ["10:30", "11:30", "14:00", "15:00"]:
                    times.append(f"{d} {h}")
            return times
        else:
            return trading_days
    else:
        raise ValueError(f"不支持决策频率: {freq}")


def _shift_window(start: str, window: int, freq: str) -> str:
    import datetime as dt
    s = dt.datetime.strptime(start, "%Y%m%d")
    if freq == "day":
        offset = dt.timedelta(days=window * 2)
    else:
        offset = dt.timedelta(days=window)
    return (s - offset).strftime("%Y%m%d")


def _collate_fn(batch):
    if isinstance(batch, list) and len(batch) == 1:
        return batch[0]
    return pd.concat(batch, ignore_index=True)
