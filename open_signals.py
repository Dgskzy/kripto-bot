import os
import uuid
from datetime import datetime
from pymongo import MongoClient

MONGODB_URI = os.environ.get("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["kripto_bot"]
col = db["open_signals"]


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
    strength: str = "WEAK",
) -> dict:
    signal = {
        "_id": str(uuid.uuid4())[:8],
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
        "strength": strength,
    }
    col.insert_one(signal)
    signal["id"] = signal.pop("_id")
    return signal


def _to_signal(doc: dict) -> dict:
    doc["id"] = doc.pop("_id")
    return doc


def get_open_signals(user_id: int) -> list:
    return [_to_signal(d) for d in col.find({"user_id": user_id, "status": "open"})]


def get_all_open_signals() -> list:
    return [_to_signal(d) for d in col.find({"status": "open"})]


def get_all_closed_signals(user_id: int) -> list:
    return [_to_signal(d) for d in col.find({"user_id": user_id, "status": {"$ne": "open"}})]


def get_open_signals_for_coin(user_id: int, symbol: str) -> list:
    return [_to_signal(d) for d in col.find({"user_id": user_id, "symbol": symbol, "status": "open"})]


def _calc_pnl(signal_type: str, entry: float, close: float) -> float:
    if signal_type == "BUY":
        return round((close - entry) / entry * 100, 2)
    return round((entry - close) / entry * 100, 2)


def close_signal(signal_id: str, status: str, close_price: float) -> bool:
    pnl = None
    doc = col.find_one({"_id": signal_id, "status": "open"})
    if not doc:
        return False
    pnl = _calc_pnl(doc["signal_type"], doc["entry_price"], close_price)
    result = col.update_one(
        {"_id": signal_id, "status": "open"},
        {"$set": {
            "status": status,
            "close_price": round(close_price, 6),
            "pnl_pct": pnl,
            "closed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        }},
    )
    return result.modified_count > 0


def close_all_open_for_coin(user_id: int, symbol: str, close_price: float, status: str = "reversed") -> list:
    docs = list(col.find({"user_id": user_id, "symbol": symbol, "status": "open"}))
    closed = []
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    for doc in docs:
        pnl = _calc_pnl(doc["signal_type"], doc["entry_price"], close_price)
        col.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "status": status,
                "close_price": round(close_price, 6),
                "pnl_pct": pnl,
                "closed_at": now,
            }},
        )
        doc["id"] = doc.pop("_id")
        doc["status"] = status
        doc["close_price"] = round(close_price, 6)
        doc["pnl_pct"] = pnl
        closed.append(doc)
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
    query = {"user_id": user_id, "status": {"$ne": "open"}}
    if symbol:
        query["symbol"] = symbol
    total = col.count_documents(query)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    docs = list(
        col.find(query)
        .sort("closed_at", -1)
        .skip(page * per_page)
        .limit(per_page)
    )
    return {
        "items": [_to_signal(d) for d in docs],
        "page": page,
        "total_pages": total_pages,
        "total": total,
    }


def get_stats(user_id: int, symbol: str = None) -> dict:
    query = {"user_id": user_id, "status": {"$ne": "open"}}
    if symbol:
        query["symbol"] = symbol
    signals = [_to_signal(d) for d in col.find(query)]

    tp  = [s for s in signals if s["status"] == "tp_hit"]
    sl  = [s for s in signals if s["status"] == "sl_hit"]
    rev = [s for s in signals if s["status"] == "reversed"]

    total_decided = len(tp) + len(sl)
    win_rate = (len(tp) / total_decided * 100) if total_decided > 0 else None

    all_pnl  = [s["pnl_pct"] for s in signals if s.get("pnl_pct") is not None]
    net_pnl  = round(sum(all_pnl), 2) if all_pnl else None
    avg_win  = round(sum(s["pnl_pct"] for s in tp if s.get("pnl_pct") is not None) / len(tp), 2) if tp else None
    avg_loss = round(sum(s["pnl_pct"] for s in sl if s.get("pnl_pct") is not None) / len(sl), 2) if sl else None

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


def _update_signal_sl(signal_id: str, new_sl: float):
    col.update_one(
        {"_id": signal_id, "status": "open"},
        {"$set": {"stop_loss": round(new_sl, 6)}},
    )

def _update_signal_tp(signal_id: str, new_tp: float):
    col.update_one(
        {"_id": signal_id, "status": "open"},
        {"$set": {"take_profit": round(new_tp, 6)}},
    )
