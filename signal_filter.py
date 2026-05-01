# signal_filter.py
import ccxt
import pandas as pd
import numpy as np

exchange_futures = ccxt.binance({
    'options': {'defaultType': 'future'},
    'enableRateLimit': True,
})


def get_cvd_oi_data(symbol: str, timeframe: str = "1h", limit: int = 120):
    """Binance Futures'tan CVD ve Open Interest verisi çeker."""
    try:
        binance_symbol = symbol.replace("/", "")
        
        # Düzeltilmiş API çağrıları (büyük harf!)
        oi_raw = exchange_futures.fapiPublicGet_openInterestHist({
            'symbol': binance_symbol,
            'period': timeframe,
            'limit': limit,
        })
        taker_raw = exchange_futures.fapiPublicGet_takerBuySellVol({
            'symbol': binance_symbol,
            'period': timeframe,
            'limit': limit,
        })

        if not oi_raw or not taker_raw:
            return None

        oi_df = pd.DataFrame(oi_raw, columns=['timestamp', 'sumOpenInterest', 'sumOpenInterestValue'])
        oi_df['timestamp'] = pd.to_datetime(oi_df['timestamp'], unit='ms')
        oi_df['oi'] = pd.to_numeric(oi_df['sumOpenInterestValue'])

        taker_df = pd.DataFrame(taker_raw, columns=['timestamp', 'buyVol', 'sellVol'])
        taker_df['timestamp'] = pd.to_datetime(taker_df['timestamp'], unit='ms')
        taker_df['delta'] = pd.to_numeric(taker_df['buyVol']) - pd.to_numeric(taker_df['sellVol'])
        taker_df['cvd'] = taker_df['delta'].cumsum()

        merged = pd.merge(oi_df[['timestamp', 'oi']], taker_df[['timestamp', 'cvd']], on='timestamp', how='inner')
        return merged

    except Exception as e:
        print(f"CVD/OI verisi alınamadı: {e}")
        return None


def _trend(series: pd.Series, lookback: int = 5) -> str:
    """Son N değerin yönünü belirler: 'up', 'down' veya 'neutral'"""
    if len(series) < lookback:
        return 'neutral'
    recent = series.tail(lookback)
    slope = np.polyfit(range(len(recent)), recent.values, 1)[0]  # doğrusal eğim
    # eğim çok küçükse yatay kabul et
    if abs(slope) < (recent.std() / len(recent)) * 0.5:
        return 'neutral'
    return 'up' if slope > 0 else 'down'


def classify_signal(signal_type: str, cvd_series: pd.Series, oi_series: pd.Series) -> str:
    """Tabloya göre sinyali STRONG/WEAK/RANGE olarak sınıflandırır."""
    if cvd_series is None or oi_series is None or len(cvd_series) < 5:
        # veri yoksa varsayılan olarak WEAK dön (sinyali gönder ama güçsüz)
        return "WEAK_LONG" if signal_type == "BUY" else "WEAK_SHORT"

    cvd_trend = _trend(cvd_series)
    oi_trend = _trend(oi_series)

    if signal_type == "BUY":
        # CVD yükseliyor
        if cvd_trend == "up":
            if oi_trend == "up":
                return "STRONG_LONG"
            else:  # down veya neutral -> weak
                return "WEAK_LONG"
        # CVD yatay
        elif cvd_trend == "neutral":
            # OI yükseliyorsa bekle (range), değilse yine zayıf sinyal gönderilebilir
            if oi_trend == "up":
                return "RANGE"
            else:
                return "WEAK_LONG"
        # CVD düşüyor -> tuzak (range)
        else:  # cvd_trend == "down"
            return "RANGE"
    else:  # SELL
        # CVD düşüyor
        if cvd_trend == "down":
            if oi_trend == "up":
                return "STRONG_SHORT"
            else:  # down veya neutral -> weak
                return "WEAK_SHORT"
        # CVD yatay
        elif cvd_trend == "neutral":
            if oi_trend == "up":
                return "RANGE"
            else:
                return "WEAK_SHORT"
        # CVD yükseliyor -> tuzak
        else:  # cvd_trend == "up"
            return "RANGE"
