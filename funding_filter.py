import ccxt

exchange = ccxt.binance()

def get_funding_info(symbol: str) -> dict:
    """
    Binance'den güncel funding rate bilgisini çeker.
    """
    try:
        binance_symbol = symbol.replace("/", "")
        
        # Önce fetch_funding_rate dene
        try:
            funding_data = exchange.fetch_funding_rate(binance_symbol)
            if isinstance(funding_data, list):
                funding_data = funding_data[0]
            rate = float(funding_data["fundingRate"]) * 100
        except:
            # fetch_funding_rate çalışmazsa, fapiPublic ile dene
            try:
                funding_data = exchange.fapiPublic_get_premiumindex({"symbol": binance_symbol})
                rate = float(funding_data["lastFundingRate"]) * 100
            except:
                # Hiçbiri çalışmazsa varsayılan
                return {
                    "rate": 0,
                    "icon": "⚪",
                    "text": "Veri yok",
                    "max_limit": 0,
                    "min_limit": 0,
                }
        
        # Coin'in kendi limitlerini al
        try:
            market = exchange.market(binance_symbol)
            max_rate = float(market['info'].get('maxFundingRate', 0.01)) * 100
            min_rate = float(market['info'].get('minFundingRate', -0.01)) * 100
        except:
            max_rate = 0.75  # varsayılan
            min_rate = -0.75
        
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
            "text": f"Hata: {str(e)[:20]}",
            "max_limit": 0,
            "min_limit": 0,
        }
