import json
import os
import uuid
from datetime import datetime

SIGNALS_FILE = os.path.join(os.path.dirname(__file__), "open_signals.json")


def _load() -> list:
    if not os.path.exists(SIGNALS_FILE):
        return []
    with open(SIGNALS_FILE) as f:
        return json.load(f)


def _save(signals: list):
    with open(SIGNALS_FILE, "w") as f:
        json.dump(signals, f, indent=2)


def add_signal(
    user_id: int,
    symbol: str,
    signal_type: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    atr: float,
    timeframe: str,
    reason: str,
) -> dict:
    signals = _load()
    signal = {
        "id": str(uuid.uuid4())[:8],
        "user_id": user_id,
        "symbol": symbol,
        "signal_type": signal_type,
        "entry_price": round(entry_price, 6),
        "stop_loss": round(stop_loss, 6),
        "take_profit": round(take_profit, 6),
        "atr": round(atr, 6),
        "timeframe": timeframe,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "status": "open",
        "close_price": None,
        "pnl_pct": None,
        "reason": reason,
    }
    signals.append(signal)
    _save(signals)
    return signal


def get_open_signals(user_id: int) -> list:
    return [s for s in _load() if s["user_id"] == user_id and s["status"] == "open"]


def get_all_open_signals() -> list:
    return [s for s in _load() if s["status"] == "open"]


def get_all_closed_signals(user_id: int) -> list:
    return [s for s in _load() if s["user_id"] == user_id and s["status"] != "open"]


def get_open_signals_for_coin(user_id: int, symbol: str) -> list:
    return [
        s for s in _load()
        if s["user_id"] == user_id and s["symbol"] == symbol and s["status"] == "open"
    ]


def _calc_pnl(signal_type: str, entry: float, close: float) -> float:
    if signal_type == "BUY":
        return round((close - entry) / entry * 100, 2)
    else:
        return round((entry - close) / entry * 100, 2)


def close_signal(signal_id: str, status: str, close_price: float) -> bool:
    """Sinyali kapatır. Zaten kapalıysa False döner (çift kapama koruması)."""
    signals = _load()
    changed = False
    for s in signals:
        if s["id"] == signal_id and s["status"] == "open":
            s["status"] = status
            s["close_price"] = round(close_price, 6)
            s["pnl_pct"] = _calc_pnl(s["signal_type"], s["entry_price"], close_price)
            s["closed_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            changed = True
    if changed:
        _save(signals)
    return changed


def close_all_open_for_coin(user_id: int, symbol: str, close_price: float, status: str = "reversed") -> list:
    """Bir coin için tüm açık sinyalleri kapatır. Kapatılan sinyalleri döndürür."""
    signals = _load()
    closed = []
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    for s in signals:
        if s["user_id"] == user_id and s["symbol"] == symbol and s["status"] == "open":
            s["status"] = status
            s["close_price"] = round(close_price, 6)
            s["pnl_pct"] = _calc_pnl(s["signal_type"], s["entry_price"], close_price)
            s["closed_at"] = now
            closed.append(s.copy())
    _save(signals)
    return closed


def check_and_update_signal(signal: dict, current_price: float) -> str:
    if signal["signal_type"] == "BUY":
        if current_price >= signal["take_profit"]:
            return "tp_hit"
        elif current_price <= signal["stop_loss"]:
            return "sl_hit"
    else:
        if current_price <= signal["take_profit"]:
            return "tp_hit"
        elif current_price >= signal["stop_loss"]:
            return "sl_hit"
    return "open"


def get_history(user_id: int, symbol: str = None, page: int = 0, per_page: int = 5) -> dict:
    """Kapalı sinyalleri sayfalı döndürür. En yeniden eskiye sıralı."""
    all_signals = _load()
    closed = [
        s for s in all_signals
        if s["user_id"] == user_id and s["status"] != "open"
        and (symbol is None or s["symbol"] == symbol)
    ]
    closed.sort(key=lambda s: s.get("closed_at", s.get("timestamp", "")), reverse=True)
    total = len(closed)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    items = closed[start: start + per_page]
    return {
        "items": items,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    }


def get_stats(user_id: int, symbol: str = None) -> dict:
    """Kullanıcının sinyal istatistiklerini hesaplar. symbol verilirse o coini filtreler."""
    all_signals = _load()
    signals = [
        s for s in all_signals
        if s["user_id"] == user_id and s["status"] != "open"
        and (symbol is None or s["symbol"] == symbol)
    ]

    tp = [s for s in signals if s["status"] == "tp_hit"]
    sl = [s for s in signals if s["status"] == "sl_hit"]
    rev = [s for s in signals if s["status"] == "reversed"]

    total_decided = len(tp) + len(sl)
    win_rate = (len(tp) / total_decided * 100) if total_decided > 0 else None

    all_pnl = [s["pnl_pct"] for s in signals if s.get("pnl_pct") is not None]
    net_pnl = round(sum(all_pnl), 2) if all_pnl else None
    avg_win = round(sum(s["pnl_pct"] for s in tp if s.get("pnl_pct") is not None) / len(tp), 2) if tp else None
    avg_loss = round(sum(s["pnl_pct"] for s in sl if s.get("pnl_pct") is not None) / len(sl), 2) if sl else None

    # Coin bazında dağılım
    by_coin = {}
    for s in signals:
        sym = s["symbol"]
        if sym not in by_coin:
            by_coin[sym] = {"tp": 0, "sl": 0, "rev": 0, "pnl": []}
        if s["status"] == "tp_hit":
            by_coin[sym]["tp"] += 1
        elif s["status"] == "sl_hit":
            by_coin[sym]["sl"] += 1
        elif s["status"] == "reversed":
            by_coin[sym]["rev"] += 1
        if s.get("pnl_pct") is not None:
            by_coin[sym]["pnl"].append(s["pnl_pct"])

    return {
        "total": len(signals),
        "tp_count": len(tp),
        "sl_count": len(sl),
        "rev_count": len(rev),
        "win_rate": win_rate,
        "net_pnl": net_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "by_coin": by_coin,
    }
