import logging
from typing import Callable, Dict, List, Optional

import pandas as pd

from data import provider
from engine import config

logger = logging.getLogger(__name__)


def match(target: Dict[str, int], positions: Dict[str, int],
          cash: float, next_bars: pd.DataFrame,
          commission_fn: Optional[Callable] = None,
          limit_df: Optional[pd.DataFrame] = None,
          suspend_df: Optional[pd.DataFrame] = None,
          st_df: Optional[pd.DataFrame] = None) -> Dict:
    if commission_fn is None:
        commission_fn = default_commission

    trades: List[Dict] = []
    delta = _compute_delta(target, positions)
    next_prices = _extract_next_open(next_bars)

    for ts_code, qty_delta in delta.items():
        if qty_delta == 0:
            continue
        price = next_prices.get(ts_code)
        if price is None:
            continue

        if qty_delta > 0:
            if limit_df is not None and not limit_df.empty:
                lim = limit_df[limit_df["ts_code"] == ts_code]
                if not lim.empty and lim.iloc[0]["up_limit"] <= price:
                    logger.info(f"涨停过滤: {ts_code}")
                    continue
            if suspend_df is not None and not suspend_df.empty:
                susp = suspend_df[suspend_df["ts_code"] == ts_code]
                if not susp.empty:
                    logger.info(f"停牌过滤: {ts_code}")
                    continue

            cost = qty_delta * price
            fee = commission_fn(cost, "buy")
            if cash < cost + fee:
                affordable = max(0, int((cash - fee) / price))
                if affordable <= 0:
                    continue
                qty_delta = affordable
                cost = qty_delta * price
                fee = commission_fn(cost, "buy")
            trades.append({"ts_code": ts_code, "price": price,
                           "qty": qty_delta, "side": "buy", "fee": fee})
            positions[ts_code] = positions.get(ts_code, 0) + qty_delta
            cash -= cost + fee

        else:
            sell_qty = abs(qty_delta)
            if limit_df is not None and not limit_df.empty:
                lim = limit_df[limit_df["ts_code"] == ts_code]
                if not lim.empty and lim.iloc[0]["down_limit"] >= price:
                    logger.info(f"跌停过滤: {ts_code}")
                    continue
            revenue = sell_qty * price
            fee = commission_fn(revenue, "sell")
            trades.append({"ts_code": ts_code, "price": price,
                           "qty": sell_qty, "side": "sell", "fee": fee})
            positions[ts_code] = positions.get(ts_code, 0) - sell_qty
            if positions[ts_code] <= 0:
                del positions[ts_code]
            cash += revenue - fee

    zero_keys = [k for k, v in positions.items() if v <= 0]
    for k in zero_keys:
        del positions[k]

    return {"positions": positions, "cash": cash, "trades": trades}


def default_commission(amount: float, side: str) -> float:
    rate = config.get("engine.commission_rate", 0.0003)
    min_comm = config.get("engine.min_commission", 5.0)
    comm = amount * rate
    comm = max(comm, min_comm)
    if side == "sell":
        stamp_rate = config.get("engine.stamp_tax_rate", 0.0005)
        comm += amount * stamp_rate
    return comm


def _compute_delta(target: Dict[str, int], current: Dict[str, int]) -> Dict[str, int]:
    delta = {}
    all_codes = set(target.keys()) | set(current.keys())
    for code in all_codes:
        tgt = target.get(code, 0)
        cur = current.get(code, 0)
        d = tgt - cur
        if d != 0:
            delta[code] = d
    return delta


def _extract_next_open(next_bars: pd.DataFrame) -> Dict[str, float]:
    if next_bars.empty:
        return {}
    if "ts_code" in next_bars.columns:
        return dict(zip(next_bars["ts_code"], next_bars["open"]))
    if "name" in next_bars.columns:
        return dict(zip(next_bars["name"], next_bars["open"]))
    return {}
