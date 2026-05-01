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

# Coin bazlı volatilite profilleri
VOLATILITY_PROFILES = {
    "BTC": {"sl_mult": 1.0, "tp_mult": 2.5},
    "ETH": {"sl_mult": 1.2, "tp_mult": 2.8},
    "SOL": {"sl_mult": 1.5, "tp_mult": 3.0},
    "AVAX": {"sl_mult": 1.5, "tp_mult": 3.0},
    "XRP": {"sl_mult": 1.5, "tp_mult": 3.0},
    "LINK": {"sl_mult": 1.5, "tp_mult": 3.0},
    "EGLD": {"sl_mult": 1.8, "tp_mult": 3.5},
    "DOGE": {"sl_mult": 2.0, "tp_mult": 4.0},
    "default": {"sl_mult": 1.5, "tp_mult": 3.0}
}

def get_coin_profile(symbol: str) -> dict:
    base = symbol.split("/")[0] if "/" in symbol else symbol
    return VOLATILITY_PROFILES.get(base, VOLATILITY_PROFILES["default"])

TRAIL_ACTIVATION = 0.5
TRAIL_DISTANCE = 1.0


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
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def calc_supertrend(df: pd.DataFrame, period: int = SUPERTREND_PERIOD, multiplier: float = SUPERTREND_MULT):
    atr = calc_atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2

    basic_ub = hl2 + multiplier * atr
    basic_lb = hl2 - multiplier * atr

    final_ub = basic_ub.copy()
    final_lb = basic_lb.copy()

    close = df["close"]

    for i in range(1, len(df)):
        prev_ub = final_ub.iloc[i - 1]
        prev_lb = final_lb.iloc[i - 1]
        prev_close = close.iloc[i - 1]

        if basic_ub.iloc[i] < prev_ub or prev_close > prev_ub:
            final_ub.iloc[i] = basic_ub.iloc[i]
        else:
            final_ub.iloc[i] = prev_ub

        if basic_lb.iloc[i] > prev_lb or prev_close < prev_lb:
            final_lb.iloc[i] = basic_lb.iloc[i]
        else:
            final_lb.iloc[i] = prev_lb

    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)

    supertrend.iloc[0] = final_ub.iloc[0]
    direction.iloc[0] = -1

    for i in range(1, len(df)):
        prev_st = supertrend.iloc[i - 1]
        prev_ub = final_ub.iloc[i - 1]
        prev_lb = final_lb.iloc[i - 1]
        cur_close = close.iloc[i]

        if prev_st == prev_ub:
            if cur_close <= final_ub.iloc[i]:
                supertrend.iloc[i] = final_ub.iloc[i]
                direction.iloc[i] = -1
            else:
                supertrend.iloc[i] = final_lb.iloc[i]
                direction.iloc[i] = 1
        else:
            if cur_close >= final_lb.iloc[i]:
                supertrend.iloc[i] = final_lb.iloc[i]
                direction.iloc[i] = 1
            else:
                supertrend.iloc[i] = final_ub.iloc[i]
                direction.iloc[i] = -1

    return supertrend, direction, atr


def calc_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def detect_signal(symbol: str, timeframe: str = "1h") -> dict | None:
    df = get_ohlcv(symbol, timeframe=timeframe, limit=120)
    ema12 = calc_ema(df["close"], 12)
    ema26 = calc_ema(df["close"], 26)
    supertrend, direction, atr = calc_supertrend(df)

    cur_ema12 = ema12.iloc[-2]
    cur_ema26 = ema26.iloc[-2]
    cur_dir = direction.iloc[-2]
    cur_price = float(df["close"].iloc[-2])
    cur_atr = float(atr.iloc[-2])
    cur_st = float(supertrend.iloc[-2])

    # Son 3 barda kesişim var mı?
    crossed_up = False
    crossed_down = False
    for j in range(1, 4):
        # Sınır kontrolü
        if j+2 >= len(ema12) or j+1 >= len(ema12):
            break
        p12 = ema12.iloc[-j-2]
        p26 = ema26.iloc[-j-2]
        c12 = ema12.iloc[-j-1]
        c26 = ema26.iloc[-j-1]
        if p12 <= p26 and c12 > c26:
            crossed_up = True
        if p12 >= p26 and c12 < c26:
            crossed_down = True

    # Coin'in volatilite profilini al
    profile = get_coin_profile(symbol)
    sl_mult = profile["sl_mult"]
    tp_mult = profile["tp_mult"]

    if crossed_up and cur_dir == 1:
        sl = cur_price - sl_mult * cur_atr
        tp = cur_price + tp_mult * cur_atr
        reason = (
            f"EMA12 ({round(cur_ema12, 2)}) EMA26'yı ({round(cur_ema26, 2)}) yukarı kesti\n"
            f"SuperTrend POZİTİF — fiyat destek üstünde ({format_price(cur_st)})\n"
            f"SL: {sl_mult}xATR | TP: {tp_mult}xATR | R:R 1:{tp_mult/sl_mult:.1f}"
        )
        return {
            "signal_type": "BUY",
            "entry_price": cur_price,
            "stop_loss": sl,
            "take_profit": tp,
            "atr": cur_atr,
            "sl_mult": sl_mult,
            "tp_mult": tp_mult,
            "reason": reason,
            "ema12": round(cur_ema12, 4),
            "ema26": round(cur_ema26, 4),
            "supertrend": round(cur_st, 4),
            "supertrend_dir": 1,
        }

    if crossed_down and cur_dir == -1:
        sl = cur_price + sl_mult * cur_atr
        tp = cur_price - tp_mult * cur_atr
        reason = (
            f"EMA12 ({round(cur_ema12, 2)}) EMA26'yı ({round(cur_ema26, 2)}) aşağı kesti\n"
            f"SuperTrend NEGATİF — fiyat direnç altında ({format_price(cur_st)})\n"
            f"SL: {sl_mult}xATR | TP: {tp_mult}xATR | R:R 1:{tp_mult/sl_mult:.1f}"
        )
        return {
            "signal_type": "SELL",
            "entry_price": cur_price,
            "stop_loss": sl,
            "take_profit": tp,
            "atr": cur_atr,
            "sl_mult": sl_mult,
            "tp_mult": tp_mult,
            "reason": reason,
            "ema12": round(cur_ema12, 4),
            "ema26": round(cur_ema26, 4),
            "supertrend": round(cur_st, 4),
            "supertrend_dir": -1,
        }

    return None


def get_dashboard_data(symbol: str, timeframe: str = "1h") -> dict:
    df = get_ohlcv(symbol, timeframe=timeframe, limit=120)
    ema12 = calc_ema(df["close"], 12)
    ema26 = calc_ema(df["close"], 26)
    supertrend, direction, atr = calc_supertrend(df)
    rsi = calc_rsi(df["close"])

    close = float(df["close"].iloc[-1])
    e12 = float(ema12.iloc[-1])
    e26 = float(ema26.iloc[-1])
    st = float(supertrend.iloc[-1])
    st_dir = int(direction.iloc[-1])
    atr_val = float(atr.iloc[-1])
    rsi_val = round(float(rsi.iloc[-1]), 1)

    trend_emoji = "🟢" if st_dir == 1 else "🔴"
    ema_cross = "🟢 EMA12>26" if e12 > e26 else "🔴 EMA12<26"

    return {
        "symbol": symbol,
        "price": close,
        "ema12": round(e12, 4),
        "ema26": round(e26, 4),
        "supertrend": round(st, 4),
        "supertrend_dir": st_dir,
        "trend_emoji": trend_emoji,
        "ema_cross": ema_cross,
        "atr": round(atr_val, 4),
        "rsi": rsi_val,
        "timeframe": timeframe,
    }


def calculate_signals(symbol: str, timeframe: str = "1h") -> dict:
    df = get_ohlcv(symbol, timeframe=timeframe, limit=120)
    ema12 = calc_ema(df["close"], 12)
    ema26 = calc_ema(df["close"], 26)
    supertrend, direction, atr_series = calc_supertrend(df)
    rsi_series = calc_rsi(df["close"])

    close = float(df["close"].iloc[-1])
    e12 = float(ema12.iloc[-1])
    e26 = float(ema26.iloc[-1])
    st = float(supertrend.iloc[-1])
    st_dir = int(direction.iloc[-1])
    atr_val = float(atr_series.iloc[-1])
    rsi_val = round(float(rsi_series.iloc[-1]), 2)

    if st_dir == 1:
        st_text = "🟢 POZİTİF (Yükseliş)"
    else:
        st_text = "🔴 NEGATİF (Düşüş)"

    if e12 > e26:
        ema_text = "🟢 EMA12 > EMA26 (Yükseliş)"
    else:
        ema_text = "🔴 EMA12 < EMA26 (Düşüş)"

    if st_dir == 1 and e12 > e26:
        overall = "🟢 AL"
    elif st_dir == -1 and e12 < e26:
        overall = "🔴 SAT"
    else:
        overall = "🟡 BEKLE (Uyumsuzluk)"

    # Coin'in volatilite profilini al
    profile = get_coin_profile(symbol)
    sl_mult = profile["sl_mult"]
    tp_mult = profile["tp_mult"]

    sl_buy = close - sl_mult * atr_val
    tp_buy = close + tp_mult * atr_val
    sl_sell = close + sl_mult * atr_val
    tp_sell = close - tp_mult * atr_val

    return {
        "symbol": symbol,
        "price": close,
        "ema12": round(e12, 4),
        "ema26": round(e26, 4),
        "ema_text": ema_text,
        "supertrend": round(st, 4),
        "supertrend_text": st_text,
        "atr": round(atr_val, 4),
        "rsi": rsi_val,
        "overall": overall,
        "sl_buy": sl_buy,
        "tp_buy": tp_buy,
        "sl_sell": sl_sell,
        "tp_sell": tp_sell,
        "timeframe": timeframe,
    }


def format_price(price: float) -> str:
    if price >= 1:
        return f"${price:,.2f}"
    elif price >= 0.01:
        return f"${price:.4f}"
    else:
        return f"${price:.8f}"


def normalize_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    
    # Özel eşleştirmeler (Binance'de farklı olanlar)
    SPECIAL_MAP = {
        "AVAX": "AVAX/USDT",
        "XRP": "XRP/USDT",
        "LINK": "LINK/USDT",
        "EGLD": "EGLD/USDT",
        "BTC": "BTC/USDT",
        "ETH": "ETH/USDT",
        "SOL": "SOL/USDT",
    }
    
    # Eğer direkt eşleşme varsa onu kullan
    if "/" in symbol:
        base, quote = symbol.split("/", 1)
        base = SYMBOL_ALIASES.get(base, base)
        if base in SPECIAL_MAP:
            return SPECIAL_MAP[base]
        if quote in ("USD", "USDT"):
            return f"{base}/USDT"
        return f"{base}/{quote}"
    
    if symbol.endswith("USDT"):
        base = symbol[:-4]
    elif symbol.endswith("USD"):
        base = symbol[:-3]
    else:
        base = symbol
    
    base = SYMBOL_ALIASES.get(base, base)
    if base in SPECIAL_MAP:
        return SPECIAL_MAP[base]
    return f"{base}/USDT"
