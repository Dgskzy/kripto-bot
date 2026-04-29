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
) -> float:
    """
    Dinamik Trailing Stop hesaplar.
    
    - TP'nin %50'sine ulaşana kadar: Sabit SL
    - TP'nin %50'sine ulaştıktan sonra: Fiyatı 1 ATR mesafeden takip eder
    - Yeni SL, ESKİ SL'den DAHA İYİ olmalı (karı korumalı)
    
    Döndürdüğü: Yeni Stop Loss fiyatı
    """
    tp_distance = abs(original_tp - entry_price)
    
    if signal_type == "BUY":
        profit_pct = (current_price - entry_price) / entry_price * 100
        tp_pct = (original_tp - entry_price) / entry_price * 100
        
        # TP'nin %50'sine ulaştıysa trailing başlat
        if profit_pct >= tp_pct * trail_activation:
            trailing_sl = current_price - (trail_distance * atr)
            # Yeni SL, eski SL'den yukarıdaysa güncelle (karı koru)
            return max(original_sl, trailing_sl)
        else:
            return original_sl
    
    else:  # SELL
        profit_pct = (entry_price - current_price) / entry_price * 100
        tp_pct = (entry_price - original_tp) / entry_price * 100
        
        if profit_pct >= tp_pct * trail_activation:
            trailing_sl = current_price + (trail_distance * atr)
            # Yeni SL, eski SL'den aşağıdaysa güncelle (karı koru)
            return min(original_sl, trailing_sl)
        else:
            return original_sl
