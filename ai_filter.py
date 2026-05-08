import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import os
import io
import joblib
import pickle
from pymongo import MongoClient

# ── MongoDB bağlantısı ──────────────────────────────────────────────
MONGODB_URI = os.environ.get("MONGODB_URI")
_client = MongoClient(MONGODB_URI)
_db     = _client["kripto_bot"]
_col    = _db["ai_training_data"]   # Yeni koleksiyon
_model_col = _db["ai_model_store"]  # Model binary'si için


class AISignalFilter:
    """
    Yapay Zeka Sinyal Filtresi — MongoDB tabanlı kalıcı depolama

    Özellikler (7 adet):
    1. Trend yönü         (1=Yükseliş, -1=Düşüş)
    2. Trend gücü R²      (0-100)
    3. RSI                (0-100)
    4. ATR / Fiyat %      (volatilite)
    5. Sinyal tipi        (BUY=1, SELL=-1)
    6. Risk/Ödül oranı    (tp_mult / sl_mult)
    7. Fonlama oranı
    """

    def __init__(self):
        self.model      = None
        self.scaler     = StandardScaler()
        self.is_trained = False
        self._load_model_from_mongo()

    # ── Özellik çıkarımı ──────────────────────────────────────────
    def extract_features(self, signal_data: dict) -> np.ndarray | None:
        price = signal_data.get("entry_price", 0) or 100.0

        features = [
            float(signal_data.get("trend_direction", 0)),
            float(signal_data.get("trend_strength", 50.0)),
            float(signal_data.get("rsi", 50)),
            float(signal_data.get("atr", 0)) / price * 100,
            1.0 if signal_data.get("signal_type") == "BUY" else -1.0,
            float(signal_data.get("tp_mult", 3.0)) / max(float(signal_data.get("sl_mult", 1.5)), 0.01),
            float(signal_data.get("funding_rate", 0.0)),
        ]
        return np.array(features).reshape(1, -1)

    # ── Eğitim ────────────────────────────────────────────────────
    def train(self, trades_data: list) -> bool:
        if len(trades_data) < 10:
            return False

        X, y = [], []
        for trade in trades_data:
            feats  = trade.get("features", [])
            result = trade.get("result", "sl_hit")
            if len(feats) == 7:
                X.append(feats)
                y.append(1 if result in ("TP", "tp_hit") else 0)

        if len(X) < 10 or sum(y) < 2 or (len(y) - sum(y)) < 2:
            return False

        try:
            X_scaled = self.scaler.fit_transform(np.array(X))
            self.model = RandomForestClassifier(
                n_estimators=50, max_depth=3, random_state=42
            )
            self.model.fit(X_scaled, np.array(y))
            self.is_trained = True
            self._save_model_to_mongo()
            return True
        except Exception as e:
            print(f"Train error: {e}")
            return False

    # ── Tahmin ────────────────────────────────────────────────────
    def predict(self, signal_data: dict) -> dict:
        if not self.is_trained or self.model is None:
            return {"probability": 50.0, "confidence": "NO_MODEL", "approved": True}

        features_scaled = self.scaler.transform(self.extract_features(signal_data))
        proba    = self.model.predict_proba(features_scaled)[0]
        win_prob = proba[1] if len(proba) > 1 else 0.5

        if win_prob >= 0.65:
            confidence, approved = "HIGH",   True
        elif win_prob >= 0.45:
            confidence, approved = "MEDIUM", True
        else:
            confidence, approved = "LOW",    False

        return {
            "probability": round(win_prob * 100, 1),
            "confidence":  confidence,
            "approved":    approved,
        }

    # ── Trade verisi ekle → MongoDB ───────────────────────────────
    def add_trade_data(self, signal_data: dict, result: str):
        features = self.extract_features(signal_data)
        if features is None:
            return

        normalized = "tp_hit" if result in ("TP", "tp_hit") else "sl_hit"

        _col.insert_one({
            "features":  features.flatten().tolist(),
            "result":    normalized,
            "timestamp": str(pd.Timestamp.now()),
        })

        # Son 500 kaydı tut (eskiyi sil)
        total = _col.count_documents({})
        if total > 500:
            oldest = list(_col.find({}, {"_id": 1}).sort("timestamp", 1).limit(total - 500))
            ids = [d["_id"] for d in oldest]
            _col.delete_many({"_id": {"$in": ids}})

        # Her 5 trade'de bir yeniden eğit
        count = _col.count_documents({})
        if count >= 10 and count % 5 == 0:
            all_data = list(_col.find({}, {"_id": 0}))
            self.train(all_data)

    # ── MongoDB'den tüm veriyi yükle ve eğit ─────────────────────
    def train_from_mongo(self) -> bool:
        all_data = list(_col.find({}, {"_id": 0}))
        if not all_data:
            return False
        return self.train(all_data)

    def get_stats(self) -> dict:
        total = _col.count_documents({})
        tp    = _col.count_documents({"result": "tp_hit"})
        return {"total": total, "tp": tp, "sl": total - tp}

    # ── Model kaydet / yükle (MongoDB binary) ─────────────────────
    def _save_model_to_mongo(self):
        try:
            model_bytes  = pickle.dumps(self.model)
            scaler_bytes = pickle.dumps(self.scaler)
            _model_col.replace_one(
                {"_id": "ai_model"},
                {"_id": "ai_model", "model": model_bytes, "scaler": scaler_bytes},
                upsert=True,
            )
        except Exception as e:
            print(f"Model save error: {e}")

    def _load_model_from_mongo(self):
        try:
            doc = _model_col.find_one({"_id": "ai_model"})
            if doc:
                self.model   = pickle.loads(doc["model"])
                self.scaler  = pickle.loads(doc["scaler"])
                self.is_trained = True
        except Exception as e:
            print(f"Model load error: {e}")


# Global instance
ai_filter = AISignalFilter()
