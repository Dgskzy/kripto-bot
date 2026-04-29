import ccxt

exchange = ccxt.binance()

def get_funding_info(symbol: str) -> dict:
    """
    Binance'den güncel funding rate bilgisini çeker.
    Sinyal engellemez, sadece bilgi verir.
    """
    try:
        binance_symbol = symbol.replace("/", "")
        ticker_data = exchange.fetch_funding_rate(binance_symbol)
        
        # fetch_funding_rate bazen liste döner
        if isinstance(ticker_data, list):
            ticker_data = ticker_data[0]
        
        rate = float(ticker_data["fundingRate"]) * 100  # Yüzde
        
        # Coin'in kendi limitlerini al
        market = exchange.market(binance_symbol)
        max_rate = float(market['info'].get('maxFundingRate', 0.01)) * 100
        min_rate = float(market['info'].get('minFundingRate', -0.01)) * 100
        
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
            "text": f"Veri yok",
            "max_limit": 0,
            "min_limit": 0,
        }

    except Exception as e:
        print(f"Funding analiz hatası: {e}")
        return "normal", "Veri alınamadı"
