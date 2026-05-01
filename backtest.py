import ccxt
import pandas as pd
import numpy as np
from signals import (
    calc_ema, calc_supertrend, calc_atr,
    get_coin_profile
)
from trailing_stop import calc_trailing_sl

exchange = ccxt.binance()

# Timeframe başına bar sayısı (günlük limit hesabı için)
TF_BARS_PER_DAY = {
    "1m": 1440, "5m": 288, "15m": 96,
    "30m": 48,  "1h": 24,  "4h": 6, "1d": 1
}


def run_backtest(symbol: str, timeframe: str = "1h", days: int = 30) -> dict:
    """
    EMA12/26 kesişimi + SuperTrend + Trailing Stop backtesti.

    Düzeltmeler:
    - Aynı mumda hem SL hem TP tetiklenirse açılış fiyatına yakın olan önce alınır
    - Gap açılışı: fiyat zaten SL'nin ötesinde açılırsa açılış fiyatından çıkılır
    - Timeframe'e göre doğru bar limiti hesaplanır
    - filtered_signals anahtarı eklendi (main.py uyumu)
    - max_drawdown sıfır trade durumunda hata vermez
    """

    profile = get_coin_profile(symbol)
    sl_mult = profile["sl_mult"]
    tp_mult = profile["tp_mult"]

    bars_per_day = TF_BARS_PER_DAY.get(timeframe, 24)
    limit = min(days * bars_per_day + 60, 1500)  # +60 ısınma barı

    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception as e:
        return {"error": f"Veri alınamadı: {str(e)[:60]}"}

    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)

    if len(df) < 60:
        return {"error": f"Yetersiz veri: {len(df)} bar (min 60 gerekli)"}

    ema12 = calc_ema(df["close"], 12)
    ema26 = calc_ema(df["close"], 26)
    supertrend, direction, atr = calc_supertrend(df)

    trades = []
    position = None
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    original_sl = 0.0
    entry_time = None

    for i in range(50, len(df) - 1):
        cur_open  = float(df["open"].iloc[i])
        cur_high  = float(df["high"].iloc[i])
        cur_low   = float(df["low"].iloc[i])
        cur_close = float(df["close"].iloc[i])
        cur_dir   = int(direction.iloc[i])
        cur_atr   = float(atr.iloc[i])

        crossed_up   = (ema12.iloc[i - 1] <= ema26.iloc[i - 1]) and (ema12.iloc[i] > ema26.iloc[i])
        crossed_down = (ema12.iloc[i - 1] >= ema26.iloc[i - 1]) and (ema12.iloc[i] < ema26.iloc[i])

        # ── Açık pozisyon yönetimi ──────────────────────────────────────
        if position == "BUY":
            # Trailing stop güncelle
            stop_loss = calc_trailing_sl(
                "BUY", entry_price, cur_close, cur_atr,
                original_sl, take_profit, sl_mult
            )

            # Gap kontrolü: açılış zaten SL altında
            if cur_open <= stop_loss:
                exit_px = cur_open
                pnl = (exit_px - entry_price) / entry_price * 100
                trades.append(_make_trade("BUY", entry_price, exit_px, "SL",
                                          pnl, entry_time, df.index[i]))
                position = None

            elif cur_low <= stop_loss and cur_high >= take_profit:
                # Aynı mumda ikisi de tetiklendi → açılışa yakın olan önce
                sl_dist = abs(cur_open - stop_loss)
                tp_dist = abs(cur_open - take_profit)
                if sl_dist <= tp_dist:
                    exit_px = stop_loss
                    pnl = (exit_px - entry_price) / entry_price * 100
                    trades.append(_make_trade("BUY", entry_price, exit_px, "SL",
                                              pnl, entry_time, df.index[i]))
                else:
                    exit_px = take_profit
                    pnl = (exit_px - entry_price) / entry_price * 100
                    trades.append(_make_trade("BUY", entry_price, exit_px, "TP",
                                              pnl, entry_time, df.index[i]))
                position = None

            elif cur_low <= stop_loss:
                exit_px = stop_loss
                pnl = (exit_px - entry_price) / entry_price * 100
                trades.append(_make_trade("BUY", entry_price, exit_px, "SL",
                                          pnl, entry_time, df.index[i]))
                position = None

            elif cur_high >= take_profit:
                exit_px = take_profit
                pnl = (exit_px - entry_price) / entry_price * 100
                trades.append(_make_trade("BUY", entry_price, exit_px, "TP",
                                          pnl, entry_time, df.index[i]))
                position = None

        elif position == "SELL":
            stop_loss = calc_trailing_sl(
                "SELL", entry_price, cur_close, cur_atr,
                original_sl, take_profit, sl_mult
            )

            # Gap kontrolü: açılış zaten SL üstünde
            if cur_open >= stop_loss:
                exit_px = cur_open
                pnl = (entry_price - exit_px) / entry_price * 100
                trades.append(_make_trade("SELL", entry_price, exit_px, "SL",
                                          pnl, entry_time, df.index[i]))
                position = None

            elif cur_high >= stop_loss and cur_low <= take_profit:
                sl_dist = abs(cur_open - stop_loss)
                tp_dist = abs(cur_open - take_profit)
                if sl_dist <= tp_dist:
                    exit_px = stop_loss
                    pnl = (entry_price - exit_px) / entry_price * 100
                    trades.append(_make_trade("SELL", entry_price, exit_px, "SL",
                                              pnl, entry_time, df.index[i]))
                else:
                    exit_px = take_profit
                    pnl = (entry_price - exit_px) / entry_price * 100
                    trades.append(_make_trade("SELL", entry_price, exit_px, "TP",
                                              pnl, entry_time, df.index[i]))
                position = None

            elif cur_high >= stop_loss:
                exit_px = stop_loss
                pnl = (entry_price - exit_px) / entry_price * 100
                trades.append(_make_trade("SELL", entry_price, exit_px, "SL",
                                          pnl, entry_time, df.index[i]))
                position = None

            elif cur_low <= take_profit:
                exit_px = take_profit
                pnl = (entry_price - exit_px) / entry_price * 100
                trades.append(_make_trade("SELL", entry_price, exit_px, "TP",
                                          pnl, entry_time, df.index[i]))
                position = None

        # ── Yeni sinyal (pozisyon yoksa) ────────────────────────────────
        if position is None:
            if crossed_up and cur_dir == 1:
                entry_price = cur_close
                original_sl = cur_close - sl_mult * cur_atr
                stop_loss   = original_sl
                take_profit = cur_close + tp_mult * cur_atr
                position    = "BUY"
                entry_time  = df.index[i]

            elif crossed_down and cur_dir == -1:
                entry_price = cur_close
                original_sl = cur_close + sl_mult * cur_atr
                stop_loss   = original_sl
                take_profit = cur_close - tp_mult * cur_atr
                position    = "SELL"
                entry_time  = df.index[i]

    # ── İstatistikler ────────────────────────────────────────────────────
    if not trades:
        return {"error": f"Sinyal yok ({len(df)} bar, {days} gün)"}

    tp_trades = [t for t in trades if t["result"] == "TP"]
    sl_trades = [t for t in trades if t["result"] == "SL"]
    total     = len(trades)
    win_rate  = len(tp_trades) / total * 100 if total > 0 else 0

    all_pnl   = [t["pnl"] for t in trades]
    total_pnl = round(sum(all_pnl), 2)
    avg_win   = round(sum(t["pnl"] for t in tp_trades) / len(tp_trades), 2) if tp_trades else 0
    avg_loss  = round(sum(t["pnl"] for t in sl_trades) / len(sl_trades), 2) if sl_trades else 0

    cumulative   = np.cumsum(all_pnl)
    running_max  = np.maximum.accumulate(cumulative)
    drawdowns    = cumulative - running_max
    max_drawdown = round(abs(float(drawdowns.min())), 2) if len(drawdowns) > 0 else 0.0

    return {
        "symbol":           symbol,
        "timeframe":        timeframe,
        "period":           f"{days} gün",
        "sl_mult":          sl_mult,
        "tp_mult":          tp_mult,
        "total_signals":    total,
        "filtered_signals": 0,          # ← main.py uyumu için
        "tp_count":         len(tp_trades),
        "sl_count":         len(sl_trades),
        "win_rate":         round(win_rate, 1),
        "total_pnl":        total_pnl,
        "avg_win":          avg_win,
        "avg_loss":         avg_loss,
        "max_drawdown":     max_drawdown,
        "trades":           trades[-10:],
    }


def _make_trade(
    trade_type: str,
    entry: float,
    exit_px: float,
    result: str,
    pnl: float,
    entry_time,
    exit_time,
) -> dict:
    return {
        "type":       trade_type,
        "entry":      entry,
        "exit":       exit_px,
        "result":     result,
        "pnl":        round(pnl, 2),
        "entry_time": entry_time,
        "exit_time":  exit_time,
    }
