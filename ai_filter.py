import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import joblib
import os
import json

MODEL_FILE  = os.path.join(os.path.dirname(__file__), "ai_model.pkl")
SCALER_FILE = os.path.join(os.path.dirname(__file__), "ai_scaler.pkl")
DATA_FILE   = os.path.join(os.path.dirname(__file__), "ai_training_data.json")


class AISignalFilter:
    """
    Yapay Zeka Sinyal Filtresi

    Geçmiş trade verilerinden öğrenerek yeni sinyallerin
    kârlı olma olasılığını tahmin eder.

    Özellikler (v2 — Trend Analizi uyumlu):
    1. Trend yönü         (1=Yükseliş, -1=Düşüş)
    2. Trend gücü R²      (0-100)
    3. RSI                (0-100)
    4. ATR / Fiyat %      (volatilite)
    5. Sinyal tipi        (BUY=1, SELL=-1)
    6. Risk/Ödül oranı    (tp_mult / sl_mult)
    7. Fonlama oranı      (varsa, yoksa 0)
    """

    def __init__(self):
        self.model     = None
        self.scaler    = StandardScaler()
        self.is_trained = False
        self.load_model()

    def extract_features(self, signal_data: dict) -> np.ndarray | None:
        price = signal_data.get("entry_price", 0)
        if price == 0:
            return None

        features = []

        # 1. Trend yönü
        trend_dir = signal_data.get("trend_direction", 0)
        features.append(float(trend_dir))

        # 2. Trend gücü R²
        trend_str = signal_data.get("trend_strength", 50.0)
        features.append(float(trend_str))

        # 3. RSI
        rsi = signal_data.get("rsi", 50)
        features.append(float(rsi))

        # 4. Volatilite (ATR / Fiyat %)
        atr     = signal_data.get("atr", 0)
        atr_pct = atr / price * 100 if price > 0 else 0
        features.append(float(atr_pct))

        # 5. Sinyal tipi (BUY=1, SELL=-1)
        sig_type = 1 if signal_data.get("signal_type") == "BUY" else -1
        features.append(float(sig_type))

        # 6. Risk/Ödül oranı
        sl_mult  = signal_data.get("sl_mult", 1.5)
        tp_mult  = signal_data.get("tp_mult", 3.0)
        rr_ratio = tp_mult / sl_mult if sl_mult > 0 else 0
        features.append(float(rr_ratio))

        # 7. Fonlama oranı
        funding_rate = signal_data.get("funding_rate", 0.0)
        features.append(float(funding_rate))

        return np.array(features).reshape(1, -1)

    def train(self, trades_data: list) -> bool:
        if len(trades_data) < 10:
            return False

        X, y = [], []
        for trade in trades_data:
            feats  = trade.get("features", [])
            result = trade.get("result", "SL")
            if len(feats) == 7:
                X.append(feats)
                y.append(1 if result == "TP" else 0)

        if len(X) < 10 or sum(y) == 0 or sum(y) == len(y):
            return False

        X = np.array(X)
        y = np.array(y)
        X_scaled = self.scaler.fit_transform(X)

        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=5,
            random_state=42,
        )
        self.model.fit(X_scaled, y)
        self.is_trained = True
        self.save_model()
        return True

    def predict(self, signal_data: dict) -> dict:
        """
        Sinyalin kârlı olma olasılığını tahmin eder.
        Döndürdüğü: {"probability": float, "confidence": str, "approved": bool}
        """
        if not self.is_trained or self.model is None:
            return {"probability": 50.0, "confidence": "NO_MODEL", "approved": True}

        features = self.extract_features(signal_data)
        if features is None:
            return {"probability": 50.0, "confidence": "NO_DATA", "approved": True}

        features_scaled = self.scaler.transform(features)
        proba    = self.model.predict_proba(features_scaled)[0]
        win_prob = proba[1] if len(proba) > 1 else 0.5

        if win_prob >= 0.65:
            confidence = "HIGH"
            approved   = True
        elif win_prob >= 0.45:
            confidence = "MEDIUM"
            approved   = True
        else:
            confidence = "LOW"
            approved   = False

        return {
            "probability": round(win_prob * 100, 1),
            "confidence":  confidence,
            "approved":    approved,
        }

    def save_model(self):
        if self.model and self.is_trained:
            joblib.dump(self.model,  MODEL_FILE)
            joblib.dump(self.scaler, SCALER_FILE)

    def load_model(self):
        if os.path.exists(MODEL_FILE) and os.path.exists(SCALER_FILE):
            try:
                self.model     = joblib.load(MODEL_FILE)
                self.scaler    = joblib.load(SCALER_FILE)
                self.is_trained = True
            except Exception:
                pass

    def add_trade_data(self, signal_data: dict, result: str):
        """Yeni trade verisini eğitim setine ekler; 5 trade'de bir yeniden eğitir."""
        features = self.extract_features(signal_data)
        if features is None:
            return

        data = []
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                try:
                    data = json.load(f)
                except Exception:
                    data = []

        data.append({
            "features":  features.flatten().tolist(),
            "result":    result,
            "timestamp": str(pd.Timestamp.now()),
        })
        data = data[-500:]   # Son 500 trade'i tut

        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)

        if len(data) >= 10 and len(data) % 5 == 0:
            self.train(data)


# Global instance
ai_filter = AISignalFilter()
