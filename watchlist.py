import os
from pymongo import MongoClient

MONGODB_URI = os.environ.get("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["kripto_bot"]
col = db["watchlist"]

VALID_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
DEFAULT_COINS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "XRP/USDT", "LINK/USDT", "EGLD/USDT"]


def _get(user_id: int) -> dict:
    uid = str(user_id)
    doc = col.find_one({"_id": uid})
    if not doc:
        doc = {
            "_id": uid,
            "coins": DEFAULT_COINS.copy(),
            "timeframe": "1h",
            "mtf_timeframe": "1h",
            "last_signals": {},
        }
        col.insert_one(doc)
    return doc


def get_user_settings(user_id: int) -> dict:
    return _get(user_id)


def add_coin(user_id: int, symbol: str) -> bool:
    doc = _get(user_id)
    if symbol in doc["coins"]:
        return False
    col.update_one({"_id": str(user_id)}, {"$push": {"coins": symbol}})
    return True


def remove_coin(user_id: int, symbol: str) -> bool:
    doc = _get(user_id)
    if symbol not in doc["coins"]:
        return False
    col.update_one(
        {"_id": str(user_id)},
        {
            "$pull": {"coins": symbol},
            "$unset": {f"last_signals.{symbol}": ""},
        },
    )
    return True


def set_timeframe(user_id: int, timeframe: str):
    _get(user_id)
    col.update_one({"_id": str(user_id)}, {"$set": {"timeframe": timeframe}})


def get_all_users_with_coins() -> list:
    result = []
    for doc in col.find():
        coins = doc.get("coins", [])
        if not coins:
            coins = DEFAULT_COINS.copy()
        result.append({
            "user_id": int(doc["_id"]),
            "coins": coins,
            "timeframe": doc.get("timeframe", "1h"),
            "last_signals": doc.get("last_signals", {}),
        })
    return result


def update_last_signal(user_id: int, symbol: str, signal_type: str):
    _get(user_id)
    col.update_one(
        {"_id": str(user_id)},
        {"$set": {f"last_signals.{symbol}": signal_type}},
    )


def get_last_signal(user_id: int, symbol: str) -> str:
    doc = _get(user_id)
    return doc.get("last_signals", {}).get(symbol, "")

def set_mtf_timeframe(user_id: int, timeframe: str):
    """MTF üst zaman dilimini günceller."""
    _get(user_id)  # Kullanıcı yoksa oluştur
    col.update_one(
        {"_id": str(user_id)},
        {"$set": {"mtf_timeframe": timeframe}}
    )

def get_all_last_signals(user_id: int) -> dict:
    """Kullanıcının tüm coin'ler için son sinyal kayıtlarını döndürür."""
    doc = _get(user_id)
    return doc.get("last_signals", {})

from datetime import datetime, timezone

def update_last_signal_time(user_id: int, symbol: str):
    """Bir sinyal gönderildiğinde veya güncellendiğinde zaman damgasını kaydeder."""
    col.update_one(
        {"_id": str(user_id)},
        {"$set": {f"last_signal_time.{symbol}": datetime.now(timezone.utc)}}
    )

def get_last_signal_time(user_id: int, symbol: str):
    """Bir coin için son sinyal zaman damgasını döndürür."""
    doc = _get(user_id)
    return doc.get("last_signal_time", {}).get(symbol)



