import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from signals import (
    calc_ema, calc_supertrend, calc_rsi, calc_atr,
    SUPERTREND_PERIOD, SUPERTREND_MULT, SL_ATR_MULT, TP_ATR_MULT
)

exchange = ccxt.binance()

def run_backtest(symbol: str, timeframe: str = "1h", days: int = 30) -> dict:
    """
    Geçmiş verilerde stratejiyi test eder.
    
    Parametreler:
        symbol: "BTC/USDT", "ETH/USDT" vb.
        timeframe: "1h", "4h", "1d"
        days: Kaç günlük veri çekilecek (max 90)
    
    Döndürdüğü:
        {
            "total_signals": toplam sinyal sayısı,
            "tp_count": TP isabet sayısı,
            "sl_count": SL isabet sayısı,
            "win_rate": kazanma oranı %,
            "total_pnl": toplam kâr/zarar %,
            "avg_win": ortalama kâr %,
            "avg_loss": ortalama zarar %,
            "max_drawdown": en büyük düşüş %,
            "trades": tüm işlemler listesi
        }
    """
    # Geçmiş veriyi çek
    since = exchange.parse8601((datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
    
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    
    if len(df) < 50:
        return {"error": "Yetersiz veri"}
    
    # İndikatörleri hesapla
    ema12 = calc_ema(df["close"], 12)
    ema26 = calc_ema(df["close"], 26)
    supertrend, direction, atr = calc_supertrend(df)
    
    trades = []
    position = None  # None, "BUY", "SELL"
    entry_price = 0
    stop_loss = 0
    take_profit = 0
    entry_time = None
    
    # Her barı tara (ilk 50 bar'dan sonra başla)
    for i in range(50, len(df) - 1):
        cur_price = float(df["close"].iloc[i])
        cur_ema12 = ema12.iloc[i]
        cur_ema26 = ema26.iloc[i]
        prev_ema12 = ema12.iloc[i - 1]
        prev_ema26 = ema26.iloc[i - 1]
        cur_dir = direction.iloc[i]
        cur_atr = float(atr.iloc[i])
        
        crossed_up = prev_ema12 <= prev_ema26 and cur_ema12 > cur_ema26
        crossed_down = prev_ema12 >= prev_ema26 and cur_ema12 < cur_ema26
        
        # Açık pozisyon varsa SL/TP kontrolü
        if position == "BUY":
            if float(df["low"].iloc[i]) <= stop_loss:
                pnl = (stop_loss - entry_price) / entry_price * 100
                trades.append({
                    "type": "BUY",
                    "entry": entry_price,
                    "exit": stop_loss,
                    "result": "SL",
                    "pnl": round(pnl, 2),
                    "entry_time": entry_time,
                    "exit_time": df.index[i]
                })
                position = None
            elif float(df["high"].iloc[i]) >= take_profit:
                pnl = (take_profit - entry_price) / entry_price * 100
                trades.append({
                    "type": "BUY",
                    "entry": entry_price,
                    "exit": take_profit,
                    "result": "TP",
                    "pnl": round(pnl, 2),
                    "entry_time": entry_time,
                    "exit_time": df.index[i]
                })
                position = None
                
        elif position == "SELL":
            if float(df["high"].iloc[i]) >= stop_loss:
                pnl = (entry_price - stop_loss) / entry_price * 100
                trades.append({
                    "type": "SELL",
                    "entry": entry_price,
                    "exit": stop_loss,
                    "result": "SL",
                    "pnl": round(pnl, 2),
                    "entry_time": entry_time,
                    "exit_time": df.index[i]
                })
                position = None
            elif float(df["low"].iloc[i]) <= take_profit:
                pnl = (entry_price - take_profit) / entry_price * 100
                trades.append({
                    "type": "SELL",
                    "entry": entry_price,
                    "exit": take_profit,
                    "result": "TP",
                    "pnl": round(pnl, 2),
                    "entry_time": entry_time,
                    "exit_time": df.index[i]
                })
                position = None
        
        # Yeni sinyal kontrolü (sadece pozisyon yoksa)
        if position is None:
            if crossed_up and cur_dir == 1:
                # AL sinyali
                entry_price = cur_price
                stop_loss = cur_price - SL_ATR_MULT * cur_atr
                take_profit = cur_price + TP_ATR_MULT * cur_atr
                position = "BUY"
                entry_time = df.index[i]
                
            elif crossed_down and cur_dir == -1:
                # SAT sinyali
                entry_price = cur_price
                stop_loss = cur_price + SL_ATR_MULT * cur_atr
                take_profit = cur_price - TP_ATR_MULT * cur_atr
                position = "SELL"
                entry_time = df.index[i]
    
    # İstatistikleri hesapla
    if not trades:
        return {"error": "Bu periyotta hiç sinyal oluşmadı"}
    
    tp_trades = [t for t in trades if t["result"] == "TP"]
    sl_trades = [t for t in trades if t["result"] == "SL"]
    total = len(trades)
    win_rate = len(tp_trades) / total * 100
    
    all_pnl = [t["pnl"] for t in trades]
    total_pnl = round(sum(all_pnl), 2)
    avg_win = round(sum(t["pnl"] for t in tp_trades) / len(tp_trades), 2) if tp_trades else 0
    avg_loss = round(sum(t["pnl"] for t in sl_trades) / len(sl_trades), 2) if sl_trades else 0
    
    # Max Drawdown hesapla
    cumulative = np.cumsum(all_pnl)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = cumulative - running_max
    max_drawdown = round(abs(min(drawdown)), 2)
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "period": f"{days} gün",
        "total_signals": total,
        "tp_count": len(tp_trades),
        "sl_count": len(sl_trades),
        "win_rate": round(win_rate, 1),
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "max_drawdown": max_drawdown,
        "trades": trades[-10:]  # Son 10 işlem
    }
