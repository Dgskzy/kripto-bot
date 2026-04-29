import ccxt
import os

exchange = ccxt.binance()

def get_dynamic_funding_threshold(symbol: str):
    """
    Binance'den sembolün resmi min/max funding rate değerlerini çeker.
    """
    try:
        binance_symbol = symbol.replace("/", "")
        market = exchange.market(binance_symbol)
        
        max_rate = float(market['info'].get('maxFundingRate', 0))
        min_rate = float(market['info'].get('minFundingRate', 0))
        
        return {
            "max_rate": max_rate,
            "min_rate": min_rate
        }
    except Exception as e:
        print(f"Sınır değerleri alınamadı: {e}")
        return None

def analyze_funding_risk(signal_type, symbol):
    """
    Güncel funding rate'in, sembolün kendi eşiklerine göre risk analizini yapar.
    """
    try:
        binance_symbol = symbol.replace("/", "")
        ticker_data = exchange.fetch_funding_rate(binance_symbol)
        current_rate = float(ticker_data[0] if isinstance(ticker_data, tuple) else ticker_data['fundingRate'])
        
        thresholds = get_dynamic_funding_threshold(symbol)
        if not thresholds:
            return "normal", "Eşik bilgisi alınamadı"

        if signal_type == "BUY":
            # Örnek: Güncel oran, resmi alt eşiğin %60'ından daha negatifse aşırı short vardır.
            if thresholds['min_rate'] < 0 and current_rate <= thresholds['min_rate'] * 0.6:
                return "block", f"Aşırı Short (Funding: %{current_rate*100:.2f}, Limit: %{thresholds['min_rate']*100:.2f})"
            elif thresholds['min_rate'] < 0 and current_rate <= thresholds['min_rate'] * 0.3:
                return "strong", f"Short Ağırlıklı (Funding: %{current_rate*100:.2f})"
            elif thresholds['max_rate'] > 0 and current_rate >= thresholds['max_rate'] * 0.6:
                return "block", f"Aşırı Long Riski (Funding: %{current_rate*100:.2f}, Limit: %{thresholds['max_rate']*100:.2f})"
            else:
                return "normal", "Funding dengeli"

        elif signal_type == "SELL":
            if thresholds['max_rate'] > 0 and current_rate >= thresholds['max_rate'] * 0.6:
                return "block", f"Aşırı Long (Funding: %{current_rate*100:.2f}, Limit: %{thresholds['max_rate']*100:.2f})"
            elif thresholds['max_rate'] > 0 and current_rate >= thresholds['max_rate'] * 0.3:
                return "strong", f"Long Ağırlıklı (Funding: %{current_rate*100:.2f})"
            elif thresholds['min_rate'] < 0 and current_rate <= thresholds['min_rate'] * 0.6:
                return "block", f"Aşırı Short Riski (Funding: %{current_rate*100:.2f}, Limit: %{thresholds['min_rate']*100:.2f})"
            else:
                return "normal", "Funding dengeli"

    except Exception as e:
        print(f"Funding analiz hatası: {e}")
        return "normal", "Veri alınamadı"
