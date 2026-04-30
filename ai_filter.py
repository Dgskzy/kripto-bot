import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import joblib
import os
import json

MODEL_FILE = os.path.join(os.path.dirname(__file__), "ai_model.pkl")
SCALER_FILE = os.path.join(os.path.dirname(__file__), "ai_scaler.pkl")
DATA_FILE = os.path.join(os.path.dirname(__file__), "ai_training_data.json")

class AISignalFilter:
    """
    Yapay Zeka Sinyal Filtresi
    
    Geçmiş trade verilerinden öğrenerek, yeni sinyallerin
    kârlı olma olasılığını tahmin eder.
    """
    
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.load_model()
    
    def extract_features(self, signal_data: dict) -> np.ndarray:
        """
        Sinyal verisinden AI için özellikler çıkarır.
        
        Özellikler:
        - EMA farkı (%)
        - RSI değeri
        - ATR / Fiyat oranı (volatilite)
        - SuperTrend yönü
        - EMA trend gücü
        - Fonlama oranı (varsa)
        """
        price = signal_data.get("entry_price", 0)
        if price == 0:
            return None
        
        features = []
        
        # 1. EMA farkı (%)
        ema12 = signal_data.get("ema12", price)
        ema26 = signal_data.get("ema26", price)
        ema_diff_pct = abs(ema12 - ema26) / price * 100
        features.append(ema_diff_pct)
        
        # 2. RSI
        rsi = signal_data.get("rsi", 50)
        features.append(rsi)
        
        # 3. Volatilite (ATR / Fiyat %)
        atr = signal_data.get("atr", 0)
        atr_pct = atr / price * 100 if price > 0 else 0
        features.append(atr_pct)
        
        # 4. SuperTrend yönü (1 = yukarı, -1 = aşağı)
        st_dir = signal_data.get("supertrend_dir", 0)
        features.append(st_dir)
        
        # 5. EMA trend gücü (pozitif = yükseliş, negatif = düşüş)
        ema_trend = (ema12 - ema26) / price * 100
        features.append(ema_trend)
        
        # 6. Sinyal tipi (BUY=1, SELL=-1)
        sig_type = 1 if signal_data.get("signal_type") == "BUY" else -1
        features.append(sig_type)
        
        # 7. Risk/Ödül oranı
        sl_mult = signal_data.get("sl_mult", 1.5)
        tp_mult = signal_data.get("tp_mult", 3.0)
        rr_ratio = tp_mult / sl_mult if sl_mult > 0 else 0
        features.append(rr_ratio)
        
        return np.array(features).reshape(1, -1)
    
    def train(self, trades_data: list) -> bool:
        """
        Geçmiş trade verileriyle modeli eğitir.
        
        trades_data: [{"features": [...], "result": "TP"}, ...]
        """
        if len(trades_data) < 10:
            return False
        
        X = []
        y = []
        
        for trade in trades_data:
            feats = trade.get("features", [])
            result = trade.get("result", "SL")
            
            if len(feats) == 7:  # Tüm özellikler varsa
                X.append(feats)
                y.append(1 if result == "TP" else 0)
        
        if len(X) < 10 or sum(y) == 0 or sum(y) == len(y):
            return False
        
        X = np.array(X)
        y = np.array(y)
        
        # Veriyi ölçeklendir
        X_scaled = self.scaler.fit_transform(X)
        
        # Random Forest modeli
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=5,
            random_state=42
        )
        self.model.fit(X_scaled, y)
        self.is_trained = True
        
        # Modeli kaydet
        self.save_model()
        
        return True
    
    def predict(self, signal_data: dict) -> dict:
        """
        Bir sinyalin kârlı olma olasılığını tahmin eder.
        
        Döndürdüğü:
        {
            "probability": 0.75,  # %75 kârlı olma ihtimali
            "confidence": "HIGH",  # HIGH/MEDIUM/LOW
            "approved": True       # Sinyal onaylandı mı?
        }
        """
        if not self.is_trained or self.model is None:
            return {"probability": 0.5, "confidence": "NO_MODEL", "approved": True}
        
        features = self.extract_features(signal_data)
        if features is None:
            return {"probability": 0.5, "confidence": "NO_DATA", "approved": True}
        
        # Ölçeklendir
        features_scaled = self.scaler.transform(features)
        
        # Tahmin
        proba = self.model.predict_proba(features_scaled)[0]
        win_prob = proba[1] if len(proba) > 1 else 0.5
        
        # Güven seviyesi
        if win_prob >= 0.65:
            confidence = "HIGH"
            approved = True
        elif win_prob >= 0.45:
            confidence = "MEDIUM"
            approved = True
        else:
            confidence = "LOW"
            approved = False
        
        return {
            "probability": round(win_prob * 100, 1),
            "confidence": confidence,
            "approved": approved
        }
    
    def save_model(self):
        """Modeli dosyaya kaydeder."""
        if self.model and self.is_trained:
            joblib.dump(self.model, MODEL_FILE)
            joblib.dump(self.scaler, SCALER_FILE)
    
    def load_model(self):
        """Kaydedilmiş modeli yükler."""
        if os.path.exists(MODEL_FILE) and os.path.exists(SCALER_FILE):
            try:
                self.model = joblib.load(MODEL_FILE)
                self.scaler = joblib.load(SCALER_FILE)
                self.is_trained = True
            except:
                pass
    
    def add_trade_data(self, signal_data: dict, result: str):
        """Yeni trade verisini eğitim verisine ekler."""
        features = self.extract_features(signal_data)
        if features is None:
            return
        
        data = []
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                try:
                    data = json.load(f)
                except:
                    data = []
        
        data.append({
            "features": features.flatten().tolist(),
            "result": result,
            "timestamp": str(pd.Timestamp.now())
        })
        
        # Son 500 trade'i tut
        data = data[-500:]
        
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
        
        # 20 trade'de bir modeli yeniden eğit
        if len(data) >= 10 and len(data) % 5 == 0:
            self.train(data)


# Global instance
ai_filter = AISignalFilter()
