import json
import os
import uuid
from dataclasses import dataclass, asdict
from typing import Optional

ALERTS_FILE = os.path.join(os.path.dirname(__file__), "alerts.json")


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


def _load_alerts() -> list[Alert]:
    if not os.path.exists(ALERTS_FILE):
        return []
    with open(ALERTS_FILE, "r") as f:
        data = json.load(f)
    return [Alert.from_dict(a) for a in data]


def _save_alerts(alerts: list[Alert]):
    with open(ALERTS_FILE, "w") as f:
        json.dump([a.to_dict() for a in alerts], f, indent=2)


def add_alert(user_id: int, symbol: str, condition: str, target_price: float) -> Alert:
    alerts = _load_alerts()
    alert = Alert(
        id=str(uuid.uuid4())[:8],
        user_id=user_id,
        symbol=symbol.upper(),
        condition=condition,
        target_price=target_price,
    )
    alerts.append(alert)
    _save_alerts(alerts)
    return alert


def get_user_alerts(user_id: int) -> list[Alert]:
    return [a for a in _load_alerts() if a.user_id == user_id and not a.triggered]


def get_all_active_alerts() -> list[Alert]:
    return [a for a in _load_alerts() if not a.triggered]


def mark_alert_triggered(alert_id: str):
    alerts = _load_alerts()
    for a in alerts:
        if a.id == alert_id:
            a.triggered = True
    _save_alerts(alerts)


def delete_alert(user_id: int, alert_id: str) -> bool:
    alerts = _load_alerts()
    original_count = len(alerts)
    alerts = [a for a in alerts if not (a.id == alert_id and a.user_id == user_id)]
    if len(alerts) < original_count:
        _save_alerts(alerts)
        return True
    return False
