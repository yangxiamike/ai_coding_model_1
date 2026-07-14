import numpy as np
import pandas as pd


def calc(nav_df: pd.DataFrame) -> pd.DataFrame:
    if nav_df.empty:
        return pd.DataFrame()

    nav = nav_df["nav"].values
    dates = nav_df["ts"].values

    returns = np.diff(nav) / nav[:-1]
    returns = np.append(0.0, returns)

    total_return = nav[-1] / nav[0] - 1
    n_days = len(nav)
    annual_return = (1 + total_return) ** (252 / n_days) - 1 if n_days > 0 else 0.0

    mean_ret = np.mean(returns[1:]) if len(returns) > 1 else 0.0
    std_ret = np.std(returns[1:]) if len(returns) > 1 else 0.0
    sharpe = mean_ret / std_ret * np.sqrt(252) if std_ret > 0 else 0.0

    cummax = np.maximum.accumulate(nav)
    drawdown = (nav - cummax) / cummax
    max_drawdown = np.min(drawdown)

    peak_idx = np.argmin(drawdown)
    recovery_idx = np.argmax(nav[peak_idx:]) + peak_idx if peak_idx < len(nav) - 1 else len(nav) - 1
    max_dd_duration = recovery_idx - peak_idx

    result = pd.DataFrame({
        "total_return": [total_return],
        "annual_return": [annual_return],
        "sharpe": [sharpe],
        "max_drawdown": [max_drawdown],
        "max_dd_duration_days": [max_dd_duration],
        "n_days": [n_days],
    })

    return result
