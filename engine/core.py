import logging
from typing import Callable, Dict

import pandas as pd

from engine import config
from engine.interface import validate_declare
from engine.loader import load_backtest, load_live, load_aux_filters, load_next_open
from engine.executor import execute_backtest, execute_live
from engine.portfolio import initial_state, update_portfolio, total_asset
from engine.matcher import default_commission

logger = logging.getLogger(__name__)


def run(declare_dict: Dict, start: str, end: str = None,
        commission_fn: Callable = None,
        mode: str = None) -> object:
    validate_declare(declare_dict)
    if mode is None:
        mode = config.get("engine.mode", "backtest")
    if commission_fn is None:
        commission_fn = default_commission

    bars = declare_dict["bars"]
    fetch_fn = declare_dict["fetch"]
    decision_freq = declare_dict["decision_freq"]

    if mode == "backtest":
        return _run_backtest(bars, fetch_fn, decision_freq,
                             start, end, commission_fn)
    elif mode == "live":
        return _run_live(bars, fetch_fn, decision_freq,
                         start, commission_fn)
    else:
        raise ValueError(f"不支持模式: {mode}")


def _run_backtest(bars, fetch_fn, decision_freq, start, end, commission_fn):
    loader, decision_times = load_backtest(bars, decision_freq, start, end)
    state = initial_state()

    ts_idx = 0
    next_data = next(loader.__iter__(), None)

    while ts_idx < len(decision_times):
        t = decision_times[ts_idx]
        ohlcv_df = next_data
        if ohlcv_df is None:
            break

        fetch_result = fetch_fn(t)
        ctx = {"ohlcv_df": ohlcv_df, "fetch": fetch_result,
               "positions": dict(state["positions"]),
               "cash": state["cash"]}

        target = yield ctx

        next_ts_idx = ts_idx + 1
        if next_ts_idx >= len(decision_times):
            break

        next_ts = decision_times[next_ts_idx]
        aux = load_aux_filters(next_ts)
        next_open_df = load_next_open(bars, next_ts)

        result = execute_backtest(target, state["positions"], state["cash"],
                                  next_open_df, aux, commission_fn)
        state = update_portfolio(result)

        ts_idx += 1
        try:
            next_data = loader.__iter__().__next__()
        except StopIteration:
            next_data = None

    provider.close()


def _run_live(bars, fetch_fn, decision_freq, start, commission_fn):
    state = initial_state()

    while True:
        t = start
        ohlcv_df = load_live(bars, decision_freq, t, fetch_fn)
        fetch_result = fetch_fn(t)
        ctx = {"ohlcv_df": ohlcv_df, "fetch": fetch_result,
               "positions": dict(state["positions"]),
               "cash": state["cash"]}

        target = yield ctx

        aux = load_aux_filters(t)
        next_ts = t
        next_open_df = load_next_open(bars, next_ts)

        result = execute_backtest(target, state["positions"], state["cash"],
                                  next_open_df, aux, commission_fn)
        state = update_portfolio(result)
