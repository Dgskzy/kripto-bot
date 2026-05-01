import os
import uuid
from dataclasses import dataclass, asdict
from pymongo import MongoClient

MONGODB_URI = os.environ.get("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["kripto_bot"]
col = db["alerts"]


@dataclass
class Alert:
    id: str
    user_id: int
    symbol: str
    condition: str
    target_price: float
    triggered: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)


def _to_alert(doc: dict) -> Alert:
    doc["id"] = doc.pop("_id")
    return Alert.from_dict(doc)


def add_alert(user_id: int, symbol: str, condition: str, target_price: float) -> Alert:
    alert_id = str(uuid.uuid4())[:8]
    doc = {
        "_id": alert_id,
        "id": alert_id,
        "user_id": user_id,
        "symbol": symbol.upper(),
        "condition": condition,
        "target_price": target_price,
        "triggered": False,
    }
    col.insert_one(doc)
    return Alert(
        id=alert_id,
        user_id=user_id,
        symbol=symbol.upper(),
        condition=condition,
        target_price=target_price,
    )


def get_user_alerts(user_id: int) -> list:
    return [_to_alert(d) for d in col.find({"user_id": user_id, "triggered": False})]


def get_all_active_alerts() -> list:
    return [_to_alert(d) for d in col.find({"triggered": False})]


def mark_alert_triggered(alert_id: str):
    col.update_one({"_id": alert_id}, {"$set": {"triggered": True}})


def delete_alert(user_id: int, alert_id: str) -> bool:
    result = col.delete_one({"_id": alert_id, "user_id": user_id})
    return result.deleted_count > 0
