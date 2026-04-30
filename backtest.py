import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from signals import (
    calc_ema, calc_supertrend, calc_rsi, calc_atr,
    SUPERTREND_PERIOD, SUPERTREND_MULT, get_coin_profile
)
from trailing_stop import calc_trailing_sl
from signal_filter import get_cvd_oi_data, classify_signal
from market_regime import detect_market_regime, should_trade

exchange = ccxt.binance()

def run_backtest(symbol: str, timeframe: str = "1h", days: int = 30) -> dict:
    """
    Geçmiş verilerde stratejiyi test eder.
    
    Filtreler:
    - EMA + SuperTrend temel sinyal
    - CVD/OI filtresi (RANGE sinyalleri eler)
    - Piyasa Rejimi filtresi (yatay piyasada sinyali engeller)
    - Coin bazlı dinamik SL/TP çarpanları
    - Trailing stop (TP'nin %50'sinde devreye girer)
    """
    # Coin profilini al
    profile = get_coin_profile(symbol)
    sl_mult = profile["sl_mult"]
    tp_mult = profile["tp_mult"]
    
    # Geçmiş veriyi çek
    since = exchange.parse8601((datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=2000)
    
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
    filtered_count = 0  # Filtre tarafından elenen sinyal sayısı
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
        cur_ema12 = ema12.iloc[i]
        cur_ema26 = ema26.iloc[i]
        prev_ema12 = ema12.iloc[i - 1]
        prev_ema26 = ema26.iloc[i - 1]
        cur_dir = direction.iloc[i]
        cur_atr = float(atr.iloc[i])
        
        crossed_up = prev_ema12 <= prev_ema26 and cur_ema12 > cur_ema26
        crossed_down = prev_ema12 >= prev_ema26 and cur_ema12 < cur_ema26
        
        # Açık pozisyon varsa - TRAILING STOP ile SL/TP kontrolü
        if position == "BUY":
            stop_loss = calc_trailing_sl(
                signal_type="BUY",
                entry_price=entry_price,
                current_price=cur_price,
                atr=cur_atr,
                original_sl=original_sl,
                original_tp=take_profit,
                sl_mult=sl_mult,
            )
            
            if cur_low <= stop_loss:
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
            elif cur_high >= take_profit:
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
            stop_loss = calc_trailing_sl(
                signal_type="SELL",
                entry_price=entry_price,
                current_price=cur_price,
                atr=cur_atr,
                original_sl=original_sl,
                original_tp=take_profit,
                sl_mult=sl_mult,
            )
            
            if cur_high >= stop_loss:
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
            elif cur_low <= take_profit:
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
                # --- CVD/OI FİLTRESİ ---
                try:
                    cvd_oi_df = get_cvd_oi_data(symbol, timeframe, limit=120)
                    if cvd_oi_df is not None and not cvd_oi_df.empty:
                        quality = classify_signal("BUY", cvd_oi_df["cvd"], cvd_oi_df["oi"])
                        if quality == "RANGE":
                            filtered_count += 1
                            continue
                except:
                    pass
                
                # --- PİYASA REJİMİ FİLTRESİ ---
                try:
                    regime = detect_market_regime(symbol, timeframe)
                    trade_ok, _ = should_trade(regime)
                    if not trade_ok:
                        filtered_count += 1
                        continue
                except:
                    pass
                # -------------------------------
                
                # AL sinyali
                entry_price = cur_price
                original_sl = cur_price - sl_mult * cur_atr
                stop_loss = original_sl
                take_profit = cur_price + tp_mult * cur_atr
                position = "BUY"
                entry_time = df.index[i]
                
            elif crossed_down and cur_dir == -1:
                # --- CVD/OI FİLTRESİ (sadece canlı veri varsa) ---
                try:
                    cvd_oi_df = get_cvd_oi_data(symbol, timeframe, limit=120)
                    if cvd_oi_df is not None and not cvd_oi_df.empty:
                        quality = classify_signal("BUY", cvd_oi_df["cvd"], cvd_oi_df["oi"])
                        if quality == "RANGE":
                            filtered_count += 1
                            continue
                except:
                    # Veri yoksa filtreleme yapma, sinyale izin ver
                    pass
                
                # --- PİYASA REJİMİ FİLTRESİ ---
                try:
                    regime = detect_market_regime(symbol, timeframe)
                    trade_ok, _ = should_trade(regime)
                    if not trade_ok:
                        filtered_count += 1
                        continue
                except:
                    pass
                # -------------------------------
                
                # SAT sinyali
                entry_price = cur_price
                original_sl = cur_price + sl_mult * cur_atr
                stop_loss = original_sl
                take_profit = cur_price - tp_mult * cur_atr
                position = "SELL"
                entry_time = df.index[i]
    
    # İstatistikleri hesapla
    if not trades:
        return {"error": "Bu periyotta hiç sinyal oluşmadı"}
    
    tp_trades = [t for t in trades if t["result"] == "TP"]
    sl_trades = [t for t in trades if t["result"] == "SL"]
    total = len(trades)
    win_rate = len(tp_trades) / total * 100 if total > 0 else 0
    
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
        "sl_mult": sl_mult,
        "tp_mult": tp_mult,
        "total_signals": total,
        "filtered_signals": filtered_count,
        "tp_count": len(tp_trades),
        "sl_count": len(sl_trades),
        "win_rate": round(win_rate, 1),
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "max_drawdown": max_drawdown,
        "trades": trades[-10:]
    }
