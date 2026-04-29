import json
import os

# Varsayılan coin listesi (Render sıfırlansa bile kaybolmaz!)
DEFAULT_COINS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "XRP/USDT", "LINK/USDT", "EGLD/USDT"]

WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlist.json")

VALID_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]


def _load() -> dict:
    if not os.path.exists(WATCHLIST_FILE):
        return {}
    with open(WATCHLIST_FILE) as f:
        return json.load(f)


def _save(data: dict):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _user(data: dict, user_id: int) -> dict:
    uid = str(user_id)
    if uid not in data:
        # Varsayılan coin listesiyle başla
        data[uid] = {"coins": DEFAULT_COINS.copy(), "timeframe": "1h", "last_signals": {}}
        _save(data)  # Hemen kaydet ki kalıcı olsun
    return data[uid]


def get_user_settings(user_id: int) -> dict:
    data = _load()
    return _user(data, user_id)


def add_coin(user_id: int, symbol: str) -> bool:
    data = _load()
    u = _user(data, user_id)
    if symbol in u["coins"]:
        return False
    u["coins"].append(symbol)
    _save(data)
    return True


def remove_coin(user_id: int, symbol: str) -> bool:
    data = _load()
    u = _user(data, user_id)
    if symbol not in u["coins"]:
        return False
    u["coins"].remove(symbol)
    u["last_signals"].pop(symbol, None)
    _save(data)
    return True


def set_timeframe(user_id: int, timeframe: str):
    data = _load()
    u = _user(data, user_id)
    u["timeframe"] = timeframe
    _save(data)


def get_all_users_with_coins() -> list:
    data = _load()
    result = []
    for uid, udata in data.items():
        if udata.get("coins"):
            result.append({
                "user_id": int(uid),
                "coins": udata["coins"],
                "timeframe": udata.get("timeframe", "1h"),
                "last_signals": udata.get("last_signals", {}),
            })
    return result


def update_last_signal(user_id: int, symbol: str, signal_type: str):
    data = _load()
    u = _user(data, user_id)
    u["last_signals"][symbol] = signal_type
    _save(data)


def get_last_signal(user_id: int, symbol: str) -> str:
    data = _load()
    u = _user(data, user_id)
    return u["last_signals"].get(symbol, "")
