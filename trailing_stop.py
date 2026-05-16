def calc_trailing_sl(
    signal_type: str,
    entry_price: float,
    current_price: float,
    atr: float,
    original_sl: float,
    original_tp: float,
    sl_mult: float = 1.5,
    trail_activation: float = 0.5,
    trail_distance: float = 1.0,
    trend_strength: float = 50.0,  # <-- YENİ: Trend gücü parametresi
) -> float:
    """
    Dinamik Trailing Stop hesaplar.
    
    - TP'nin %50'sine ulaşana kadar: Sabit SL
    - TP'nin %50'sine ulaştıktan sonra: Fiyatı dinamik ATR mesafeden takip eder
    - Yeni SL, ESKİ SL'den DAHA İYİ olmalı (karı korumalı)
    - Trend gücüne göre takip mesafesi ayarlanır (Trende Saygı Duruşu)
    
    Döndürdüğü: Yeni Stop Loss fiyatı
    """
    # ═══════ TRENDE SAYGI DURUŞU (DİNAMİK TAKİP MESAFESİ) ═══════
    if trend_strength > 80:
        dynamic_distance = 1.8  # Süper trend, bırak koşsun
    elif trend_strength > 65:
        dynamic_distance = 1.4  # Güçlü trend, nefes alsın
    elif trend_strength > 50:
        dynamic_distance = 1.0  # Standart takip
    else:
        dynamic_distance = 0.7  # Zayıf trend, dizginleri sık
    # ═══════════════════════════════════════════════════════════

    tp_distance = abs(original_tp - entry_price)
    
    if signal_type == "BUY":
        profit_pct = (current_price - entry_price) / entry_price * 100
        tp_pct = (original_tp - entry_price) / entry_price * 100
        
        # TP'nin %50'sine ulaştıysa trailing başlat
        if profit_pct >= tp_pct * trail_activation:
            trailing_sl = current_price - (dynamic_distance * atr)  # <-- dinamik mesafe
            # Yeni SL, eski SL'den yukarıdaysa güncelle (karı koru)
            return max(original_sl, trailing_sl)
        else:
            return original_sl
    
    else:  # SELL
        profit_pct = (entry_price - current_price) / entry_price * 100
        tp_pct = (entry_price - original_tp) / entry_price * 100
        
        if profit_pct >= tp_pct * trail_activation:
            trailing_sl = current_price + (dynamic_distance * atr)  # <-- dinamik mesafe
            # Yeni SL, eski SL'den aşağıdaysa güncelle (karı koru)
            return min(original_sl, trailing_sl)
        else:
            return original_sl


def calc_dynamic_tp(
    signal_type: str,
    entry_price: float,
    current_price: float,
    atr: float,
    original_tp: float,
    trend_strength: float,  # R² (0-100)
    tp_mult: float = 3.0,
) -> float:
    """
    Dinamik Take Profit hesaplar.
    
    - Trend güçlüyse (R² > 70): TP uzaklaşır (trendi yakala)
    - Trend zayıfsa (R² < 40): TP yakınlaşır (karı al)
    - Fiyat TP'ye yaklaştıkça TP güncellenir
    
    Döndürdüğü: Yeni Take Profit fiyatı
    """
    
    # Trend gücüne göre TP çarpanı ayarla
    if trend_strength > 80:
        dynamic_mult = tp_mult * 1.3   # Süper trend → TP'yi uzat
    elif trend_strength > 60:
        dynamic_mult = tp_mult * 1.1   # Güçlü trend → biraz uzat
    elif trend_strength > 40:
        dynamic_mult = tp_mult         # Normal
    elif trend_strength > 25:
        dynamic_mult = tp_mult * 0.8   # Zayıf trend → TP'yi yakınlaştır
    else:
        dynamic_mult = tp_mult * 0.6   # Trend bitiyor → hemen kar al
    
    if signal_type == "BUY":
        # TP'yi güncelle: orijinal TP ile dinamik TP arasında maksimumu al
        new_tp = entry_price + (dynamic_mult * atr)
        # TP hiçbir zaman orijinalden aşağı düşmesin
        return max(original_tp, new_tp)
    
    else:  # SELL
        new_tp = entry_price - (dynamic_mult * atr)
        # TP hiçbir zaman orijinalden yukarı çıkmasın
        return min(original_tp, new_tp)


def calc_trailing_duo(
    signal_type: str,
    entry_price: float,
    current_price: float,
    atr: float,
    original_sl: float,
    original_tp: float,
    trend_strength: float,
    sl_mult: float = 1.5,
    tp_mult: float = 3.0,
    trail_activation: float = 0.5,
    trail_distance: float = 1.0,
) -> tuple:
    """
    Hem SL hem TP'yi dinamik günceller.
    
    Döndürdüğü: (yeni_sl, yeni_tp)
    """
    
    # Dinamik SL (Trende Saygı Duruşu aktif)
    new_sl = calc_trailing_sl(
        signal_type=signal_type,
        entry_price=entry_price,
        current_price=current_price,
        atr=atr,
        original_sl=original_sl,
        original_tp=original_tp,
        sl_mult=sl_mult,
        trail_activation=trail_activation,
        trail_distance=trail_distance,
        trend_strength=trend_strength,  # <-- YENİ: trend gücü iletiliyor
    )
    
    # Dinamik TP
    new_tp = calc_dynamic_tp(
        signal_type=signal_type,
        entry_price=entry_price,
        current_price=current_price,
        atr=atr,
        original_tp=original_tp,
        trend_strength=trend_strength,
        tp_mult=tp_mult,
    )
    
    return new_sl, new_tp
