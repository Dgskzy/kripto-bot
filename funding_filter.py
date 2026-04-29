import requests

def get_funding_info(symbol: str) -> dict:
    """
    Binance'den güncel funding rate bilgisini çeker.
    Binance public API'si ile çalışır (ccxt'den bağımsız).
    """
    try:
        # Binance sembol formatı: BTC/USDT -> BTCUSDT
        binance_symbol = symbol.replace("/", "")
        
        # Binance public funding rate API'si
        url = "https://fapi.binance.com/fapi/v1/premiumIndex"
        resp = requests.get(url, params={"symbol": binance_symbol}, timeout=5)
        
        if resp.status_code != 200:
            return {"rate": 0, "icon": "⚪", "text": "Veri yok", "max_limit": 0, "min_limit": 0}
        
        data = resp.json()
        rate = float(data["lastFundingRate"]) * 100  # Yüzdeye çevir
        
        # BTC için sabit limitler (genelde geçerli)
        if binance_symbol in ["BTCUSDT", "ETHUSDT"]:
            max_rate = 0.375
            min_rate = -0.375
        elif binance_symbol in ["SOLUSDT", "AVAXUSDT", "XRPUSDT", "LINKUSDT"]:
            max_rate = 0.75
            min_rate = -0.75
        else:
            max_rate = 3.0   # DOGE, EGLD gibi volatil coin'ler
            min_rate = -3.0
        
        # Yoruma göre ikon
        if rate >= max_rate * 0.6:
            icon = "🔴"
            text = "Aşırı LONG"
        elif rate >= max_rate * 0.3:
            icon = "🟠"
            text = "Long ağırlıklı"
        elif rate <= min_rate * 0.6:
            icon = "🟢"
            text = "Aşırı SHORT"
        elif rate <= min_rate * 0.3:
            icon = "🟢"
            text = "Short ağırlıklı"
        else:
            icon = "🟡"
            text = "Dengeli"
        
        return {
            "rate": round(rate, 4),
            "icon": icon,
            "text": text,
            "max_limit": round(max_rate, 2),
            "min_limit": round(min_rate, 2),
        }
    except Exception as e:
        return {
            "rate": 0,
            "icon": "⚪",
            "text": f"Hata: {str(e)[:15]}",
            "max_limit": 0,
            "min_limit": 0,
        }
