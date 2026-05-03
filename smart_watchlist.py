import ccxt
import numpy as np
from signals import (
    get_ohlcv, compute_trend_series, compute_strength_series,
    TREND_METHOD, TREND_PERIOD, TREND_STRENGTH_MIN
)

exchange = ccxt.binance()

def scan_best_coins(timeframe="15m", limit=50, top_n=10):
    """En iyi sinyal potansiyelli coin'leri bulur."""
    
    tickers = exchange.fetch_tickers()
    usdt_pairs = [s for s in tickers if s.endswith("/USDT")]
    
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
            
            # PUAN
            score = min(avg_r2 * 0.4, 40)  # R²
            score += max(0, 30 - trend_changes * 5)  # Kararlılık
            score += min(atr_val * 3, 20)  # Volatilite
            score += min(np.log10(volume + 1) * 2, 10)  # Hacim
            
            results.append({
                "symbol": symbol,
                "avg_r2": round(avg_r2, 1),
                "score": round(score, 1),
            })
        except:
            pass
    
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]
