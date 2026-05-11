import ccxt
import numpy as np
from signals import (
    get_ohlcv, compute_trend_series, compute_strength_series,
    TREND_METHOD, TREND_PERIOD, TREND_STRENGTH_MIN
)

exchange = ccxt.binance()

# Stablecoin listesi - bunları asla seçme
STABLE_COINS = ["USDC", "BUSD", "USDP", "TUSD", "FDUSD", "DAI", "USDD", "USTC", "PAX", "USDE", "PYUSD", "USD1"]

# Düşük kaliteli coin'ler (hacimsiz, scam riskli)
LOW_QUALITY = []  # Hacim filtresi (40M$) bu işi otomatik yapıyor


def scan_best_coins(timeframe="15m", limit=100, top_n=20):
    """En iyi sinyal potansiyelli coin'leri bulur. (v2 - 20 coin, stablecoin filtresi)"""
    
    tickers = exchange.fetch_tickers()
    usdt_pairs = [s for s in tickers if s.endswith("/USDT")]
    
    # Stablecoin'leri filtrele
    usdt_pairs = [s for s in usdt_pairs if s.split("/")[0] not in STABLE_COINS]
    usdt_pairs = [s for s in usdt_pairs if tickers[s].get("quoteVolume", 0) > 40_000_000]
    
    results = []
    
    for symbol in usdt_pairs[:limit]:
        try:
            df = get_ohlcv(symbol, timeframe, limit=150)
            trend = compute_trend_series(df, TREND_PERIOD, TREND_METHOD)
            strength = compute_strength_series(df["close"], TREND_PERIOD)
            
            avg_r2 = float(strength.tail(20).mean())
            trend_changes = (trend.tail(20).diff().abs() > 0).sum()
            atr_val = float(df["close"].pct_change().tail(20).std() * 100)
            volume = tickers[symbol].get("quoteVolume", 0)
            
            # Hacim filtresi - çok düşük hacimlileri cezalandır
            if volume < 1_000_000:  # $1M altı günlük hacim
                volume_score = 0
            elif volume < 5_000_000:
                volume_score = min(np.log10(volume / 1000000) * 3, 5)
            else:
                volume_score = min(np.log10(volume / 1000000) * 2, 10)
            
            # PUAN HESAPLAMA
            score = min(avg_r2 * 0.5, 50)  # R² (max 50, daha önemli)
            score += max(0, 30 - trend_changes * 5)  # Kararlılık (max 30)
            score += min(atr_val * 2, 15)  # Volatilite (max 15, düşürüldü)
            score += volume_score  # Hacim (max 10)
            score += 5 if trend.tail(1).iloc[0] != 0 else 0  # Net trend bonusu
            
            results.append({
                "symbol": symbol,
                "avg_r2": round(avg_r2, 1),
                "trend_changes": trend_changes,
                "volatility": round(atr_val, 2),
                "volume": volume,
                "score": round(score, 1),
            })
        except:
            pass
    
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]
