import ccxt
import pandas as pd
import numpy as np
from signals import (
    calc_atr,
    get_coin_profile,
    get_dynamic_sl_mult,
    compute_trend_series,
    compute_strength_series,
    TREND_METHOD,
    TREND_PERIOD,
    TREND_STRENGTH_MIN,
)
from trailing_stop import calc_trailing_duo

exchange = ccxt.binance()

TF_BARS_PER_DAY = {
    "1m": 1440, "5m": 288, "15m": 96,
    "30m": 48,  "1h": 24,  "4h": 6, "1d": 1,
}


def run_backtest(
    symbol: str,
    timeframe: str = "1h",
    days: int = 30,
    method: str = TREND_METHOD,
    trend_period: int = TREND_PERIOD,
) -> dict:
    """
    Trend Analizi (Pine Script Mr_Rakun) + Trailing Stop/TP Backtesti (v3).

    Filtreler:
    - R² minimum (dinamik eşik)
    - Onay mumu
    - Hacim
    """
    profile  = get_coin_profile(symbol)
    base_sl  = profile["sl_mult"]
    tp_mult  = profile["tp_mult"]

    bars_per_day = TF_BARS_PER_DAY.get(timeframe, 24)
    limit        = min(days * bars_per_day + trend_period + 10, 1500)

    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception as e:
        return {"error": f"Veri alınamadı: {str(e)[:60]}"}

    df = pd.DataFrame(
        ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)

    if len(df) < trend_period + 10:
        return {"error": f"Yetersiz veri: {len(df)} bar (min {trend_period + 10} gerekli)"}

    atr_series      = calc_atr(df)
    trend_series    = compute_trend_series(df, trend_period, method)
    strength_series = compute_strength_series(df["close"], trend_period)

    trades           = []
    filtered_count   = 0
    position         = None
    entry_price      = 0.0
    stop_loss        = 0.0
    take_profit      = 0.0
    original_sl      = 0.0
    original_tp      = 0.0
    entry_time       = None

    start_i = trend_period + 3   # Onay mumu için +1 bar daha

    for i in range(start_i, len(df) - 1):
        cur_open   = float(df["open"].iloc[i])
        cur_high   = float(df["high"].iloc[i])
        cur_low    = float(df["low"].iloc[i])
        cur_close  = float(df["close"].iloc[i])
        cur_atr    = float(atr_series.iloc[i])
        cur_volume = float(df["volume"].iloc[i])

        # Trend ve güç bilgileri (bir önceki kapalı mum)
        cur_trend    = int(trend_series.iloc[i-1])
        prev_trend   = int(trend_series.iloc[i-2])
        cur_strength = float(strength_series.iloc[i-1])

        # Onay mumu: mevcut mumun trendi sinyali doğruluyor mu?
        next_trend   = int(trend_series.iloc[i])

        bullish_start = (prev_trend != 1)  and (cur_trend == 1)
        bearish_start = (prev_trend != -1) and (cur_trend == -1)

        # ── Açık pozisyon yönetimi ──────────────────────────────────
        if position is not None:
            # Dinamik SL ve TP hesapla
            new_sl, new_tp = calc_trailing_duo(
                signal_type=position,
                entry_price=entry_price,
                current_price=cur_close,
                atr=cur_atr,
                original_sl=original_sl,
                original_tp=original_tp,
                trend_strength=cur_strength,
                sl_mult=sl_mult,
                tp_mult=tp_mult,
            )
            stop_loss   = new_sl
            take_profit = new_tp

        if position == "BUY":
            if cur_open <= stop_loss:
                exit_px = cur_open
                pnl = (exit_px - entry_price) / entry_price * 100
                trades.append(_make_trade("BUY", entry_price, exit_px, "SL",
                                          pnl, entry_time, df.index[i]))
                position = None

            elif cur_low <= stop_loss and cur_high >= take_profit:
                # Hangisi daha önce gerçekleşti?
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

        # ── Yeni sinyal (pozisyon yoksa) ────────────────────────────
        if position is None:
            if bullish_start or bearish_start:
                # ═══ FİLTRE 1: DİNAMİK R² ═══
                atr_pct = (cur_atr / cur_close) * 100
                if atr_pct >= 1.5:
                    min_r2 = 35
                elif atr_pct >= 0.8:
                    min_r2 = 45
                else:
                    min_r2 = 55

                if cur_strength < min_r2:
                    filtered_count += 1
                    continue

                # ═══ FİLTRE 2: ONAY MUMU ═══
                if bullish_start and next_trend != 1:
                    filtered_count += 1
                    continue
                if bearish_start and next_trend != -1:
                    filtered_count += 1
                    continue

                # ═══ FİLTRE 3: HACİM ═══
                avg_volume = float(df["volume"].tail(20).mean())
                if cur_volume < avg_volume * 0.6:
                    filtered_count += 1
                    continue

                # Dinamik SL çarpanı
                sl_mult = get_dynamic_sl_mult(cur_strength, base_sl)

                if bullish_start:
                    entry_price = cur_close
                    original_sl = cur_close - sl_mult * cur_atr
                    original_tp = cur_close + tp_mult * cur_atr
                    stop_loss   = original_sl
                    take_profit = original_tp
                    position    = "BUY"
                    entry_time  = df.index[i]
                else:
                    entry_price = cur_close
                    original_sl = cur_close + sl_mult * cur_atr
                    original_tp = cur_close - tp_mult * cur_atr
                    stop_loss   = original_sl
                    take_profit = original_tp
                    position    = "SELL"
                    entry_time  = df.index[i]

    # ── İstatistikler ────────────────────────────────────────────────
    if not trades:
        return {"error": f"Sinyal yok ({len(df)} bar, {days} gün, yöntem: {method})"}

    tp_trades = [t for t in trades if t["result"] == "TP"]
    sl_trades = [t for t in trades if t["result"] == "SL"]
    total     = len(trades)
    win_rate  = len(tp_trades) / total * 100 if total > 0 else 0

    all_pnl      = [t["pnl"] for t in trades]
    total_pnl    = round(sum(all_pnl), 2)
    avg_win      = round(sum(t["pnl"] for t in tp_trades) / len(tp_trades), 2) if tp_trades else 0
    avg_loss     = round(sum(t["pnl"] for t in sl_trades) / len(sl_trades), 2) if sl_trades else 0
    cumulative   = np.cumsum(all_pnl)
    running_max  = np.maximum.accumulate(cumulative)
    drawdowns    = cumulative - running_max
    max_drawdown = round(abs(float(drawdowns.min())), 2) if len(drawdowns) > 0 else 0.0

    return {
        "symbol":           symbol,
        "timeframe":        timeframe,
        "period":           f"{days} gün",
        "method":           method,
        "trend_period":     trend_period,
        "sl_mult":          sl_mult if 'sl_mult' in dir() else base_sl,
        "tp_mult":          tp_mult,
        "total_signals":    total,
        "filtered_signals": filtered_count,
        "tp_count":         len(tp_trades),
        "sl_count":         len(sl_trades),
        "win_rate":         round(win_rate, 1),
        "total_pnl":        total_pnl,
        "avg_win":          avg_win,
        "avg_loss":         avg_loss,
        "max_drawdown":     max_drawdown,
        "trades":           trades[-10:],
    }


def _make_trade(trade_type, entry, exit_px, result, pnl, entry_time, exit_time):
    return {
        "type":       trade_type,
        "entry":      entry,
        "exit":       exit_px,
        "result":     result,
        "pnl":        round(pnl, 2),
        "entry_time": entry_time,
        "exit_time":  exit_time,
    }
