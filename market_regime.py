import pandas as pd
import numpy as np
from signals import calc_ema, calc_atr

def detect_market_regime(symbol: str, timeframe: str = "1h") -> dict:
    """
    Piyasa rejimini tespit eder.
    
    Döndürdüğü:
    {
        "regime": "TREND",  # TREND / RANGE / VOLATILE
        "confidence": 0.85,  # Güven skoru
        "adx": 32.5,        # ADX değeri (trend gücü)
        "description": "Güçlü trend, sinyaller güvenilir"
    }
    """
    from signals import get_ohlcv
    
    try:
        # Son 50 bar veriyi çek
        df = get_ohlcv(symbol, timeframe=timeframe, limit=50)
        
        if len(df) < 30:
            return {"regime": "UNKNOWN", "confidence": 0, "adx": 0, 
                    "description": "Yetersiz veri"}
        
        high = df["high"]
        low = df["low"]
        close = df["close"]
        
        # 1. ADX Hesapla (Trend Gücü)
        adx = calc_adx(high, low, close, period=14)
        current_adx = float(adx.iloc[-1])
        
        # 2. Volatilite Hesapla (ATR / Fiyat)
        atr = calc_atr(df, period=14)
        current_atr = float(atr.iloc[-1])
        current_price = float(close.iloc[-1])
        volatility = (current_atr / current_price) * 100
        
        # 3. Son 20 barın fiyat aralığı (Range tespiti)
        recent_high = float(high.tail(20).max())
        recent_low = float(low.tail(20).min())
        price_range_pct = ((recent_high - recent_low) / current_price) * 100
        
        # 4. EMA eğimi (trend yönü)
        ema20 = calc_ema(close, 20)
        ema_slope = (float(ema20.iloc[-1]) - float(ema20.iloc[-5])) / float(ema20.iloc[-5]) * 100
        
        # 5. Volatilite rejimi (son 20 barın volatilitesi)
        returns = close.pct_change().dropna()
        recent_volatility = float(returns.tail(20).std()) * 100
        
            # REJİM KARARI (DÜZELTİLMİŞ)
        if current_adx > 40:
            # Çok güçlü trend
            regime = "TREND"
            confidence = 0.9
            if ema_slope > 0:
                description = f"💪 Güçlü yükseliş trendi (ADX: {current_adx:.1f})"
            else:
                description = f"💪 Güçlü düşüş trendi (ADX: {current_adx:.1f})"
            
        elif current_adx > 25:
            # Orta trend
            regime = "TREND"
            confidence = 0.7
            if ema_slope > 0:
                description = f"✅ Yükseliş trendi (ADX: {current_adx:.1f})"
            else:
                description = f"✅ Düşüş trendi (ADX: {current_adx:.1f})"
            
        elif current_adx > 20:
            # Zayıf trend
            regime = "TREND"
            confidence = 0.5
            description = f"⚠️ Zayıf trend (ADX: {current_adx:.1f}) — Dikkatli ol"
        
        elif price_range_pct < 3.0:
            # Yatay piyasa
            regime = "RANGE"
            confidence = 0.7
            description = f"🚫 Yatay piyasa (ADX: {current_adx:.1f}) — Bekle"
        
        else:
            # Belirsiz
            regime = "TREND"
            confidence = 0.4
            description = f"⚪ Belirsiz (ADX: {current_adx:.1f})"
        
        return {
            "regime": regime,
            "confidence": round(confidence, 2),
            "adx": round(current_adx, 1),
            "volatility": round(volatility, 2),
            "ema_slope": round(ema_slope, 2),
            "price_range_pct": round(price_range_pct, 2),
            "description": description
        }
        
    except Exception as e:
        return {"regime": "UNKNOWN", "confidence": 0, "adx": 0, 
                "description": f"Hata: {str(e)[:30]}"}


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ADX hesaplar - düzeltilmiş versiyon"""
    
    # True Range (manuel hesapla, calc_atr ile çakışmasın)
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_value = true_range.ewm(span=period, adjust=False).mean()
    
    # +DM ve -DM
    up_move = high.diff()
    down_move = -low.diff()
    
    plus_dm = pd.Series(0.0, index=high.index)
    minus_dm = pd.Series(0.0, index=high.index)
    
    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move
    
    # Smooth DM
    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr_value)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr_value)
    
    # DX ve ADX
    di_sum = plus_di + minus_di
    di_sum = di_sum.replace(0, np.nan)  # Sıfıra bölünmeyi engelle
    dx = 100 * abs(plus_di - minus_di) / di_sum
    adx = dx.ewm(span=period, adjust=False).mean()
    
    return adx


def should_trade(regime: dict) -> tuple[bool, str]:
    """
    Piyasa rejimine göre trade yapılıp yapılmamasına karar verir.
    
    Döndürdüğü:
    (True/False, açıklama)
    """
    if regime["regime"] == "TREND" and regime["confidence"] >= 0.6:
        return True, f"✅ Trend piyasası — Tam gaz!"
    elif regime["regime"] == "TREND" and regime["confidence"] < 0.6:
        return True, f"⚠️ Zayıf trend — Dikkatli ol"
    elif regime["regime"] == "RANGE":
        return False, f"🚫 Yatay piyasa — Bekle"
    elif regime["regime"] == "VOLATILE":
        return True, f"⚠️ Volatil piyasa — Küçük pozisyon"
    else:
        return True, f"⚪ Rejim tespit edilemedi — Normal"
