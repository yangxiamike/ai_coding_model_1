import logging
from typing import Dict, List

import pandas as pd
from torch.utils.data import Dataset

from data import provider
from data.schema import FREQ_DAY, FREQ_MIN1, FREQ_MIN60

logger = logging.getLogger(__name__)

_FREQ_MAP = {
    "1min": FREQ_MIN1,
    "60min": FREQ_MIN60,
    "day": FREQ_DAY,
}


class BarDataset(Dataset):
    def __init__(self, bars: List[Dict], decision_times: List[str],
                 decision_freq: str) -> None:
        self._bars = bars
        self._decision_times = decision_times
        self._decision_freq = decision_freq
        self._panels: Dict[str, pd.DataFrame] = {}
        self._load_all()

    def _load_all(self) -> None:
        freq_func_map = {
            "1min": provider.minute,
            "60min": provider.hour,
            "day": provider.daily,
        }
        all_ts_codes = [b["ts_code"] for b in self._bars]
        unique_codes = list(set(all_ts_codes))
        start = self._decision_times[0]
        end = self._decision_times[-1]
        for bar in self._bars:
            freq = bar["freq"]
            ts_code = bar["ts_code"]
            window = bar["window"]
            name = bar["name"]
            key = f"{ts_code}_{freq}"
            if key in self._panels:
                continue
            shift_start = _shift_window(start, window, freq)
            fetch_fn = freq_func_map.get(freq)
            if fetch_fn is None:
                raise ValueError(f"不支持频率: {freq}")
            df = fetch_fn([ts_code], shift_start, end, adjust="qfq")
            df["name"] = name
            self._panels[key] = df

    def __len__(self) -> int:
        return len(self._decision_times)

    def __getitem__(self, idx: int) -> pd.DataFrame:
        t = self._decision_times[idx]
        parts = []
        for bar in self._bars:
            freq = bar["freq"]
            window = bar["window"]
            name = bar["name"]
            ts_code = bar["ts_code"]
            key = f"{ts_code}_{freq}"
            panel = self._panels[key]
            ts_col = "trade_date" if freq == "day" else "trade_time"
            filtered = panel[panel[ts_col] <= t].tail(window)
            result = filtered[["name", ts_col, "open", "high", "low",
                               "close", "vol", "amount"]].copy()
            result = result.rename(columns={ts_col: "ts"})
            parts.append(result)
        return pd.concat(parts, ignore_index=True)


def _shift_window(start: str, window: int, freq: str) -> str:
    import datetime as dt
    s = dt.datetime.strptime(start, "%Y%m%d")
    if freq == "day":
        offset = dt.timedelta(days=window * 2)
    else:
        offset = dt.timedelta(days=window)
    return (s - offset).strftime("%Y%m%d")
