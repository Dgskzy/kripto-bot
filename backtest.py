import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from signals import (
    calc_ema, calc_supertrend, calc_rsi, calc_atr,
    SUPERTREND_PERIOD, SUPERTREND_MULT, get_coin_profile
)
from trailing_stop import calc_trailing_sl

exchange = ccxt.binance()

def run_backtest(symbol: str, timeframe: str = "1h", days: int = 30) -> dict:
    """Basitleştirilmiş backtest - sadece EMA + SuperTrend"""
    
    profile = get_coin_profile(symbol)
    sl_mult = profile["sl_mult"]
    tp_mult = profile["tp_mult"]
    
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=min(days * 24, 1500))
    
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    
    if len(df) < 50:
        return {"error": f"Yetersiz veri: {len(df)} bar"}
    
    ema12 = calc_ema(df["close"], 12)
    ema26 = calc_ema(df["close"], 26)
    supertrend, direction, atr = calc_supertrend(df)
    
    trades = []
    position = None
    entry_price = 0
    stop_loss = 0
    take_profit = 0
    original_sl = 0
    entry_time = None
    
    for i in range(50, len(df) - 1):
        cur_price = float(df["close"].iloc[i])
        cur_high = float(df["high"].iloc[i])
        cur_low = float(df["low"].iloc[i])
        cur_dir = direction.iloc[i]
        cur_atr = float(atr.iloc[i])
        
        crossed_up = ema12.iloc[i-1] <= ema26.iloc[i-1] and ema12.iloc[i] > ema26.iloc[i]
        crossed_down = ema12.iloc[i-1] >= ema26.iloc[i-1] and ema12.iloc[i] < ema26.iloc[i]
        
        # Pozisyon kontrolü
        if position == "BUY":
            stop_loss = calc_trailing_sl("BUY", entry_price, cur_price, cur_atr, original_sl, take_profit, sl_mult)
            if cur_low <= stop_loss:
                pnl = (stop_loss - entry_price) / entry_price * 100
                trades.append({"type": "BUY", "entry": entry_price, "exit": stop_loss, "result": "SL", "pnl": round(pnl, 2), "entry_time": entry_time, "exit_time": df.index[i]})
                position = None
            elif cur_high >= take_profit:
                pnl = (take_profit - entry_price) / entry_price * 100
                trades.append({"type": "BUY", "entry": entry_price, "exit": take_profit, "result": "TP", "pnl": round(pnl, 2), "entry_time": entry_time, "exit_time": df.index[i]})
                position = None
        elif position == "SELL":
            stop_loss = calc_trailing_sl("SELL", entry_price, cur_price, cur_atr, original_sl, take_profit, sl_mult)
            if cur_high >= stop_loss:
                pnl = (entry_price - stop_loss) / entry_price * 100
                trades.append({"type": "SELL", "entry": entry_price, "exit": stop_loss, "result": "SL", "pnl": round(pnl, 2), "entry_time": entry_time, "exit_time": df.index[i]})
                position = None
            elif cur_low <= take_profit:
                pnl = (entry_price - take_profit) / entry_price * 100
                trades.append({"type": "SELL", "entry": entry_price, "exit": take_profit, "result": "TP", "pnl": round(pnl, 2), "entry_time": entry_time, "exit_time": df.index[i]})
                position = None
        
        # Yeni sinyal (SADECE TREND YÖNÜNDE)
        if position is None:
            # SuperTrend POZİTİF + EMA yukarı kesişim = AL
            if crossed_up and cur_dir == 1:
                entry_price = cur_price
                original_sl = cur_price - sl_mult * cur_atr
                stop_loss = original_sl
                take_profit = cur_price + tp_mult * cur_atr
                position = "BUY"
                entry_time = df.index[i]
                
            # SuperTrend NEGATİF + EMA aşağı kesişim = SAT
            elif crossed_down and cur_dir == -1:
                entry_price = cur_price
                original_sl = cur_price + sl_mult * cur_atr
                stop_loss = original_sl
                take_profit = cur_price - tp_mult * cur_atr
                position = "SELL"
                entry_time = df.index[i]
            
            # Diğer tüm durumlar (uyumsuzluk) → SİNYAL YOK
    
    if not trades:
        return {"error": f"Sinyal yok ({len(df)} bar, {days} gün)"}
    
    tp_trades = [t for t in trades if t["result"] == "TP"]
    sl_trades = [t for t in trades if t["result"] == "SL"]
    total = len(trades)
    win_rate = len(tp_trades) / total * 100 if total > 0 else 0
    all_pnl = [t["pnl"] for t in trades]
    total_pnl = round(sum(all_pnl), 2)
    avg_win = round(sum(t["pnl"] for t in tp_trades) / len(tp_trades), 2) if tp_trades else 0
    avg_loss = round(sum(t["pnl"] for t in sl_trades) / len(sl_trades), 2) if sl_trades else 0
    cumulative = np.cumsum(all_pnl)
    max_drawdown = round(abs(min(cumulative - np.maximum.accumulate(cumulative))), 2)
    
    return {
        "symbol": symbol, "timeframe": timeframe, "period": f"{days} gün",
        "sl_mult": sl_mult, "tp_mult": tp_mult,
        "total_signals": total, "tp_count": len(tp_trades), "sl_count": len(sl_trades),
        "win_rate": round(win_rate, 1), "total_pnl": total_pnl,
        "avg_win": avg_win, "avg_loss": avg_loss, "max_drawdown": max_drawdown,
        "trades": trades[-10:]
    }
