import pandas as pd
import numpy as np
from typing import Optional


# ==================== Numba 加速支持 ====================
try:
    from numba import jit
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False


if NUMBA_AVAILABLE:
    @jit(nopython=True)
    def ema_numba(close, window):
        n = len(close)
        ema = np.empty(n)
        alpha = 2.0 / (window + 1)
        ema[0] = close[0]
        for i in range(1, n):
            ema[i] = close[i] * alpha + ema[i - 1] * (1 - alpha)
        return ema

    @jit(nopython=True)
    def atr_numba(high, low, close, window):
        n = len(high)
        tr = np.empty(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1])
            )
        atr = np.empty(n)
        atr[0] = tr[0]
        for i in range(1, n):
            atr[i] = (atr[i - 1] * (window - 1) + tr[i]) / window
        return atr

    @jit(nopython=True)
    def sma_numba(arr, window):
        n = len(arr)
        result = np.empty(n)
        cumsum = 0.0
        for i in range(n):
            if i < window:
                cumsum += arr[i]
                result[i] = cumsum / (i + 1)
            else:
                cumsum = cumsum - arr[i - window] + arr[i]
                result[i] = cumsum / window
        return result

    @jit(nopython=True)
    def wma_numba(arr, window):
        n = len(arr)
        result = np.empty(n)
        weights = np.array([i + 1 for i in range(window)], dtype=np.float64)
        weight_sum = weights.sum()
        for i in range(n):
            if i < window - 1:
                result[i] = np.nan
            else:
                window_vals = arr[i - window + 1:i + 1]
                result[i] = np.dot(window_vals, weights) / weight_sum
        return result

    @jit(nopython=True)
    def roc_numba(arr, period):
        n = len(arr)
        result = np.empty(n)
        for i in range(n):
            if i < period:
                result[i] = np.nan
            else:
                result[i] = (arr[i] - arr[i - period]) / arr[i - period] * 100
        return result

    @jit(nopython=True)
    def bb_width_numba(close, window, std_dev=2.0):
        n = len(close)
        sma = np.empty(n)
        std = np.empty(n)
        for i in range(n):
            if i < window - 1:
                sma[i] = np.nan
                std[i] = np.nan
            else:
                window_data = close[i - window + 1:i + 1]
                sma[i] = np.mean(window_data)
                std[i] = np.std(window_data)
        upper = sma + std_dev * std
        lower = sma - std_dev * std
        width = upper - lower
        return sma, upper, lower, width

    @jit(nopython=True)
    def keltner_channel_numba(high, low, close, window_atr, multiplier_atr, window_sma):
        n = len(close)
        atr = atr_numba(high, low, close, window_atr)
        sma = sma_numba(close, window_sma)
        upper = sma + multiplier_atr * atr
        lower = sma - multiplier_atr * atr
        mid = sma
        return upper, mid, lower

    @jit(nopython=True)
    def trix_numba(close, window):
        n = len(close)
        ema1 = ema_numba(close, window)
        ema2 = ema_numba(ema1, window)
        ema3 = ema_numba(ema2, window)
        trix = np.empty(n)
        for i in range(1, n):
            if np.isnan(ema3[i]) or np.isnan(ema3[i - 1]):
                trix[i] = np.nan
            else:
                trix[i] = (ema3[i] - ema3[i - 1]) / ema3[i - 1] * 100
        trix[0] = np.nan
        return trix

    @jit(nopython=True)
    def cci_numba(high, low, close, window):
        n = len(close)
        tp = (high + low + close) / 3
        sma_tp = sma_numba(tp, window)
        mad = np.empty(n)
        for i in range(n):
            if i < window - 1:
                mad[i] = np.nan
            else:
                window_tp = tp[i - window + 1:i + 1]
                mad[i] = np.mean(np.abs(window_tp - sma_tp[i]))
        cci = (tp - sma_tp) / (0.015 * (mad + 1e-10))
        return cci

    @jit(nopython=True)
    def williams_r_numba(high, low, close, window):
        n = len(close)
        highest_high = np.empty(n)
        lowest_low = np.empty(n)
        for i in range(n):
            if i < window - 1:
                highest_high[i] = np.nan
                lowest_low[i] = np.nan
            else:
                window_high = high[i - window + 1:i + 1]
                window_low = low[i - window + 1:i + 1]
                highest_high[i] = np.max(window_high)
                lowest_low[i] = np.min(window_low)
        wr = -100 * (highest_high - close) / (highest_high - lowest_low + 1e-10)
        return wr

    @jit(nopython=True)
    def mom_numba(close, window):
        n = len(close)
        mom = np.empty(n)
        for i in range(n):
            if i < window:
                mom[i] = np.nan
            else:
                mom[i] = close[i] - close[i - window]
        return mom

    @jit(nopython=True)
    def ppo_numba(close, fast, slow, signal):
        n = len(close)
        ema_fast = ema_numba(close, fast)
        ema_slow = ema_numba(close, slow)
        ppo_line = (ema_fast - ema_slow) / ema_slow * 100
        ppo_signal = ema_numba(ppo_line, signal)
        ppo_hist = ppo_line - ppo_signal
        return ppo_line, ppo_signal, ppo_hist

    @jit(nopython=True)
    def stoch_rsi_numba(close, rsi_window, stoch_window):
        n = len(close)
        delta = np.empty(n)
        delta[0] = 0
        for i in range(1, n):
            delta[i] = close[i] - close[i - 1]
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = np.empty(n)
        avg_loss = np.empty(n)
        alpha_g = 1.0 / rsi_window
        alpha_l = 1.0 / rsi_window
        avg_gain[0] = gain[0]
        avg_loss[0] = loss[0]
        for i in range(1, n):
            avg_gain[i] = gain[i] * alpha_g + avg_gain[i - 1] * (1 - alpha_g)
            avg_loss[i] = loss[i] * alpha_l + avg_loss[i - 1] * (1 - alpha_l)
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))

        min_rsi = np.empty(n)
        max_rsi = np.empty(n)
        for i in range(n):
            if i < stoch_window - 1:
                min_rsi[i] = np.nan
                max_rsi[i] = np.nan
            else:
                window = rsi[i - stoch_window + 1:i + 1]
                min_rsi[i] = np.min(window)
                max_rsi[i] = np.max(window)
        stoch_rsi = (rsi - min_rsi) / (max_rsi - min_rsi + 1e-10) * 100
        return stoch_rsi

    @jit(nopython=True)
    def uo_numba(high, low, close, window1=7, window2=14, window3=28):
        n = len(close)
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        bp = close - np.minimum(low, prev_close)

        avg1 = np.empty(n)
        avg2 = np.empty(n)
        avg3 = np.empty(n)
        for i in range(n):
            if i < window1 - 1:
                avg1[i] = np.nan
            else:
                avg1[i] = np.sum(bp[i - window1 + 1:i + 1]) / np.sum(tr[i - window1 + 1:i + 1])

            if i < window2 - 1:
                avg2[i] = np.nan
            else:
                avg2[i] = np.sum(bp[i - window2 + 1:i + 1]) / np.sum(tr[i - window2 + 1:i + 1])

            if i < window3 - 1:
                avg3[i] = np.nan
            else:
                avg3[i] = np.sum(bp[i - window3 + 1:i + 1]) / np.sum(tr[i - window3 + 1:i + 1])

        uo = 100 * ((4 * avg1) + (2 * avg2) + avg3) / 7
        return uo

else:
    def ema_numba(close, window):
        return pd.Series(close).ewm(span=window, adjust=False).mean().values

    def atr_numba(high, low, close, window):
        tr1 = high - low
        tr2 = np.abs(high - np.roll(close, 1))
        tr3 = np.abs(low - np.roll(close, 1))
        tr = np.maximum(tr1, np.maximum(tr2, tr3))
        tr[0] = tr1[0]
        return pd.Series(tr).ewm(span=window, adjust=False).mean().values

    def sma_numba(arr, window):
        return pd.Series(arr).rolling(window).mean().values

    def wma_numba(arr, window):
        weights = np.arange(1, window + 1)
        return pd.Series(arr).rolling(window).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True).values

    def roc_numba(arr, period):
        return ((pd.Series(arr) / pd.Series(arr).shift(period)) - 1) * 100

    def bb_width_numba(close, window, std_dev=2.0):
        sma = pd.Series(close).rolling(window).mean().values
        std = pd.Series(close).rolling(window).std().values
        upper = sma + std_dev * std
        lower = sma - std_dev * std
        width = upper - lower
        return sma, upper, lower, width

    def keltner_channel_numba(high, low, close, window_atr, multiplier_atr, window_sma):
        atr_val = atr_numba(high, low, close, window_atr)
        sma_val = sma_numba(close, window_sma)
        upper = sma_val + multiplier_atr * atr_val
        lower = sma_val - multiplier_atr * atr_val
        mid = sma_val
        return upper, mid, lower

    def trix_numba(close, window):
        ema1 = ema_numba(close, window)
        ema2 = ema_numba(ema1, window)
        ema3 = ema_numba(ema2, window)
        trix = np.diff(ema3, prepend=ema3[0]) / (ema3 + 1e-10) * 100
        trix[0] = np.nan
        return trix

    def cci_numba(high, low, close, window):
        tp = (high + low + close) / 3
        sma_tp = pd.Series(tp).rolling(window).mean().values
        mad = pd.Series(np.abs(tp - sma_tp)).rolling(window).mean().values
        cci = (tp - sma_tp) / (0.015 * (mad + 1e-10))
        return cci

    def williams_r_numba(high, low, close, window):
        hh = pd.Series(high).rolling(window).max().values
        ll = pd.Series(low).rolling(window).min().values
        wr = -100 * (hh - close) / (hh - ll + 1e-10)
        return wr

    def mom_numba(close, window):
        return pd.Series(close).diff(window).values

    def ppo_numba(close, fast, slow, signal):
        ema_f = ema_numba(close, fast)
        ema_s = ema_numba(close, slow)
        ppo_line = (ema_f - ema_s) / (ema_s + 1e-10) * 100
        ppo_signal = ema_numba(ppo_line, signal)
        ppo_hist = ppo_line - ppo_signal
        return ppo_line, ppo_signal, ppo_hist

    def stoch_rsi_numba(close, rsi_window, stoch_window):
        delta = np.diff(close, prepend=close[0])
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = pd.Series(gain).ewm(alpha=1/ rsi_window, adjust=False).mean().values
        avg_loss = pd.Series(loss).ewm(alpha=1/ rsi_window, adjust=False).mean().values
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        min_rsi = pd.Series(rsi).rolling(stoch_window).min().values
        max_rsi = pd.Series(rsi).rolling(stoch_window).max().values
        stoch_rsi = 100 * (rsi - min_rsi) / (max_rsi - min_rsi + 1e-10)
        return stoch_rsi

    def uo_numba(high, low, close, window1=7, window2=14, window3=28):
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        bp = close - np.minimum(low, prev_close)
        avg1 = pd.Series(bp).rolling(window1).sum().values / pd.Series(tr).rolling(window1).sum().values
        avg2 = pd.Series(bp).rolling(window2).sum().values / pd.Series(tr).rolling(window2).sum().values
        avg3 = pd.Series(bp).rolling(window3).sum().values / pd.Series(tr).rolling(window3).sum().values
        uo = 100 * ((4 * avg1) + (2 * avg2) + avg3) / 7
        return uo


# ==================== 主函数：计算全部技术指标 ====================
def compute_all_kline_indicators(df: pd.DataFrame, 
                                fast_ema=[3, 5, 8, 10], 
                                slow_ema=[12, 26, 50, 100, 200],
                                rsi_windows=[14, 7, 25],
                                stoch_windows=[14, 21],
                                atr_windows=[14, 10, 20],
                                bb_windows=[14, 20],
                                adx_window=14,
                                use_numba=True) -> pd.DataFrame:

    required = ['time', 'open', 'high', 'low', 'close', 'volume']
    for col in required:
        if col not in df.columns:
            raise ValueError(f"缺少必要列: {col}")

    df = df.copy().sort_values('time').reset_index(drop=True)
    open_ = df['open'].values
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    volume = df['volume'].values
    n = len(close)

    result = {'time': df['time']}

    for window in [3, 5, 8, 10, 14, 20, 25, 50, 100, 150, 200]:
        sma = sma_numba(close, window)
        result[f'SMA_{window}'] = sma

    for window in fast_ema + slow_ema:
        ema = ema_numba(close, window)
        result[f'EMA_{window}'] = ema

    for window in [10, 14, 20, 50]:
        wma = wma_numba(close, window)
        result[f'WMA_{window}'] = wma

    for window in bb_windows:
        _, bb_upper, bb_lower, bb_width = bb_width_numba(close, window, 2.0)
        result[f'BB_upper_{window}'] = bb_upper
        result[f'BB_lower_{window}'] = bb_lower
        result[f'BB_width_{window}'] = bb_width
        result[f'BB_percent_{window}'] = (close - bb_lower) / (bb_upper - bb_lower + 1e-10) * 100

    for window in atr_windows:
        atr = atr_numba(high, low, close, window)
        result[f'ATR_{window}'] = atr
        result[f'ATR_pct_{window}'] = atr / close * 100

    for window in rsi_windows:
        delta = np.diff(close, prepend=close[0])
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = pd.Series(gain).ewm(span=window, adjust=False).mean().values
        avg_loss = pd.Series(loss).ewm(span=window, adjust=False).mean().values
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        result[f'RSI_{window}'] = rsi

    for window in stoch_windows:
        low_min = pd.Series(low).rolling(window).min().values
        high_max = pd.Series(high).rolling(window).max().values
        stoch_k = 100 * (close - low_min) / (high_max - low_min + 1e-10)
        stoch_d = pd.Series(stoch_k).rolling(3).mean().values
        result[f'%K_{window}'] = stoch_k
        result[f'%D_{window}'] = stoch_d
        result[f'%DSlow_{window}'] = pd.Series(stoch_d).rolling(3).mean().values

    macd_fast, macd_slow, macd_signal = 12, 26, 9
    ema_fast = ema_numba(close, macd_fast)
    ema_slow = ema_numba(close, macd_slow)
    macd_line = ema_fast - ema_slow
    macd_signal_line = ema_numba(macd_line, macd_signal)
    macd_hist = macd_line - macd_signal_line
    result['MACD'] = macd_line
    result['MACD_signal'] = macd_signal_line
    result['MACD_hist'] = macd_hist

    ppo_fast, ppo_slow, ppo_signal = 12, 26, 9
    ppo_line, ppo_sig, ppo_hist = ppo_numba(close, ppo_fast, ppo_slow, ppo_signal)
    result['PPO'] = ppo_line
    result['PPO_signal'] = ppo_sig
    result['PPO_hist'] = ppo_hist

    for window_atr in [10, 14, 20]:
        upper, mid, lower = keltner_channel_numba(high, low, close, window_atr, 1.5, window_atr)
        result[f'KC_upper_{window_atr}'] = upper
        result[f'KC_mid_{window_atr}'] = mid
        result[f'KC_lower_{window_atr}'] = lower
        result[f'KC_bandwidth_{window_atr}'] = (upper - lower) / mid * 100

    for window in [14, 20, 50]:
        cci = cci_numba(high, low, close, window)
        result[f'CCI_{window}'] = cci

    for window in [14, 21, 28]:
        wr = williams_r_numba(high, low, close, window)
        result[f'Williams_%R_{window}'] = wr

    for window in [5, 10, 14, 20, 50]:
        mom = mom_numba(close, window)
        result[f'Momentum_{window}'] = mom

    for window in [5, 10, 12, 25, 50]:
        roc = roc_numba(close, window)
        result[f'ROC_{window}'] = roc

    for window in [12, 15, 20, 30]:
        trix = trix_numba(close, window)
        result[f'TRIX_{window}'] = trix
        result[f'TRIX_signal_{window}'] = ema_numba(trix, 9)

    for window in [14, 21]:
        stoch_rsi = stoch_rsi_numba(close, window, 14)
        result[f'StochRSI_{window}'] = stoch_rsi
        result[f'StochRSI_D_{window}'] = pd.Series(stoch_rsi).rolling(3).mean().values

    uo = uo_numba(high, low, close)
    result['UO'] = uo

    tr1 = high - low
    tr2 = np.abs(high - np.roll(close, 1))
    tr3 = np.abs(low - np.roll(close, 1))
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    tr[0] = tr1[0]

    up_move = high - np.roll(high, 1)
    down_move = np.roll(low, 1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    smooth_tr = pd.Series(tr).ewm(span=adx_window, adjust=False).mean().values
    smooth_plus_dm = pd.Series(plus_dm).ewm(span=adx_window, adjust=False).mean().values
    smooth_minus_dm = pd.Series(minus_dm).ewm(span=adx_window, adjust=False).mean().values

    plus_di = 100 * smooth_plus_dm / (smooth_tr + 1e-10)
    minus_di = 100 * smooth_minus_dm / (smooth_tr + 1e-10)
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = pd.Series(dx).ewm(span=adx_window, adjust=False).mean().values

    result['ADX'] = adx
    result['+DI'] = plus_di
    result['-DI'] = minus_di

    tr_sum = pd.Series(tr).rolling(adx_window).sum().values
    vp = pd.Series(np.abs(high - np.roll(low, 1))).rolling(adx_window).sum().values
    vm = pd.Series(np.abs(low - np.roll(high, 1))).rolling(adx_window).sum().values
    vi_plus = vp / (tr_sum + 1e-10)
    vi_minus = vm / (tr_sum + 1e-10)
    result['VI_plus'] = vi_plus
    result['VI_minus'] = vi_minus
    result['VI_diff'] = vi_plus - vi_minus

    median_price = (high + low) / 2
    ao = sma_numba(median_price, 5) - sma_numba(median_price, 34)
    result['AO'] = ao

    force = (close - np.roll(close, 1)) * volume
    for window in [2, 13]:
        fi = pd.Series(force).ewm(span=window, adjust=False).mean().values
        result[f'ForceIndex_{window}'] = fi

    distance = ((high + low) / 2 - (np.roll(high, 1) + np.roll(low, 1)) / 2) * (high - low) / volume
    eom = pd.Series(distance).rolling(14).mean().values
    result['EOM'] = eom

    hl_avg = (high + low) / 2
    cum_vol = np.cumsum(volume)
    cum_vwap = np.cumsum(hl_avg * volume)
    vwap = np.where(cum_vol > 0, cum_vwap / cum_vol, np.nan)
    result['VWAP'] = vwap

    obv = np.zeros(n)
    for i in range(1, n):
        if close[i] > close[i - 1]:
            obv[i] = obv[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            obv[i] = obv[i - 1] - volume[i]
        else:
            obv[i] = obv[i - 1]
    result['OBV'] = obv
    result['OBV_EMA_10'] = ema_numba(obv, 10)

    mf_multiplier = ((close - low) - (high - close)) / (high - low + 1e-10)
    mf_volume = mf_multiplier * volume
    cmf = pd.Series(mf_volume).rolling(20).sum().values / pd.Series(volume).rolling(20).sum().values
    result['CMF'] = cmf

    typical_price = (high + low + close) / 3
    money_flow = typical_price * volume
    pos_flow = np.where(typical_price > np.roll(typical_price, 1), money_flow, 0)
    neg_flow = np.where(typical_price < np.roll(typical_price, 1), money_flow, 0)
    pos_sum = pd.Series(pos_flow).rolling(14).sum().values
    neg_sum = pd.Series(neg_flow).rolling(14).sum().values
    mfi = 100 - (100 / (1 + pos_sum / (neg_sum + 1e-10)))
    result['MFI_14'] = mfi

    ema_13 = ema_numba(close, 13)
    bull_power = high - ema_13
    bear_power = low - ema_13
    result['BullPower'] = bull_power
    result['BearPower'] = bear_power

    roc1 = roc_numba(close, 10)
    roc2 = roc_numba(close, 15)
    roc3 = roc_numba(close, 20)
    roc4 = roc_numba(close, 30)
    kst = (
        pd.Series(roc1).ewm(span=10).mean().values +
        pd.Series(roc2).ewm(span=10).mean().values * 2 +
        pd.Series(roc3).ewm(span=10).mean().values * 3 +
        pd.Series(roc4).ewm(span=15).mean().values * 4
    )
    kst_signal = pd.Series(kst).ewm(span=9).mean().values
    result['KST'] = kst
    result['KST_signal'] = kst_signal

    sar = np.full(n, np.nan)
    ep = high[0]
    af = 0.02
    trend = 1
    sar[0] = low[0]
    for i in range(1, n):
        if trend == 1:
            sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
            if high[i] > ep:
                ep = high[i]
                af = min(af + 0.02, 0.2)
            if low[i] < sar[i]:
                trend = -1
                sar[i] = ep
                ep = low[i]
                af = 0.02
        else:
            sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
            if low[i] < ep:
                ep = low[i]
                af = min(af + 0.02, 0.2)
            if high[i] > sar[i]:
                trend = 1
                sar[i] = ep
                ep = high[i]
                af = 0.02
        sar[i] = sar[i] if trend == 1 else sar[i]
    result['SAR'] = sar

    for window in [14, 20]:
        std = pd.Series(close).rolling(window).std().values
        mean = sma_numba(close, window)
        result[f'SDB_upper_{window}'] = mean + 2 * std
        result[f'SDB_lower_{window}'] = mean - 2 * std

    vol_ratio = pd.Series(high - low).rolling(14).mean().values / pd.Series(close).rolling(14).mean().values
    result['Volatility_Ratio_14'] = vol_ratio

    for window in [5, 10, 20]:
        prc = (close / np.roll(close, window) - 1) * 100
        result[f'PRC_{window}'] = prc

    vol_short = pd.Series(volume).ewm(span=5).mean().values
    vol_long = pd.Series(volume).ewm(span=20).mean().values
    vol_osc = (vol_short - vol_long) / vol_long * 100
    result['Volume_Osc'] = vol_osc

    clv = ((close - low) - (high - close)) / (high - low + 1e-10)
    adl = np.cumsum(clv * volume)
    result['ADL'] = adl
    result['ADL_EMA_10'] = ema_numba(adl, 10)

    for window in [5, 10, 14]:
        disp = close / sma_numba(close, window) * 100
        result[f'Disparity_{window}'] = disp

    for window in [10, 20]:
        tma = pd.Series(close).rolling(window).mean().rolling(window//2).mean().values
        result[f'TMA_{window}'] = tma

    change = np.abs(close - np.roll(close, 1))
    volatility_ = pd.Series(change).rolling(10).sum().values
    er = np.where(volatility_ != 0, change / volatility_, 0)
    sc = (er * (0.666 - 0.0645) + 0.0645) ** 2
    kama = np.full(n, np.nan)
    kama[0] = close[0]
    for i in range(1, n):
        if not np.isnan(sc[i]):
            kama[i] = kama[i - 1] + sc[i] * (close[i] - kama[i - 1])
    result['KAMA'] = kama

    EMA_26 = ema_numba(close, 20)
    result['Speed_Line_0.5'] = EMA_26 * 0.5
    result['Speed_Line_1.0'] = EMA_26 * 1.0
    result['Speed_Line_1.5'] = EMA_26 * 1.5
    result['Speed_Line_2.0'] = EMA_26 * 2.0

    prev_high = np.roll(high, 1)
    prev_low = np.roll(low, 1)
    prev_close = np.roll(close, 1)
    pivot = (prev_high + prev_low + prev_close) / 3
    r1 = 2 * pivot - prev_low
    s1 = 2 * pivot - prev_high
    r2 = pivot + (prev_high - prev_low)
    s2 = pivot - (prev_high - prev_low)
    r3 = prev_high + 2 * (pivot - prev_low)
    s3 = prev_low - 2 * (prev_high - pivot)
    result['Pivot'] = pivot
    result['R1'] = r1
    result['S1'] = s1
    result['R2'] = r2
    result['S2'] = s2
    result['R3'] = r3
    result['S3'] = s3

    lookback = 10
    rolling_high = pd.Series(high).rolling(lookback).max().values
    rolling_low = pd.Series(low).rolling(lookback).min().values
    fib_range = rolling_high - rolling_low
    result['Fib_0.236'] = rolling_high - 0.236 * fib_range
    result['Fib_0.382'] = rolling_high - 0.382 * fib_range
    result['Fib_0.5'] = rolling_high - 0.5 * fib_range
    result['Fib_0.618'] = rolling_high - 0.618 * fib_range
    result['Fib_0.786'] = rolling_high - 0.786 * fib_range

    for window in [14, 20, 50]:
        dc_upper = pd.Series(high).rolling(window).max().values
        dc_lower = pd.Series(low).rolling(window).min().values
        result[f'Donchian_Upper_{window}'] = dc_upper
        result[f'Donchian_Lower_{window}'] = dc_lower
        result[f'Donchian_Mid_{window}'] = (dc_upper + dc_lower) / 2

    bb_std = pd.Series(close).rolling(20).std().values
    kc_atr = atr_numba(high, low, close, 20)
    kc_width = 1.5 * kc_atr
    bb_width = 2 * bb_std
    squeeze_on = bb_width < kc_width
    squeeze_off = bb_width > kc_width
    result['TTM_Squeeze_On'] = squeeze_on.astype(float)
    result['TTM_Squeeze_Off'] = squeeze_off.astype(float)

    price_bins = np.linspace(close.min(), close.max(), 20)
    volume_profile = np.zeros_like(close)
    for i in range(len(price_bins)-1):
        mask = (close >= price_bins[i]) & (close < price_bins[i+1])
        volume_profile[mask] = np.sum(volume[mask]) / np.sum(mask) if np.sum(mask) > 0 else 0
    result['Volume_Profile'] = volume_profile

    for window in [14, 50]:
        mean = pd.Series(close).rolling(window).mean().values
        std = pd.Series(close).rolling(window).std().values
        zscore = (close - mean) / (std + 1e-10)
        result[f'Price_ZScore_{window}'] = zscore

    for window in [10, 20]:
        x = np.arange(window)
        slope = np.empty(n)
        for i in range(window-1, n):
            y = close[i-window+1:i+1]
            slope[i] = np.polyfit(x, y, 1)[0]
        result[f'LR_Slope_{window}'] = slope

    for window in [10, 20]:
        corr = pd.Series(close).rolling(window).corr(pd.Series(volume))
        result[f'Corr_Close_Vol_{window}'] = corr.values

    for window in [10, 20]:
        se = np.empty(n)
        x = np.arange(window)
        for i in range(window-1, n):
            y = close[i-window+1:i+1]
            sl, intercept = np.polyfit(x, y, 1)
            y_pred = sl * x + intercept
            se[i] = np.sqrt(np.mean((y - y_pred)**2))
        result[f'StdError_{window}'] = se

    jaw = sma_numba(close, 13)
    teeth = sma_numba(close, 8)
    lips = sma_numba(close, 5)
    result['Alligator_Jaw'] = np.roll(jaw, 8)
    result['Alligator_Teeth'] = np.roll(teeth, 5)
    result['Alligator_Lips'] = np.roll(lips, 3)

    mfi_val = (high - low) / volume
    result['MFI'] = mfi_val
    result['MFI_EMA_5'] = ema_numba(mfi_val, 5)

    for window in [10, 20]:
        pc_high = pd.Series(high).rolling(window).max().values
        pc_low = pd.Series(low).rolling(window).min().values
        result[f'PriceChannel_High_{window}'] = pc_high
        result[f'PriceChannel_Low_{window}'] = pc_low

    swing_high = (
        (high > np.roll(high, 1)) &
        (high > np.roll(high, 2)) &
        (high > np.roll(high, -1)) &
        (high > np.roll(high, -2))
    ).astype(int)
    swing_low = (
        (low < np.roll(low, 1)) &
        (low < np.roll(low, 2)) &
        (low < np.roll(low, -1)) &
        (low < np.roll(low, -2))
    ).astype(int)
    result['SwingHigh'] = np.roll(swing_high, 2)
    result['SwingLow'] = np.roll(swing_low, 2)

    for window in [10, 20, 50]:
        avg_vol = pd.Series(volume).rolling(window).mean().values
        result[f'AvgVolume_{window}'] = avg_vol

    vol_ma = pd.Series(volume).rolling(20).mean().values
    vol_spike = (volume > vol_ma * 2).astype(float)
    result['Vol_Spike'] = vol_spike

    result['OBV_MA_10'] = ema_numba(result['OBV'], 10)

    nvi = np.zeros(n)
    nvi[0] = 1000
    for i in range(1, n):
        if volume[i] < volume[i - 1]:
            nvi[i] = nvi[i - 1] * (1 + (close[i] - close[i - 1]) / close[i - 1])
        else:
            nvi[i] = nvi[i - 1]
    result['NVI'] = nvi
    result['NVI_EMA_255'] = ema_numba(nvi, 255)

    pvi = np.zeros(n)
    pvi[0] = 1000
    for i in range(1, n):
        if volume[i] > volume[i - 1]:
            pvi[i] = pvi[i - 1] * (1 + (close[i] - close[i - 1]) / close[i - 1])
        else:
            pvi[i] = pvi[i - 1]
    result['PVI'] = pvi
    result['PVI_EMA_255'] = ema_numba(pvi, 255)

    for window in [9, 14]:
        delta = np.diff(close, prepend=close[0])
        pos_sum = np.zeros(n)
        neg_sum = np.zeros(n)
        for i in range(1, n):
            if delta[i] > 0:
                pos_sum[i] = pos_sum[i - 1] + delta[i]
                neg_sum[i] = neg_sum[i - 1]
            else:
                pos_sum[i] = pos_sum[i - 1]
                neg_sum[i] = neg_sum[i - 1] - delta[i]
        cmo = 100 * (pos_sum - neg_sum) / (pos_sum + neg_sum + 1e-10)
        result[f'CMO_{window}'] = cmo

    bop = (close - open_) / (high - low + 1e-10)
    result['BOP'] = bop

    for fast, slow in [(5, 35), (12, 26)]:
        fast_ema = ema_numba(close, fast)
        slow_ema = ema_numba(close, slow)
        po = fast_ema - slow_ema
        result[f'PriceOsc_{fast}_{slow}'] = po

    for window in [10, 20]:
        ema1 = ema_numba(close, window)
        ema2 = ema_numba(ema1, window)
        ema3 = ema_numba(ema2, window)
        tema = 3 * ema1 - 3 * ema2 + ema3
        result[f'TEMA_{window}'] = tema

    for window in [9, 14, 20]:
        half_length = int(window / 2)
        sqrt_length = int(np.sqrt(window))
        wma_half = wma_numba(close, half_length)
        wma_full = wma_numba(close, window)
        hma = wma_numba(2 * wma_half - wma_full, sqrt_length)
        result[f'HMA_{window}'] = hma

    vwap_dev = (close - result['VWAP']) / result['VWAP'] * 100
    result['VWAP_Deviation'] = vwap_dev

    oc_spread = (close - open_) / open_ * 100
    result['OC_Spread'] = oc_spread

    hl_spread = (high - low) / close * 100
    result['HL_Spread'] = hl_spread

    for window in [10, 20]:
        s = pd.Series(close)
        rank = s.rolling(window).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100, raw=False)
        result[f'Close_Rank_{window}'] = rank.values

    vol_mean = pd.Series(hl_spread).rolling(14).mean().values
    vol_std_ = pd.Series(hl_spread).rolling(14).std().values
    breakout = (hl_spread > vol_mean + 1.5 * vol_std_).astype(float)
    result['Vol_Breakout'] = breakout

    gap_up = (open_ > np.roll(high, 1)).astype(float)
    gap_down = (open_ < np.roll(low, 1)).astype(float)
    result['Gap_Up'] = gap_up
    result['Gap_Down'] = gap_down

    inside_bar = (high <= np.roll(high, 1)) & (low >= np.roll(low, 1))
    outside_bar = (high >= np.roll(high, 1)) & (low <= np.roll(low, 1))
    result['Inside_Bar'] = inside_bar.astype(float)
    result['Outside_Bar'] = outside_bar.astype(float)

    bull_engulf = (close > open_) & (close > np.roll(open_, 1)) & (open_ < np.roll(close, 1))
    bear_engulf = (close < open_) & (close < np.roll(open_, 1)) & (open_ > np.roll(close, 1))
    result['Bullish_Engulfing'] = bull_engulf.astype(float)
    result['Bearish_Engulfing'] = bear_engulf.astype(float)

    body = np.abs(close - open_)
    upper_shadow = high - np.maximum(open_, close)
    lower_shadow = np.minimum(open_, close) - low
    hammer = (lower_shadow > 2 * body) & (upper_shadow < 0.5 * body) & (close > open_)
    shooting_star = (upper_shadow > 2 * body) & (lower_shadow < 0.5 * body) & (close < open_)
    result['Hammer'] = hammer.astype(float)
    result['Shooting_Star'] = shooting_star.astype(float)

    doji = body / (high - low + 1e-10) < 0.1
    result['Doji'] = doji.astype(float)

    three_white = (
        (close > open_) &
        (np.roll(close, 1) > np.roll(open_, 1)) &
        (np.roll(close, 2) > np.roll(open_, 2)) &
        (close > np.roll(close, 1)) &
        (np.roll(close, 1) > np.roll(close, 2))
    ).astype(float)
    three_black = (
        (close < open_) &
        (np.roll(close, 1) < np.roll(open_, 1)) &
        (np.roll(close, 2) < np.roll(open_, 2)) &
        (close < np.roll(close, 1)) &
        (np.roll(close, 1) < np.roll(close, 2))
    ).astype(float)
    result['Three_White_Soldiers'] = three_white
    result['Three_Black_Crows'] = three_black

    morning_star = (
        (np.roll(close, 2) < np.roll(open_, 2)) &
        (np.abs(np.roll(close, 1) - np.roll(open_, 1)) < 0.3 * np.abs(np.roll(high, 1) - np.roll(low, 1))) &
        (close > open_) &
        (close > np.roll(open_, 2) + 0.5 * (np.roll(high, 2) - np.roll(low, 2)))
    ).astype(float)
    evening_star = (
        (np.roll(close, 2) > np.roll(open_, 2)) &
        (np.abs(np.roll(close, 1) - np.roll(open_, 1)) < 0.3 * np.abs(np.roll(high, 1) - np.roll(low, 1))) &
        (close < open_) &
        (close < np.roll(open_, 2) - 0.5 * (np.roll(high, 2) - np.roll(low, 2)))
    ).astype(float)
    result['Morning_Star'] = morning_star
    result['Evening_Star'] = evening_star

    piercing = (
        (np.roll(close, 1) < np.roll(open_, 1)) &
        (close > open_) &
        (close > (np.roll(open_, 1) + np.roll(close, 1)) / 2) &
        (close < np.roll(open_, 1))
    ).astype(float)
    dark_cloud = (
        (np.roll(close, 1) > np.roll(open_, 1)) &
        (close < open_) &
        (close < (np.roll(open_, 1) + np.roll(close, 1)) / 2) &
        (close > np.roll(open_, 1))
    ).astype(float)
    result['Piercing_Line'] = piercing
    result['Dark_Cloud_Cover'] = dark_cloud

    result['Trend_Strong'] = (result['ADX'] > 25).astype(float)
    result['Trend_Weak'] = (result['ADX'] < 20).astype(float)

    result['Trend_Up'] = (result['+DI'] > result['-DI']).astype(float)
    result['Trend_Down'] = (result['-DI'] > result['+DI']).astype(float)

    result['Vol_Regime_High'] = (result['ATR_14'] > result['ATR_14'].mean()).astype(float)
    result['Vol_Regime_Low'] = (result['ATR_14'] < result['ATR_14'].mean()).astype(float)

    for window in [10, 26, 50]:
        ema_val = result[f'EMA_{window}']
        result[f'Price_above_EMA_{window}'] = (close > ema_val).astype(float)
        result[f'Price_below_EMA_{window}'] = (close < ema_val).astype(float)

    for window in [14, 20]:
        upper = result[f'BB_upper_{window}']
        lower = result[f'BB_lower_{window}']
        result[f'BB_Position_{window}'] = (close - lower) / (upper - lower + 1e-10)

    result['MACD_Hist_Accel'] = np.diff(result['MACD_hist'], prepend=result['MACD_hist'][0])

    result['StochRSI_Accel'] = np.diff(result['StochRSI_14'], prepend=result['StochRSI_14'][0])

    for window in [5, 8, 13, 21, 34, 55]:
        ema_val = ema_numba(close, window)
        result[f'EMA_Ribbon_{window}'] = ema_val

    atr_val = atr_numba(high, low, close, 10)
    atr_mult = 3
    upper_band = (high + low) / 2 + atr_mult * atr_val
    lower_band = (high + low) / 2 - atr_mult * atr_val
    supertrend = np.full(n, np.nan)
    trend_arr = np.full(n, 1)
    for i in range(1, n):
        if close[i] > upper_band[i - 1]:
            trend_arr[i] = 1
        elif close[i] < lower_band[i - 1]:
            trend_arr[i] = -1
        else:
            trend_arr[i] = trend_arr[i - 1]
        if trend_arr[i] == 1:
            supertrend[i] = lower_band[i]
        else:
            supertrend[i] = upper_band[i]
    result['Supertrend'] = supertrend
    result['Supertrend_Trend'] = trend_arr

    for window in [20, 50]:
        dc_u = result[f'Donchian_Upper_{window}']
        dc_l = result[f'Donchian_Lower_{window}']
        result[f'Donchian_Breakout_U_{window}'] = (close >= dc_u).astype(float)
        result[f'Donchian_Breakout_D_{window}'] = (close <= dc_l).astype(float)

    vol_14 = pd.Series(hl_spread).rolling(14).std().values
    vol_5 = pd.Series(hl_spread).rolling(5).std().values
    result['Vol_Expansion'] = (vol_5 > vol_14 * 1.5).astype(float)

    result['Close_Open_Ratio'] = close / open_

    result['High_Low_Ratio'] = high / low

    result['Volume_Delta'] = volume - result['AvgVolume_20']

    result['VWAP_Close_Diff'] = close - result['VWAP']

    result['OBV_Slope'] = np.diff(result['OBV'], prepend=result['OBV'][0])

    result['EMA_10_cross_20_up'] = ((result['EMA_10'] > result['EMA_26']) & (np.roll(result['EMA_10'], 1) <= np.roll(result['EMA_26'], 1))).astype(float)
    result['EMA_10_cross_20_down'] = ((result['EMA_10'] < result['EMA_26']) & (np.roll(result['EMA_10'], 1) >= np.roll(result['EMA_26'], 1))).astype(float)

    result['MACD_Zero_Cross_Up'] = ((result['MACD'] > 0) & (np.roll(result['MACD'], 1) <= 0)).astype(float)
    result['MACD_Zero_Cross_Down'] = ((result['MACD'] < 0) & (np.roll(result['MACD'], 1) >= 0)).astype(float)

    result_df = pd.DataFrame(result)

    max_window = max([
        200, 150, 100, 50, 34, 26, 20, 14, 13, 12, 10, 9, 8, 5, 3
    ])
    result_df = result_df.iloc[max_window:].reset_index(drop=True)

    return result_df


def calculate_rates(df):
    required_cols = ['time', 'open', 'high', 'low', 'close', 'volume']
    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"DataFrame must contain columns: {required_cols}")

    new_df = pd.DataFrame()
    new_df['time'] = df['time'].copy()

    prev_close = df['close'].shift(1)
    new_df['open_rate'] = (df['open'] - prev_close) / prev_close
    new_df['high_rate'] = (df['high'] - prev_close) / prev_close
    new_df['low_rate'] = (df['low'] - prev_close) / prev_close
    new_df['close_rate'] = (df['close'] - prev_close) / prev_close

    volume_mean = df['volume'].mean()
    new_df['volume_rate'] = df['volume'] / volume_mean

    return new_df


def compute_future_extremes(df, k=20):
    df = df.sort_values('time').reset_index(drop=True)

    close = df['close'].values.astype(np.float64)
    high = df['high'].values.astype(np.float64)
    low = df['low'].values.astype(np.float64)
    n = len(close)

    up_3pct = np.zeros(n, dtype=bool)
    down_3pct = np.zeros(n, dtype=bool)

    upper_threshold = close * 1.10
    lower_threshold = close * 0.97

    for shift in range(1, k+1):
        if shift >= n:
            break

        future_high = high[shift:]
        future_low = low[shift:]

        current_upper = upper_threshold[:-shift]
        current_lower = lower_threshold[:-shift]

        up_mask = future_high >= current_upper
        down_mask = future_low <= current_lower

        start_idx = 0
        end_idx = n - shift
        up_3pct[start_idx:end_idx] |= up_mask
        down_3pct[start_idx:end_idx] |= down_mask

    result = df.copy()
    result['target_up_3pct_5'] = up_3pct
    result['target_down_3pct_5'] = down_3pct

    return result.iloc[:-k,:]
