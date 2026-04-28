import time
import pandas as pd
import numpy as np
from datetime import datetime
import ccxt

# Binance borsası (ücretsiz, limitsiz, hızlı)
exchange = ccxt.binance()

SYMBOL_ALIASES = {
    "MATIC": "POL",
}

SUPERTREND_PERIOD = 10
SUPERTREND_MULT = 3.0
SL_ATR_MULT = 1.5
TP_ATR_MULT = 3.0

_last_request_time = 0
_MIN_REQUEST_INTERVAL = 6.0  # CoinGecko ücretsiz API için güvenli bekleme


def _wait_for_rate_limit():
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def _get_coin_id(symbol: str) -> str:
    base = symbol.split("/")[0] if "/" in symbol else symbol
    return COIN_IDS.get(base, base.lower())


def get_current_price(symbol: str) -> float:
    """Binance'den anlık fiyat al."""
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker["last"])
    except Exception as e:
        raise Exception(f"Fiyat alınamadı: {e}")


def get_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 120) -> pd.DataFrame:
    """Binance'den OHLCV verisi çek."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        raise Exception(f"OHLCV alınamadı: {e}")


def calc_atr(df: pd.DataFrame, period: int = SUPERTREND_PERIOD) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def calc_supertrend(df, period=SUPERTREND_PERIOD, multiplier=SUPERTREND_MULT):
    atr = calc_atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2
    basic_ub, basic_lb = hl2 + multiplier * atr, hl2 - multiplier * atr
    final_ub, final_lb = basic_ub.copy(), basic_lb.copy()
    close = df["close"]

    for i in range(1, len(df)):
        if basic_ub.iloc[i] < final_ub.iloc[i-1] or close.iloc[i-1] > final_ub.iloc[i-1]:
            final_ub.iloc[i] = basic_ub.iloc[i]
        else:
            final_ub.iloc[i] = final_ub.iloc[i-1]
        if basic_lb.iloc[i] > final_lb.iloc[i-1] or close.iloc[i-1] < final_lb.iloc[i-1]:
            final_lb.iloc[i] = basic_lb.iloc[i]
        else:
            final_lb.iloc[i] = final_lb.iloc[i-1]

    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)
    supertrend.iloc[0], direction.iloc[0] = final_ub.iloc[0], -1

    for i in range(1, len(df)):
        if supertrend.iloc[i-1] == final_ub.iloc[i-1]:
            if close.iloc[i] <= final_ub.iloc[i]:
                supertrend.iloc[i], direction.iloc[i] = final_ub.iloc[i], -1
            else:
                supertrend.iloc[i], direction.iloc[i] = final_lb.iloc[i], 1
        else:
            if close.iloc[i] >= final_lb.iloc[i]:
                supertrend.iloc[i], direction.iloc[i] = final_lb.iloc[i], 1
            else:
                supertrend.iloc[i], direction.iloc[i] = final_ub.iloc[i], -1
    return supertrend, direction, atr


def calc_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def detect_signal(symbol, timeframe="1h"):
    df = get_ohlcv(symbol, timeframe=timeframe, limit=120)
    ema12 = calc_ema(df["close"], 12)
    ema26 = calc_ema(df["close"], 26)
    supertrend, direction, atr = calc_supertrend(df)

    cur_ema12, prev_ema12 = ema12.iloc[-2], ema12.iloc[-3]
    cur_ema26, prev_ema26 = ema26.iloc[-2], ema26.iloc[-3]
    cur_dir = direction.iloc[-2]
    cur_price = float(df["close"].iloc[-2])
    cur_atr = float(atr.iloc[-2])
    cur_st = float(supertrend.iloc[-2])

    crossed_up = prev_ema12 <= prev_ema26 and cur_ema12 > cur_ema26
    crossed_down = prev_ema12 >= prev_ema26 and cur_ema12 < cur_ema26

    if crossed_up and cur_dir == 1:
        return {
            "signal_type": "BUY", "entry_price": cur_price,
            "stop_loss": cur_price - SL_ATR_MULT * cur_atr,
            "take_profit": cur_price + TP_ATR_MULT * cur_atr,
            "atr": cur_atr, "ema12": round(cur_ema12, 4), "ema26": round(cur_ema26, 4),
            "supertrend": round(cur_st, 4), "supertrend_dir": 1,
            "reason": f"EMA12 ({cur_ema12:.2f}) EMA26'yı ({cur_ema26:.2f}) yukarı kesti\nSuperTrend POZİTİF"
        }
    if crossed_down and cur_dir == -1:
        return {
            "signal_type": "SELL", "entry_price": cur_price,
            "stop_loss": cur_price + SL_ATR_MULT * cur_atr,
            "take_profit": cur_price - TP_ATR_MULT * cur_atr,
            "atr": cur_atr, "ema12": round(cur_ema12, 4), "ema26": round(cur_ema26, 4),
            "supertrend": round(cur_st, 4), "supertrend_dir": -1,
            "reason": f"EMA12 ({cur_ema12:.2f}) EMA26'yı ({cur_ema26:.2f}) aşağı kesti\nSuperTrend NEGATİF"
        }
    return None


def get_dashboard_data(symbol, timeframe="1h"):
    df = get_ohlcv(symbol, timeframe=timeframe, limit=120)
    ema12, ema26 = calc_ema(df["close"], 12), calc_ema(df["close"], 26)
    supertrend, direction, atr_series = calc_supertrend(df)
    rsi_series = calc_rsi(df["close"])

    return {
        "symbol": symbol, "price": float(df["close"].iloc[-1]),
        "ema12": round(float(ema12.iloc[-1]), 4), "ema26": round(float(ema26.iloc[-1]), 4),
        "supertrend": round(float(supertrend.iloc[-1]), 4),
        "supertrend_dir": int(direction.iloc[-1]),
        "atr": round(float(atr_series.iloc[-1]), 4),
        "rsi": round(float(rsi_series.iloc[-1]), 1),
        "timeframe": timeframe
    }


def calculate_signals(symbol, timeframe="1h"):
    df = get_ohlcv(symbol, timeframe=timeframe, limit=120)
    ema12, ema26 = calc_ema(df["close"], 12), calc_ema(df["close"], 26)
    supertrend, direction, atr_series = calc_supertrend(df)
    rsi_series = calc_rsi(df["close"])

    close = float(df["close"].iloc[-1])
    e12, e26 = float(ema12.iloc[-1]), float(ema26.iloc[-1])
    st = float(supertrend.iloc[-1])
    st_dir = int(direction.iloc[-1])
    atr_val = float(atr_series.iloc[-1])
    rsi_val = round(float(rsi_series.iloc[-1]), 2)

    st_text = "🟢 POZİTİF" if st_dir == 1 else "🔴 NEGATİF"
    ema_text = "🟢 EMA12 > EMA26" if e12 > e26 else "🔴 EMA12 < EMA26"

    if st_dir == 1 and e12 > e26:
        overall = "🟢 AL"
    elif st_dir == -1 and e12 < e26:
        overall = "🔴 SAT"
    else:
        overall = "🟡 BEKLE"

    return {
        "symbol": symbol, "price": close, "ema12": round(e12, 4), "ema26": round(e26, 4),
        "ema_text": ema_text, "supertrend": round(st, 4), "supertrend_text": st_text,
        "atr": round(atr_val, 4), "rsi": rsi_val, "overall": overall,
        "sl_buy": close - SL_ATR_MULT * atr_val, "tp_buy": close + TP_ATR_MULT * atr_val,
        "sl_sell": close + SL_ATR_MULT * atr_val, "tp_sell": close - TP_ATR_MULT * atr_val,
        "timeframe": timeframe
    }


def format_price(price):
    if price >= 1: return f"${price:,.2f}"
    elif price >= 0.01: return f"${price:.4f}"
    else: return f"${price:.8f}"


def normalize_symbol(symbol):
    symbol = symbol.upper().strip()
    if "/" in symbol:
        base = symbol.split("/")[0]
        base = SYMBOL_ALIASES.get(base, base)
        return f"{base}/USD"
    if symbol.endswith("USDT"): base = symbol[:-4]
    elif symbol.endswith("USD"): base = symbol[:-3]
    else: base = symbol
    base = SYMBOL_ALIASES.get(base, base)
    return f"{base}/USD"
