import numpy as np
import pandas as pd


def compute_trailing_stop_target(df, trailing_pct=0.009, max_days=3,
                                 profit_threshold=0.01, trade_amount=10000,
                                 t1=True):
    """
    模拟引擎撮合逻辑生成训练标签。买入/卖出均在下一根bar开盘价成交，
    trailing stop 检测在当前bar的close，时间止损按交易日计数。
    T+1约束：买入当天不可卖出（ETF/股票规则）。

    参数:
        df: DataFrame, columns ['time', 'open', 'high', 'low', 'close', 'volume']
        trailing_pct: 从peak回撤比例，默认0.9%
        max_days: 最大持仓交易日数，默认3
        profit_threshold: 正样本利润阈值，默认1%
        trade_amount: 每笔交易金额（元），用于手续费折算每股费用，默认10000
        t1: 是否启用T+1约束（买入当天不可卖出），默认True

    输出: DataFrame，增加列 target(0/1), profit, exit_price, buy_price
    """
    from engine import config as engine_config

    commission_rate = engine_config.get("engine.commission_rate", 0.0003)
    min_commission = engine_config.get("engine.min_commission", 5.0)
    stamp_tax_rate = engine_config.get("engine.stamp_tax_rate", 0.0005)

    df = df.copy().sort_values('time').reset_index(drop=True)
    open_ = df['open'].values.astype(np.float64)
    high = df['high'].values.astype(np.float64)
    close = df['close'].values.astype(np.float64)
    n = len(df)

    dates = pd.to_datetime(df['time']).dt.date.values

    targets = np.zeros(n, dtype=int)
    profits = np.full(n, np.nan)
    exit_prices = np.full(n, np.nan)
    buy_prices = np.full(n, np.nan)

    for t in range(n):
        buy_idx = t + 1
        if buy_idx >= n:
            break

        buy_price = open_[buy_idx]
        peak = buy_price
        sell_idx = None
        buy_date = dates[buy_idx]

        holding_dates = set()
        holding_dates.add(buy_date)

        for i in range(buy_idx, n):
            peak = max(peak, high[i])

            if t1 and dates[i] == buy_date:
                holding_dates.add(dates[i])
                if len(holding_dates) > max_days:
                    sell_idx = i + 1
                    break
                continue

            if close[i] <= peak * (1 - trailing_pct):
                sell_idx = i + 1
                break

            holding_dates.add(dates[i])
            if len(holding_dates) > max_days:
                sell_idx = i + 1
                break

        if sell_idx is None or sell_idx >= n:
            continue

        sell_price = open_[sell_idx]

        shares = trade_amount / buy_price
        buy_commission = max(trade_amount * commission_rate, min_commission)
        sell_commission = buy_commission + trade_amount * stamp_tax_rate
        buy_fee = buy_commission / shares
        sell_fee = sell_commission / shares
        buy_cost = buy_price + buy_fee
        sell_revenue = sell_price - sell_fee

        profit = (sell_revenue - buy_cost) / buy_cost

        buy_prices[t] = buy_price
        exit_prices[t] = sell_price
        profits[t] = profit
        targets[t] = 1 if profit > profit_threshold else 0

    result = df.copy()
    result['target'] = targets
    result['profit'] = profits
    result['exit_price'] = exit_prices
    result['buy_price'] = buy_prices

    last_valid = n - max_days * 6 - 1
    if last_valid > 0:
        result = result.iloc[:last_valid]

    return result


def compute_binary_updown_target(df, k=5, up_pct=0.03, down_pct=0.03):
    """
    exp1风格：未来k步内涨超up_pct且未跌超down_pct → 1，否则0。
    """
    from seq_model.indicators import compute_future_extremes
    extremes = compute_future_extremes(df, k)
    extremes['target'] = (extremes['target_up_3pct_5'] & ~extremes['target_down_3pct_5']).astype(int)
    return extremes[['time', 'target']]


def compute_categorical_return_target(df, k=20):
    """
    exp2风格：未来k步最高/最低价相对open的涨幅分级（8级）。
    """
    df = df.sort_values('time', ascending=False).reset_index(drop=True)
    df['highest'] = df['high'].rolling(k).max()
    df['lowest'] = df['low'].rolling(k).min()
    df = df.sort_values('time').reset_index(drop=True)

    def _grade(rate):
        if rate > 0.1: return 0
        if rate > 0.08: return 1
        if rate > 0.05: return 2
        if rate > 0.03: return 3
        if rate > 0.02: return 4
        if rate > 0.01: return 5
        if rate > 0.00: return 6
        return 7

    df['high_target'] = df.apply(lambda r: _grade(r['highest'] / r['open'] - 1), axis=1)
    df['low_target'] = df.apply(lambda r: _grade(-(r['lowest'] / r['open'] - 1)), axis=1)
    return df[['time', 'high_target', 'low_target']]


def compute_multilabel_return_target(df, k=20):
    """
    exp3风格：未来k步涨幅按阈值逐位翻转，7-bit多标签。
    """
    df = df.sort_values('time', ascending=False).reset_index(drop=True)
    df['highest'] = df['high'].rolling(k).max()
    df['lowest'] = df['low'].rolling(k).min()
    df = df.sort_values('time').reset_index(drop=True)

    thresholds = [0.10, 0.08, 0.05, 0.03, 0.02, 0.01, 0.00]

    def _bits(rate):
        return [1 if rate > t else 0 for t in thresholds]

    df['high_target'] = df.apply(lambda r: _bits(r['highest'] / r['open'] - 1), axis=1)
    df['low_target'] = df.apply(lambda r: _bits(-(r['lowest'] / r['open'] - 1)), axis=1)
    return df[['time', 'high_target', 'low_target']]
