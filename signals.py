import pandas as pd
import numpy as np
import ccxt

exchange = ccxt.binance({
    'enableRateLimit': True,
    'rateLimit': 1200,
})

SYMBOL_ALIASES = {
    "MATIC": "POL",
}

# ══════════════════════════════════════════════════════════════════════
# TREND PARAMETRELERİ  (Pine Script: Trend Analysis [Mr_Rakun])
# ══════════════════════════════════════════════════════════════════════
TREND_PERIOD       = 20           # Trend hesaplama periyodu (5-200)
TREND_METHOD       = "Linear Regression"
# Seçenekler: "Linear Regression" | "MA Crossover" | "High/Low" | "Momentum" | "ADX"
TREND_STRENGTH_MIN = 30           # Sinyal için minimum R² skoru (0-100)

SL_ATR_MULT = 1.5
TP_ATR_MULT = 3.0

VOLATILITY_PROFILES = {
    "BTC":  {"sl_mult": 1.4, "tp_mult": 3.0},   # 1:2.5
    "ETH":  {"sl_mult": 1.4, "tp_mult": 3.0},   # 1:2.5
    "SOL":  {"sl_mult": 1.5, "tp_mult": 3.0},  # 1:2.5
    "AVAX": {"sl_mult": 1.5, "tp_mult": 3.0},  # 1:2.5
    "XRP":  {"sl_mult": 1.5, "tp_mult": 3.0},  # 1:2.5
    "LINK": {"sl_mult": 1.5, "tp_mult": 3.0},  # 1:2.5
    "EGLD": {"sl_mult": 2.0, "tp_mult": 4.0},   # 1:2.5
    "DOGE": {"sl_mult": 2.0, "tp_mult": 4.0},   # 1:2.5
    "default": {"sl_mult": 1.5, "tp_mult": 3.0}, # 1:2.5
}

TRAIL_ACTIVATION = 0.3
TRAIL_DISTANCE   = 1.5


def get_coin_profile(symbol: str) -> dict:
    base = symbol.split("/")[0] if "/" in symbol else symbol
    return VOLATILITY_PROFILES.get(base, VOLATILITY_PROFILES["default"])

def get_dynamic_sl_mult(r2_score: float, base_sl: float) -> float:
    """
    R² yüksekse (sıkışma) → SL genişler (erken stop önlenir)
    R² düşükse (trendli) → SL normal kalır
    """
    if r2_score > 70:    # Aşırı sıkışma
        return max(base_sl, 2.5)
    elif r2_score > 50:  # Güçlü sıkışma
        return max(base_sl, 2.0)
    elif r2_score > 30:  # Orta
        return max(base_sl, 1.5)
    else:                # Trendli
        return base_sl   # Profildeki değeri kullan


# ══════════════════════════════════════════════════════════════════════
# TEMEL VERİ FONKSİYONLARI
# ══════════════════════════════════════════════════════════════════════

def get_current_price(symbol: str) -> float:
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker["last"])
    except Exception as e:
        raise Exception(f"Fiyat alınamadı: {e}")


def get_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 150) -> pd.DataFrame:
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        raise Exception(f"OHLCV alınamadı: {e}")


def calc_atr(df: pd.DataFrame, period: int = 10) -> pd.Series:
    high  = df["high"]
    low   = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_ema(series: pd.Series, span: int) -> pd.Series:
    """market_regime.py tarafından kullanılıyor — tutuldu."""
    return series.ewm(span=span, adjust=False).mean()

def get_dynamic_atr_mult(r2_score: float) -> float:
    """
    R² yüksekse (sıkışma) → ATR periyodu büyür → SL genişler
    R² düşükse (trendli) → ATR periyodu normal → SL normal
    """
    if r2_score > 70:    # Aşırı sıkışma
        return 2.5        # SL 2.5x ATR (geniş)
    elif r2_score > 50:  # Güçlü sıkışma
        return 2.0        # SL 2.0x ATR
    elif r2_score > 30:  # Orta
        return 1.5        # SL 1.5x ATR (normal)
    else:                 # Trendli
        return 1.2        # SL 1.2x ATR (dar, trend güvenli)


# ══════════════════════════════════════════════════════════════════════
# TREND ANALİZİ  — Pine Script determinePriceTrend() karşılığı
# ══════════════════════════════════════════════════════════════════════

def _calc_dmi(high: pd.Series, low: pd.Series, close: pd.Series,
              period: int = 14):
    """ADX + DI+ + DI- hesaplar (ADX yöntemi için)."""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low  - close.shift(1)).abs()
    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    up       = high.diff()
    down     = -low.diff()
    plus_dm  = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)

    di_plus  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr
    di_minus = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr
    di_sum   = di_plus + di_minus
    dx       = 100 * (di_plus - di_minus).abs() / di_sum.where(di_sum != 0, np.nan)
    adx      = dx.ewm(span=period, adjust=False).mean()
    return di_plus, di_minus, adx


def compute_trend_series(df: pd.DataFrame, length: int, method: str) -> pd.Series:
    """
    Pine Script: determinePriceTrend() — tüm bar'lar için vektörize.
    Döndürdüğü: pd.Series[int]  1=Yükseliş | -1=Düşüş | 0=Nötr
    """
    close = df["close"]
    n     = len(df)
    trend = pd.Series(0, index=df.index, dtype=int)

    if method == "MA Crossover":
        # Kısa/Uzun MA kıyaslaması
        short_ma = close.rolling(max(1, length // 2)).mean()
        long_ma  = close.rolling(length).mean()
        trend[short_ma > long_ma] =  1
        trend[short_ma < long_ma] = -1

    elif method == "Momentum":
        # Momentum tabanlı trend
        momentum = close.diff(length)
        mom_ma   = momentum.rolling(max(1, length // 2)).mean()
        trend[mom_ma > 0] =  1
        trend[mom_ma < 0] = -1

    elif method == "ADX":
        # Trend gücü + yönü (ADX > 25)
        di_plus, di_minus, adx = _calc_dmi(df["high"], df["low"], close, length)
        strong = adx > 25
        trend[strong & (di_plus  > di_minus)] =  1
        trend[strong & (di_minus > di_plus )] = -1

    elif method == "High/Low":
        # Yükselen tepe/dip analizi
        high = df["high"]
        low  = df["low"]
        for i in range(length + 1, n):
            rising_lows  = sum(
                1 for j in range(1, length - 1)
                if low.iloc[i - j] > low.iloc[i - j - 1]
            )
            rising_highs = sum(
                1 for j in range(1, length - 1)
                if high.iloc[i - j] > high.iloc[i - j - 1]
            )
            ratio = (rising_lows + rising_highs) / (length * 2)
            trend.iloc[i] = 1 if ratio > 0.6 else (-1 if ratio < 0.4 else 0)

    else:
        # "Linear Regression"  — varsayılan
        x      = np.arange(length, dtype=float)
        x_mean = x.mean()
        ss_xx  = ((x - x_mean) ** 2).sum()

        def lr_slope(y: np.ndarray) -> float:
            y_mean = y.mean()
            ss_xy  = ((x - x_mean) * (y - y_mean)).sum()
            slope  = ss_xy / ss_xx if ss_xx != 0 else 0.0
            last_y = y[-1]
            return (slope / last_y * 100.0) if last_y != 0 else 0.0

        normalized = close.rolling(length).apply(lr_slope, raw=True)
        trend[normalized >  0.1] =  1
        trend[normalized < -0.1] = -1

    return trend


def compute_strength_series(src: pd.Series, length: int) -> pd.Series:
    """
    Pine Script: calculateTrendStrength() — Rolling R² (0-100).
    Trendin ne kadar doğrusal olduğunu ölçer.
    """
    x      = np.arange(length, dtype=float)
    x_mean = x.mean()
    ss_xx  = ((x - x_mean) ** 2).sum()

    def r_squared(y: np.ndarray) -> float:
        y_mean = y.mean()
        ss_yy  = ((y - y_mean) ** 2).sum()
        ss_xy  = ((x - x_mean) * (y - y_mean)).sum()
        if ss_yy == 0 or ss_xx == 0:
            return 0.0
        r = ss_xy / np.sqrt(ss_xx * ss_yy)
        return min(float(r * r * 100), 100.0)

    return src.rolling(length).apply(r_squared, raw=True)


def _trend_label(trend: int) -> str:
    return "▲ YÜKSELİŞ" if trend == 1 else ("▼ DÜŞÜŞ" if trend == -1 else "─ NÖTR")


def _strength_label(s: float) -> str:
    if s > 70:
        return "AŞIRI GÜÇLÜ"
    if s > 50:
        return "GÜÇLÜ"
    if s > 30:
        return "ORTA"
    return "ZAYIF"


# ══════════════════════════════════════════════════════════════════════
# SİNYAL FONKSİYONLARI
# ══════════════════════════════════════════════════════════════════════

def detect_signal(symbol: str, timeframe: str = "1h",
                  method: str = TREND_METHOD,
                  trend_period: int = TREND_PERIOD) -> dict | None:
    """
    Trend yönü değişimini algılar → AL/SAT sinyali üretir.
    Pine Script: bullishStart / bearishStart mantığı.
    Güç filtresi: R² >= TREND_STRENGTH_MIN
    """
    df              = get_ohlcv(symbol, timeframe=timeframe, limit=150)
    atr_series      = calc_atr(df)
    rsi_series      = calc_rsi(df["close"])
    trend_series    = compute_trend_series(df, trend_period, method)
    strength_series = compute_strength_series(df["close"], trend_period)

    # Onaylanmış son iki kapanmış bar (açık bar hariç)
    cur_trend    = int(trend_series.iloc[-2])
    prev_trend   = int(trend_series.iloc[-3])
    cur_strength = float(strength_series.iloc[-2])
    cur_price    = float(df["close"].iloc[-2])
    cur_atr      = float(atr_series.iloc[-2])
    cur_rsi      = float(rsi_series.iloc[-2])

    # Pine Script: bullishStart = ta.change(priceTrend) == 2  (−1 veya 0 → 1)
    bullish_start = (prev_trend != 1)  and (cur_trend == 1)
    bearish_start = (prev_trend != -1) and (cur_trend == -1)

    if not (bullish_start or bearish_start):
        return None

    # R² güç filtresi
    if cur_strength < TREND_STRENGTH_MIN:
        return None

    profile  = get_coin_profile(symbol)
    base_sl  = profile["sl_mult"]
    tp_mult  = profile["tp_mult"]
    sl_mult  = get_dynamic_sl_mult(cur_strength, base_sl)
    
    # Dinamik SL: Sıkışmada genişle, trendde daral
    dynamic_sl_mult = get_dynamic_atr_mult(cur_strength)
    sl_mult = max(base_sl_mult, dynamic_sl_mult)  # Hangisi büyükse onu kullan

    if bullish_start:
        sl = cur_price - sl_mult * cur_atr
        tp = cur_price + tp_mult * cur_atr
        reason = (
            f"Trend YÜKSELİŞ'e döndü — {method}\n"
            f"R² Trend Gücü: %{cur_strength:.1f} ({_strength_label(cur_strength)})\n"
            f"RSI: {cur_rsi:.1f}\n"
            f"SL: {sl_mult}×ATR | TP: {tp_mult}×ATR | R:K 1:{tp_mult / sl_mult:.1f}"
        )
        return {
            "signal_type":      "BUY",
            "entry_price":      cur_price,
            "stop_loss":        sl,
            "take_profit":      tp,
            "atr":              cur_atr,
            "sl_mult":          sl_mult,
            "tp_mult":          tp_mult,
            "rsi":              round(cur_rsi, 1),
            "trend_method":     method,
            "trend_strength":   round(cur_strength, 1),
            "trend_direction":  1,
            "reason":           reason,
        }

    # bearish_start
    sl = cur_price + sl_mult * cur_atr
    tp = cur_price - tp_mult * cur_atr
    reason = (
        f"Trend DÜŞÜŞ'e döndü — {method}\n"
        f"R² Trend Gücü: %{cur_strength:.1f} ({_strength_label(cur_strength)})\n"
        f"RSI: {cur_rsi:.1f}\n"
        f"SL: {sl_mult}×ATR | TP: {tp_mult}×ATR | R:K 1:{tp_mult / sl_mult:.1f}"
    )
    return {
        "signal_type":      "SELL",
        "entry_price":      cur_price,
        "stop_loss":        sl,
        "take_profit":      tp,
        "atr":              cur_atr,
        "sl_mult":          sl_mult,
        "tp_mult":          tp_mult,
        "rsi":              round(cur_rsi, 1),
        "trend_method":     method,
        "trend_strength":   round(cur_strength, 1),
        "trend_direction":  -1,
        "reason":           reason,
    }


def calculate_signals(symbol: str, timeframe: str = "1h",
                       method: str = TREND_METHOD,
                       trend_period: int = TREND_PERIOD) -> dict:
    """/signals komutu için tam analiz verisi."""
    df              = get_ohlcv(symbol, timeframe=timeframe, limit=150)
    atr_series      = calc_atr(df)
    rsi_series      = calc_rsi(df["close"])
    trend_series    = compute_trend_series(df, trend_period, method)
    strength_series = compute_strength_series(df["close"], trend_period)

    close        = float(df["close"].iloc[-1])
    cur_trend    = int(trend_series.iloc[-1])
    cur_strength = float(strength_series.iloc[-1])
    atr_val      = float(atr_series.iloc[-1])
    rsi_val      = round(float(rsi_series.iloc[-1]), 1)

    # Lineer regresyon hattının son değeri
    if len(df) >= trend_period:
        y = df["close"].values[-trend_period:]
        coeffs  = np.polyfit(np.arange(trend_period, dtype=float), y, 1)
        regline = float(np.polyval(coeffs, trend_period - 1))
    else:
        regline = close

    # Karar
    if cur_trend == 1 and cur_strength >= TREND_STRENGTH_MIN:
        overall = "🟢 AL"
    elif cur_trend == -1 and cur_strength >= TREND_STRENGTH_MIN:
        overall = "🔴 SAT"
    else:
        overall = "🟡 BEKLE"

    profile = get_coin_profile(symbol)
    sl_mult = profile["sl_mult"]
    tp_mult = profile["tp_mult"]

    return {
        "symbol":        symbol,
        "price":         close,
        "trend":         cur_trend,
        "trend_text":    _trend_label(cur_trend),
        "strength":      round(cur_strength, 1),
        "strength_text": _strength_label(cur_strength),
        "atr":           round(atr_val, 6),
        "rsi":           rsi_val,
        "regline":       round(regline, 6),
        "overall":       overall,
        "sl_buy":        close - sl_mult * atr_val,
        "tp_buy":        close + tp_mult * atr_val,
        "sl_sell":       close + sl_mult * atr_val,
        "tp_sell":       close - tp_mult * atr_val,
        "sl_mult":       sl_mult,
        "tp_mult":       tp_mult,
        "trend_method":  method,
        "trend_period":  trend_period,
        "timeframe":     timeframe,
    }


def get_dashboard_data(symbol: str, timeframe: str = "1h",
                        method: str = TREND_METHOD,
                        trend_period: int = TREND_PERIOD) -> dict:
    """/dashboard ve /scan20 için özet veri."""
    df              = get_ohlcv(symbol, timeframe=timeframe, limit=150)
    atr_series      = calc_atr(df)
    rsi_series      = calc_rsi(df["close"])
    trend_series    = compute_trend_series(df, trend_period, method)
    strength_series = compute_strength_series(df["close"], trend_period)

    close        = float(df["close"].iloc[-1])
    cur_trend    = int(trend_series.iloc[-1])
    cur_strength = float(strength_series.iloc[-1])
    atr_val      = float(atr_series.iloc[-1])
    rsi_val      = round(float(rsi_series.iloc[-1]), 1)
    trend_emoji  = "🟢" if cur_trend == 1 else ("🔴" if cur_trend == -1 else "⚪")

    return {
        "symbol":        symbol,
        "price":         close,
        "trend":         cur_trend,
        "trend_emoji":   trend_emoji,
        "trend_text":    _trend_label(cur_trend),
        "strength":      round(cur_strength, 1),
        "strength_text": _strength_label(cur_strength),
        "atr":           round(atr_val, 6),
        "rsi":           rsi_val,
        "timeframe":     timeframe,
    }


# ══════════════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ══════════════════════════════════════════════════════════════════════

def format_price(price: float) -> str:
    if price >= 1:
        return f"${price:,.2f}"
    elif price >= 0.01:
        return f"${price:.4f}"
    else:
        return f"${price:.8f}"


def normalize_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    SPECIAL_MAP = {
        "AVAX": "AVAX/USDT",
        "XRP":  "XRP/USDT",
        "LINK": "LINK/USDT",
        "EGLD": "EGLD/USDT",
        "BTC":  "BTC/USDT",
        "ETH":  "ETH/USDT",
        "SOL":  "SOL/USDT",
    }
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
