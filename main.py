import logging
import os
import threading
from flask import Flask
from smart_watchlist import scan_best_coins
from watchlist import DEFAULT_COINS
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from funding_filter import get_funding_info
from trailing_stop import calc_trailing_sl
from ai_filter import ai_filter
from market_regime import detect_market_regime, should_trade
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
from telegram.request import HTTPXRequest

import ccxt
from signals import (
    get_current_price,
    calculate_signals,
    detect_signal,
    get_dashboard_data,
    format_price,
    normalize_symbol,
    TREND_METHOD,
    TREND_PERIOD,
    TREND_STRENGTH_MIN,
)
from alerts import (
    add_alert, get_user_alerts, get_all_active_alerts,
    mark_alert_triggered, delete_alert,
)
from watchlist import (
    add_coin, remove_coin, set_timeframe, set_mtf_timeframe,
    get_user_settings, get_all_users_with_coins,
    update_last_signal, get_last_signal, VALID_TIMEFRAMES,
)
from open_signals import (
    add_signal, get_open_signals, get_all_open_signals,
    get_open_signals_for_coin, close_signal, close_all_open_for_coin,
    check_and_update_signal, get_stats, get_history, _update_signal_sl,
)
from backtest import run_backtest

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# ══════════════════════════════════════════════════════════════════════
# HELP METNİ
# ══════════════════════════════════════════════════════════════════════
HELP_TEXT = f"""
🤖 *Kripto Sinyal Botu — Tüm Komutlar*

📊 *Fiyat & Analiz*
/price <coin> — Anlık fiyat + fonlama oranı
/signals <coin> — Trend analizi, ATR, RSI, SL/TP detayı
/signals <coin> <tf> — Belirtilen zaman diliminde analiz

📋 *Takip Listesi*
/addcoin <coin> — Coin ekle
/removecoin <coin> — Coin çıkar
/watchlist — Takip listeni ve son sinyalleri göster
/setinterval <zaman> — Zaman dilimi (1m 5m 15m 30m 1h 4h 1d)
/setmtf <zaman> — MTF üst trend zaman dilimi
/smartwl — En iyi 10 coin'i otomatik seç (mevcut TF)
/smartwl <zaman> — Belirtilen TF'de akıllı watchlist
/dashboard — Tüm takip coinlerin trend özeti

🔍 *Tarama & Sıralama*
/top — Takip listesini R² + RSI puanına göre sırala
/scan20 — Binance Top 20 hacim + trend taraması

📡 *Sinyal Takibi*
/opensignals — Açık sinyaller, P&L, SL/TP durumu
/stats — Genel istatistikler (win rate, P&L, drawdown)
/stats <coin> — Coin bazlı istatistik
/history — Son kapanan sinyaller (sayfalı)
/history <coin> — Coin bazlı sinyal geçmişi

📈 *Backtest*
/backtest <coin> <gün> — Geçmiş performans testi
Örnek: /backtest BTC 30 → 30 günlük backtest

🔔 *Fiyat Alarmları*
/alert <coin> <üstünde|altında> <fiyat> — Alarm kur
/myalerts — Aktif alarmlarım (silme butonlu)
/delalert <id> — Alarm sil

🔧 *Sistem*
/debug — Bot durumu, MongoDB, AI, dosya kontrolü
/settings — Tüm ayarlarını göster (TTF, MTF, coin'ler)
/ayar — /settings kısayolu

📌 *Örnek Kullanım*
`/addcoin BTC` — Bitcoin'i takibe al
`/setinterval 15m` — 15 dakikalık tarama
`/setmtf 1h` — Ana trend 1 saatlik
`/smartwl` — En iyi 10 coin'i otomatik bul
`/signals ETH` — ETH detaylı analiz
`/backtest SOL 30` — SOL 30 günlük backtest
`/alert BTC üstünde 100000` — BTC $100K alarmı

🧠 *Strateji Detayları*
📐 Yöntem: {TREND_METHOD} (Pine Script Mr_Rakun)
📏 Periyot: {TREND_PERIOD} bar | Min R²: %{TREND_STRENGTH_MIN}
🛡️ Dinamik SL (R² bazlı genişler/daralır)
🎯 TP/SL: Coin bazlı ATR çarpanı (1:2 R:R)
📊 MTF: Üst zaman dilimi trend filtresi
🔒 Spam koruması: Aynı yön tekrarı engellenir
💾 Veritabanı: MongoDB Atlas (kalıcı)
"""


# ══════════════════════════════════════════════════════════════════════
# KOMUTLAR
# ══════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Kripto Sinyal Botuna Hoş Geldiniz!\n\n"
        "Pine Script'teki Trend Analysis [Mr_Rakun] göstergesinin Python uyarlamasıyla "
        "otomatik AL/SAT sinyalleri üretirim.\n\n"
        f"Yöntem: {TREND_METHOD} | Periyot: {TREND_PERIOD} bar\n"
        f"R² trend gücü filtresi (min %{TREND_STRENGTH_MIN})\n"
        "ATR tabanlı Stop Loss / Take Profit + Trailing Stop\n\n"
        + HELP_TEXT,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /price <coin>\nÖrnek: /price BTC")
        return
    raw = context.args[0]
    try:
        symbol  = normalize_symbol(raw)
        msg     = await update.message.reply_text(f"⏳ {symbol} fiyatı alınıyor...")
        price   = get_current_price(symbol)
        funding = get_funding_info(symbol)
        await msg.edit_text(
            f"💰 *{symbol}*\n\n"
            f"Anlık Fiyat: *{format_price(price)}*\n"
            f"📊 Fonlama: *%{funding['rate']}* {funding['icon']} {funding['text']}",
            
        )
    except Exception as e:
        logger.error(f"Price error for {raw}: {e}")
        await update.message.reply_text(
            f"❌ '{raw}' için fiyat alınamadı. Coin sembolünü kontrol edin.\nÖrnek: BTC, ETH, SOL"
        )


async def smartwl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """En uygun 10 coin'i otomatik seçer."""
    
    # Kullanıcının zaman dilimini al
    settings = get_user_settings(update.effective_user.id)
    timeframe = settings.get("timeframe", "15m")
    
    # Veya komutla belirtilen zaman dilimi
    if context.args:
        tf = context.args[0]
        if tf in VALID_TIMEFRAMES:
            timeframe = tf
    
    msg = await update.message.reply_text(f"🧠 En iyi 10 coin taranıyor... ({timeframe})\nBu işlem 1-2 dakika sürebilir.")
    
    try:
        coins = scan_best_coins(timeframe=timeframe, limit=50, top_n=10)
        
        if not coins:
            await msg.edit_text("❌ Tarama başarısız.")
            return
        
        user_id = update.effective_user.id
        user_settings = get_user_settings(user_id)
        
        # Eski listeyi temizle
        for old in user_settings.get("coins", []):
            remove_coin(user_id, old)
        
        # Yeni coin'leri ekle
        for coin in coins:
            add_coin(user_id, coin["symbol"])
        
        lines = [f"🧠 *AKILLI WATCHLIST* — {timeframe}\n"]
        for i, c in enumerate(coins, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            lines.append(
                f"{medal} *{c['symbol']}* — Puan: `{c['score']}`\n"
                f"  R²: `%{c['avg_r2']}` | Vol: `%{c['volatility']}` | "
                f"Değişim: `{c['trend_changes']}`"
            )
        
        lines.append(f"\n✅ Takip listeniz güncellendi! `/watchlist` ile kontrol edin.")
        await msg.edit_text("\n".join(lines), parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"SmartWL error: {e}")
        await msg.edit_text(f"❌ Tarama başarısız: {e}")


async def signals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Kullanım: /signals <coin> [timeframe]\nÖrnek: /signals BTC\nÖrnek: /signals ETH 4h"
        )
        return
    raw = context.args[0]
    tf  = context.args[1] if len(context.args) > 1 else None
    try:
        symbol   = normalize_symbol(raw)
        settings = get_user_settings(update.effective_user.id)
        timeframe = tf if tf in VALID_TIMEFRAMES else settings.get("timeframe", "1h")
        msg = await update.message.reply_text(f"⏳ {symbol} analiz ediliyor...")
        s   = calculate_signals(symbol, timeframe)

        # Piyasa rejimi
        regime    = detect_market_regime(symbol, timeframe)
        trade_ok, regime_msg = should_trade(regime)

        # Fonlama
        funding = get_funding_info(symbol)

        # AI filtresi
        ai_text = ""
        try:
            ai_data = {
                "entry_price":    s["price"],
                "trend_direction": s["trend"],
                "trend_strength":  s["strength"],
                "rsi":            s["rsi"],
                "atr":            s["atr"],
                "signal_type":    ("BUY" if "AL" in s["overall"]
                                   else "SELL" if "SAT" in s["overall"]
                                   else "NEUTRAL"),
                "sl_mult": s.get("sl_mult", 1.5),
                "tp_mult": s.get("tp_mult", 3.0),
                "funding_rate": funding.get("rate", 0.0),
            }
            ai_res  = ai_filter.predict(ai_data)
            ai_text = (
                f"🤖 *AI Onay:* `%{ai_res['probability']}` "
                f"(`{ai_res['confidence']}`)\n\n"
            )
        except Exception as e:
            logger.warning(f"AI filter error: {e}")

        text = (
            f"📊 *{s['symbol']} — Trend Analizi*\n"
            f"⏱ Zaman: {s['timeframe']} — Fiyat: *{format_price(s['price'])}*\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🎯 *KARAR: {s['overall']}*\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"📈 *Trend Yönü* ({s['trend_method']})\n"
            f"Durum: `{s['trend_text']}`\n"
            f"Regresyon Hattı: `{format_price(s['regline'])}`\n\n"
            f"💪 Trend Gücü (R²)\n"
            f"Skor: `%{s['strength']}` — `{s['strength_text']}`\n"
            f"Periyot: `{s['trend_period']}` bar\n\n"
            f"📏 *ATR Seviyeleri*\n"
            f"ATR: `{format_price(s['atr'])}`\n"
            f"AL  → SL: `{format_price(s['sl_buy'])}` | TP: `{format_price(s['tp_buy'])}`\n"
            f"SAT → SL: `{format_price(s['sl_sell'])}` | TP: `{format_price(s['tp_sell'])}`\n\n"
            f"RSI \\(14\\): `{s['rsi']}`\n"
            f"📊 *Fonlama:* %{funding['rate']} {funding['icon']} {funding['text']}\n\n"
            f"{ai_text}"
            f"📈 Piyasa Rejimi: {regime['regime']} (Eğim: %{regime['adx']})\n"
            f"   {regime_msg}\n\n"
            f"⚠️ Bu bilgiler yatırım tavsiyesi değildir."
        )
        await msg.edit_text(text)
    except Exception as e:
        logger.error(f"Signals error for {raw}: {e}")
        await update.message.reply_text(f"❌ '{raw}' için analiz yapılamadı.")


async def addcoin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /addcoin <coin>\nÖrnek: /addcoin BTC")
        return
    raw = context.args[0]
    try:
        symbol   = normalize_symbol(raw)
        price    = get_current_price(symbol)
        user_id  = update.effective_user.id
        added    = add_coin(user_id, symbol)
        settings = get_user_settings(user_id)
        if added:
            await update.message.reply_text(
                f"✅ *{symbol}* takip listesine eklendi!\n"
                f"Anlık fiyat: {format_price(price)}\n"
                f"Zaman dilimi: {settings.get('timeframe', '1h')}\n\n"
                f"Trend yönü değişip R²≥%{TREND_STRENGTH_MIN} olduğunda sinyal alacaksınız.",
                
            )
        else:
            await update.message.reply_text(
                f"*{symbol}* zaten takip listenizdeydi.", 
            )
    except Exception as e:
        logger.error(f"Addcoin error {raw}: {e}")
        await update.message.reply_text(f"❌ '{raw}' eklenemedi. Coin sembolünü kontrol edin.")


async def removecoin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /removecoin <coin>\nÖrnek: /removecoin BTC")
        return
    raw    = context.args[0]
    symbol = normalize_symbol(raw)
    if remove_coin(update.effective_user.id, symbol):
        await update.message.reply_text(
            f"✅ *{symbol}* takip listesinden çıkarıldı."
        )
    else:
        await update.message.reply_text(f"*{symbol}* takip listenizde bulunamadı.")


async def setinterval_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0] not in VALID_TIMEFRAMES:
        await update.message.reply_text(
            f"Kullanım: /setinterval <zaman>\n"
            f"Geçerli değerler: {' | '.join(VALID_TIMEFRAMES)}\n"
            f"Örnek: /setinterval 4h"
        )
        return
    tf = context.args[0]
    set_timeframe(update.effective_user.id, tf)
    await update.message.reply_text(
        f"✅ Zaman dilimi *{tf}* olarak güncellendi.\n"
        f"Tüm sinyal taramaları bu zaman dilimiyle çalışacak.",
        
    )


async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Takip listesindeki coinleri trend skoru + RSI'ya göre sıralar."""
    user_id  = update.effective_user.id
    settings = get_user_settings(user_id)
    coins    = settings.get("coins", []) or DEFAULT_COINS
    timeframe = settings.get("timeframe", "1h")

    msg = await update.message.reply_text(f"⏳ {len(coins)} coin taranıyor...")

    results = []
    for symbol in coins:
        try:
            s = calculate_signals(symbol, timeframe)
            score = 0.0
            # Trend gücü (max 40 puan)
            score += min(s["strength"] * 0.4, 40)
            # RSI aşırı bölge (25 puan)
            if s["rsi"] < 30 or s["rsi"] > 70:
                score += 25
            elif 40 <= s["rsi"] <= 60:
                score += 10
            # Net trend yönü var (20 puan)
            if s["trend"] != 0:
                score += 20
            # AL/SAT kararı oluştu (15 puan)
            if "AL" in s["overall"] or "SAT" in s["overall"]:
                score += 15

            results.append({
                "symbol":       symbol,
                "price":        s["price"],
                "rsi":          s["rsi"],
                "overall":      s["overall"],
                "trend_text":   s["trend_text"],
                "strength":     s["strength"],
                "strength_text": s["strength_text"],
                "score":        round(score, 1),
            })
        except Exception as e:
            logger.error(f"Top scan error {symbol}: {e}")

    results.sort(key=lambda x: x["score"], reverse=True)

    if not results:
        await msg.edit_text("❌ Hiçbir coin taranamadı.")
        return

    lines = [f"🏆 *EN İYİ SETUPLAR* — {timeframe}\n"]
    for i, r in enumerate(results[:10], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        lines.append(
            f"{medal} *{r['symbol']}* — Puan: `{r['score']}`\n"
            f"  💵 {format_price(r['price'])} | RSI: `{r['rsi']}`\n"
            f"  🎯 {r['overall']} | {r['trend_text']}\n"
            f"  💪 R²: `%{r['strength']}` ({r['strength_text']})\n"
        )

    lines.append("\n⚠️ _Yatırım tavsiyesi değildir._")
    await msg.edit_text("\n".join(lines))


async def scan20_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Binance'de en yüksek hacimli 20 coin'i tarar."""
    msg = await update.message.reply_text(
        "⏳ Binance'den Top 20 coin taranıyor...\nBu işlem 2-3 dakika sürebilir."
    )
    try:
        ex      = ccxt.binance()
        tickers = ex.fetch_tickers()

        usdt_pairs = []
        for symbol, ticker in tickers.items():
            if symbol.endswith("/USDT") and ticker.get("quoteVolume"):
                base = symbol.split("/")[0]
                if base not in ["USDC", "BUSD", "USDP", "TUSD", "FDUSD", "EUR"]:
                    usdt_pairs.append({
                        "symbol": symbol,
                        "volume": ticker["quoteVolume"],
                        "price":  ticker["last"],
                    })

        usdt_pairs.sort(key=lambda x: x["volume"], reverse=True)
        top20 = usdt_pairs[:20]

        lines = [f"📊 *TOP 20 COIN TARAMASI* — 1h\n"]
        for i, coin in enumerate(top20, 1):
            try:
                symbol = coin["symbol"]
                d      = get_dashboard_data(symbol, "1h")
                vol_m  = coin["volume"] / 1_000_000
                vol_text = f"${vol_m:.0f}M" if vol_m >= 1 else f"${vol_m:.2f}M"
                lines.append(
                    f"{i}. *{symbol}*\n"
                    f"  💵 {format_price(d['price'])} | 📊 Hacim: `{vol_text}`\n"
                    f"  {d['trend_emoji']} Trend: `{d['trend_text']}` | R²: `%{d['strength']}`\n"
                    f"  📏 RSI: `{d['rsi']}` | ATR: `{format_price(d['atr'])}`\n"
                )
            except Exception:
                lines.append(f"{i}. *{coin['symbol']}* — ❌ Veri alınamadı\n")

        lines.append("\n⚠️ _Yatırım tavsiyesi değildir._")
        await msg.edit_text("\n".join(lines))

    except Exception as e:
        logger.error(f"Scan20 error: {e}")
        await msg.edit_text(f"❌ Tarama başarısız: {e}")


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    settings  = get_user_settings(user_id)
    coins     = settings.get("coins", [])
    timeframe = settings.get("timeframe", "1h")

    if not coins:
        coins = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT",
                 "XRP/USDT", "LINK/USDT", "EGLD/USDT"]
        for coin in coins:
            try:
                add_coin(user_id, coin)
            except Exception:
                pass

    msg   = await update.message.reply_text(f"⏳ {len(coins)} coin analiz ediliyor...")
    lines = [f"📊 *DASHBOARD* — {timeframe}\n"]

    for symbol in coins:
        try:
            d = get_dashboard_data(symbol, timeframe)
            lines.append(
                f"*{symbol}*\n"
                f"  💵 {format_price(d['price'])}\n"
                f"  {d['trend_emoji']} `{d['trend_text']}` | R²: `%{d['strength']}` ({d['strength_text']})\n"
                f"  📏 ATR: `{format_price(d['atr'])}` | RSI: `{d['rsi']}`\n"
            )
        except Exception as e:
            logger.error(f"Dashboard error {symbol}: {e}")
            lines.append(f"*{symbol}* — ❌ Veri alınamadı\n")

    await msg.edit_text("\n".join(lines))


async def opensignals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    signals = get_open_signals(user_id)

    if not signals:
        await update.message.reply_text(
            "Açık sinyal bulunmuyor.\n\n"
            "Coin ekleyerek otomatik sinyal almaya başlayın: /addcoin BTC"
        )
        return

    msg   = await update.message.reply_text("⏳ Açık sinyaller güncelleniyor...")
    lines = [f"📡 *AÇIK SİNYALLER* ({len(signals)} adet)\n"]

    for s in signals:
        try:
            cur_price  = get_current_price(s["symbol"])
            status_now = check_and_update_signal(s, cur_price)
            if status_now != "open":
                cp = s["take_profit"] if status_now == "tp_hit" else s["stop_loss"]
                close_signal(s["id"], status_now, close_price=cp)

            if s["signal_type"] == "BUY":
                pnl_pct = (cur_price - s["entry_price"]) / s["entry_price"] * 100
            else:
                pnl_pct = (s["entry_price"] - cur_price) / s["entry_price"] * 100

            pnl_icon    = "📈" if pnl_pct >= 0 else "📉"
            status_icon = ("✅ TP HIT" if status_now == "tp_hit"
                           else "❌ SL HIT" if status_now == "sl_hit"
                           else "🟡 AÇIK")
            signal_icon = "🟢" if s["signal_type"] == "BUY" else "🔴"

            lines.append(
                f"{signal_icon} *{s['signal_type']} — {s['symbol']}* [{s['timeframe']}]\n"
                f"  {status_icon}\n"
                f"  Giriş: `{format_price(s['entry_price'])}` | Şu an: `{format_price(cur_price)}`\n"
                f"  {pnl_icon} P&L: `{pnl_pct:+.2f}%`\n"
                f"  SL: `{format_price(s['stop_loss'])}` | TP: `{format_price(s['take_profit'])}`\n"
                f"  ATR: `{format_price(s['atr'])}` | ID: `{s['id']}`\n"
                f"  🕐 {s['timestamp']}\n"
            )
        except Exception as e:
            logger.error(f"Open signals error {s['id']}: {e}")
            lines.append(f"*{s['symbol']}* — ❌ Güncelleme hatası\n")

    await msg.edit_text("\n".join(lines))


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw     = context.args[0] if context.args else None
    symbol  = normalize_symbol(raw) if raw else None
    st      = get_stats(user_id, symbol)
    title   = f"*{symbol}* için" if symbol else "Tüm coinler için"

    if st["total"] == 0:
        await update.message.reply_text(
            f"📊 {title} henüz kapalı sinyal bulunmuyor.\n\n"
            "Coin ekleyerek başlayın: /addcoin BTC"
        )
        return

    win_rate_text = f"`{st['win_rate']:.1f}%`" if st["win_rate"] is not None else "`-`"
    net_pnl  = st["net_pnl"]
    net_icon = "📈" if (net_pnl or 0) >= 0 else "📉"
    net_text = f"`{net_pnl:+.2f}%`" if net_pnl is not None else "`-`"
    avg_win_text  = f"`+{st['avg_win']:.2f}%`"  if st["avg_win"]  is not None else "`-`"
    avg_loss_text = f"`{st['avg_loss']:.2f}%`"  if st["avg_loss"] is not None else "`-`"

    lines = [
        f"📊 *SİNYAL İSTATİSTİKLERİ*\n{title}\n",
        "━━━━━━━━━━━━━━━━",
        f"Toplam Kapalı Sinyal: *{st['total']}*",
        f"✅ Take Profit: *{st['tp_count']}*  |  ❌ Stop Loss: *{st['sl_count']}*",
        f"🔄 Ters Sinyal: *{st['rev_count']}*",
        "",
        f"🎯 Kazanma Oranı: {win_rate_text}",
        f"📈 Ort. Kazanç: {avg_win_text}",
        f"📉 Ort. Kayıp: {avg_loss_text}",
        f"{net_icon} Net P&L: {net_text}",
    ]

    if not symbol and st["by_coin"]:
        lines.append("\n━━━━━━━━━━━━━━━━")
        lines.append("*Coin Bazında Özet*\n")
        for sym, data in st["by_coin"].items():
            net     = round(sum(data["pnl"]), 2) if data["pnl"] else 0
            net_i   = "📈" if net >= 0 else "📉"
            decided = data["tp"] + data["sl"]
            wr      = f"{data['tp']/decided*100:.0f}%" if decided > 0 else "-"
            lines.append(
                f"*{sym}*: ✅{data['tp']} ❌{data['sl']} 🔄{data['rev']}  "
                f"WR:{wr}  {net_i}{net:+.2f}%"
            )

    lines.append("\n⚠️ _Yatırım tavsiyesi değildir._")
    await update.message.reply_text("\n".join(lines))


PER_PAGE = 5
STATUS_LABELS = {
    "tp_hit":   "✅ TP",
    "sl_hit":   "❌ SL",
    "reversed": "🔄 Ters",
}


def _build_history_message(user_id: int, symbol: str | None, page: int):
    result      = get_history(user_id, symbol=symbol, page=page, per_page=PER_PAGE)
    items       = result["items"]
    total       = result["total"]
    current_page = result["page"]
    total_pages = result["total_pages"]
    filter_label = f" — *{symbol}*" if symbol else ""

    if total == 0:
        return (
            f"📜 Henüz kapatılmış sinyal yok{filter_label}.\n\n"
            "Sinyal almak için coin ekleyin: /addcoin BTC",
            None,
        )

    lines = [
        f"📜 *SİNYAL GEÇMİŞİ*{filter_label}\n"
        f"Toplam {total} kayıt | Sayfa {current_page + 1}/{total_pages}\n"
        "━━━━━━━━━━━━━━━━\n"
    ]
    for s in items:
        direction    = "🟢 AL" if s["signal_type"] == "BUY" else "🔴 SAT"
        status_label = STATUS_LABELS.get(s["status"], s["status"])
        pnl          = s.get("pnl_pct")
        pnl_text     = f"`{pnl:+.2f}%`" if pnl is not None else "`-`"
        pnl_icon     = "📈" if (pnl or 0) >= 0 else "📉"
        entry        = format_price(s["entry_price"])
        close_p      = format_price(s["close_price"]) if s.get("close_price") else "-"
        closed_at    = s.get("closed_at", s.get("timestamp", "-"))
        lines.append(
            f"{direction} *{s['symbol']}* [{s['timeframe']}]\n"
            f"  {status_label}  {pnl_icon} {pnl_text}\n"
            f"  Giriş: `{entry}` → Çıkış: `{close_p}`\n"
            f"  🕐 {closed_at}\n"
        )

    sym_key = symbol or ""
    buttons = []
    if current_page > 0:
        buttons.append(
            InlineKeyboardButton("◀ Önceki", callback_data=f"hist:{current_page - 1}:{sym_key}")
        )
    if current_page < total_pages - 1:
        buttons.append(
            InlineKeyboardButton("Sonraki ▶", callback_data=f"hist:{current_page + 1}:{sym_key}")
        )
    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
    return "\n".join(lines), keyboard


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw     = context.args[0] if context.args else None
    symbol  = normalize_symbol(raw) if raw else None
    text, keyboard = _build_history_message(user_id, symbol, page=0)
    await update.message.reply_text(text, reply_markup=keyboard)


async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Kullanım: /alert <coin> <üstünde|altında> <fiyat>\n"
            "Örnek: /alert BTC üstünde 80000\n"
            "Örnek: /alert ETH altında 3000"
        )
        return
    raw_symbol = context.args[0]
    direction  = context.args[1].lower()
    raw_price  = context.args[2].replace(",", ".")

    if direction not in ("üstünde", "altında", "üzerinde"):
        await update.message.reply_text("Yön 'üstünde' veya 'altında' olmalıdır.")
        return

    condition = "above" if direction in ("üstünde", "üzerinde") else "below"

    try:
        target_price = float(raw_price)
    except ValueError:
        await update.message.reply_text("Geçersiz fiyat. Örnek: 80000 veya 0.5")
        return

    try:
        symbol        = normalize_symbol(raw_symbol)
        current_price = get_current_price(symbol)
        alert         = add_alert(update.effective_user.id, symbol, condition, target_price)
        direction_text = "üstüne çıktığında" if condition == "above" else "altına düştüğünde"
        await update.message.reply_text(
            f"✅ *Alarm Kuruldu!*\n\n"
            f"Coin: *{symbol}*\n"
            f"Koşul: Fiyat *{format_price(target_price)}* {direction_text}\n"
            f"Şu anki fiyat: {format_price(current_price)}\n"
            f"Alarm ID: `{alert.id}`",
            
        )
    except Exception as e:
        logger.error(f"Alert error: {e}")
        await update.message.reply_text("❌ Alarm kurulamadı. Coin sembolünü kontrol edin.")


async def myalerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    alerts = get_user_alerts(update.effective_user.id)
    if not alerts:
        await update.message.reply_text(
            "Aktif alarmınız bulunmuyor.\n\nAlarm kurmak için: /alert BTC üstünde 80000"
        )
        return
    text     = "🔔 *Aktif Alarmlarınız*\n\n"
    keyboard = []
    for a in alerts:
        direction = ">" if a.condition == "above" else "<"
        text += f"• `{a.id}` — *{a.symbol}* {direction} {format_price(a.target_price)}\n"
        keyboard.append([InlineKeyboardButton(f"❌ Sil: {a.id}", callback_data=f"del_{a.id}")])
    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def delalert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /delalert <alarm_id>")
        return
    alert_id = context.args[0]
    if delete_alert(update.effective_user.id, alert_id):
        await update.message.reply_text(f"✅ Alarm `{alert_id}` silindi.")
    else:
        await update.message.reply_text("❌ Alarm bulunamadı veya size ait değil.")


async def backtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Kullanım: /backtest <coin> [gün]\n"
            "Örnek: /backtest BTC 30\n"
            "Örnek: /backtest ETH 60\n\n"
            "Zaman dilimi /setinterval ile değiştirilebilir."
        )
        return
    raw  = context.args[0]
    days = int(context.args[1]) if len(context.args) > 1 else 30
    days = min(days, 90)

    symbol    = normalize_symbol(raw)
    settings  = get_user_settings(update.effective_user.id)
    timeframe = settings.get("timeframe", "1h")

    msg = await update.message.reply_text(
        f"⏳ {symbol} için {days} günlük backtest yapılıyor...\n"
        f"Zaman: {timeframe} | Yöntem: {TREND_METHOD}"
    )
    try:
        result = run_backtest(symbol, timeframe, days)

        if "error" in result:
            await msg.edit_text(f"❌ {result['error']}")
            return

        text = (
            f"📊 *BACKTEST SONUCU*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Coin: *{symbol}*\n"
            f"Periyot: {result['period']}\n"
            f"Zaman Dilimi: {result['timeframe']}\n"
            f"Yöntem: {result['method']}\n\n"
            f"SL: {result['sl_mult']}×ATR | TP: {result['tp_mult']}×ATR\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📡 Toplam Sinyal: *{result['total_signals']}*\n"
            f"🚫 R² Filtresiyle Elenen: *{result.get('filtered_signals', 0)}*\n"
            f"✅ TP: *{result['tp_count']}* | ❌ SL: *{result['sl_count']}*\n"
            f"🎯 Kazanma Oranı: *%{result['win_rate']}*\n\n"
            f"💰 Toplam P&L: *%{result['total_pnl']:+.2f}*\n"
            f"📈 Ort. Kâr: *%+{result['avg_win']:.2f}*\n"
            f"📉 Ort. Zarar: *%{result['avg_loss']:.2f}*\n"
            f"🔻 Max Drawdown: *%{result['max_drawdown']:.2f}*\n\n"
            f"📋 *Son İşlemler:*\n"
        )
        for t in result["trades"][-5:]:
            icon  = "✅" if t["result"] == "TP" else "❌"
            etime = t["exit_time"]
            time_str = etime.strftime("%d/%m %H:%M") if hasattr(etime, "strftime") else str(etime)[:10]
            text += f"{icon} {t['type']}: %{t['pnl']:+.2f} ({time_str})\n"

        text += "\n⚠️ _Geçmiş performans geleceği garanti etmez._"
        await msg.edit_text(text)

    except Exception as e:
        logger.error(f"Backtest error: {e}")
        await msg.edit_text(f"❌ Backtest başarısız: {e}")


async def watchlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    settings  = get_user_settings(user_id)
    coins     = settings.get("coins", [])
    timeframe = settings.get("timeframe", "1h")

    if not coins:
        await update.message.reply_text(
            "📋 Takip listeniz boş.\n\n"
            "Eklemek için: /addcoin BTC\n"
            f"Varsayılan liste: {', '.join(DEFAULT_COINS)}"
        )
        return

    lines = [
        f"📋 *TAKİP LİSTESİ* — {len(coins)} coin",
        f"⏱ Zaman dilimi: *{timeframe}*\n",
    ]
    for i, coin in enumerate(coins, 1):
        last_sig  = get_last_signal(user_id, coin)
        sig_icon  = "🟢" if last_sig == "BUY" else "🔴" if last_sig == "SELL" else "⚪"
        lines.append(f"{i}. {coin} {sig_icon} {last_sig or 'Sinyal yok'}")

    lines.append("\n/removecoin <coin> ile çıkarabilirsiniz.")
    await update.message.reply_text("\n".join(lines))


async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lines   = ["🔍 BOT DURUM RAPORU", ""]

    settings = get_user_settings(user_id)
    coins    = settings.get("coins", [])
    lines.append(f"📋 Takip Listesi: {len(coins)} coin")
    if coins:
        lines.append(f"   {', '.join(coins[:5])}{'...' if len(coins) > 5 else ''}")

    open_sigs = get_open_signals(user_id)
    lines.append(f"📡 Açık Sinyaller: {len(open_sigs)} adet")

    try:
        from pymongo import MongoClient
        mc   = MongoClient(os.environ.get("MONGODB_URI"))
        mdb  = mc["kripto_bot"]
        cols = mdb.list_collection_names()
        lines.append(f"🗄️ MongoDB: ✅ Bağlı ({len(cols)} koleksiyon)")
        for c in cols:
            lines.append(f"   📁 {c}: {mdb[c].count_documents({})} belge")
    except Exception as e:
        lines.append(f"🗄️ MongoDB: ❌ {str(e)[:30]}")

    ai_path = os.path.join(os.path.dirname(__file__), "ai_model.pkl")
    lines.append(f"   {'✅' if os.path.exists(ai_path) else '❌'} ai_model.pkl")

    try:
        regime = detect_market_regime("BTC/USDT")
        lines.append(f"📈 Piyasa (BTC): {regime.get('regime', 'N/A')} (Eğim: %{regime.get('adx', 0)})")
    except Exception as e:
        lines.append(f"📈 Piyasa: Hata: {str(e)[:30]}")

    lines.append(f"🤖 AI: {'Eğitildi' if ai_filter.is_trained else 'Henüz eğitilmedi'}")
    lines.append("")
    lines.append(f"📐 Trend Yöntemi: {TREND_METHOD}")
    lines.append(f"📏 Periyot: {TREND_PERIOD} bar | Min R²: %{TREND_STRENGTH_MIN}")
    lines.append("")
    lines.append("⏱ Tarama: Her 10 dk'da bir")
    lines.append("🔔 Alarm: Her 3 dk'da bir")
    lines.append("🛡️ SL/TP: Her 5 dk'da bir")

    # AI eğitim butonu
    if not ai_filter.is_trained:
        keyboard = [[InlineKeyboardButton("🤖 AI'ı Eğit (Geçmiş Trade'lerle)", callback_data="train_ai")]]
        await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
        return

    await update.message.reply_text("\n".join(lines))


# ══════════════════════════════════════════════════════════════════════
# ARKA PLAN GÖREVLERİ
# ══════════════════════════════════════════════════════════════════════

async def scan_watchlist(context: ContextTypes.DEFAULT_TYPE):
    """
    Her 10 dakikada takip listesindeki coinlerde sinyal tarar.
    Spam önleme: aynı yön tekrar gelmez; yön değişince mevcut pozisyon kapatılır.
    """
    users = get_all_users_with_coins()
    for user in users:
        user_id   = user["user_id"]
        timeframe = user["timeframe"]
        for symbol in user["coins"]:
            try:
                # Kullanıcının MTF ayarını al
                user_mtf = user.get("mtf_timeframe", "1h")
                sig = detect_signal(symbol, timeframe, 
                                    use_mtf=True, 
                                    higher_tf=user_mtf)
                if sig is None:
                    continue

                # Trend gücüne göre kalite etiketi
                strength = sig.get("trend_strength", 0)
                if strength > 70:
                    quality = f"AŞIRI GÜÇLÜ {'AL' if sig['signal_type'] == 'BUY' else 'SAT'}"
                elif strength > 50:
                    quality = f"GÜÇLÜ {'AL' if sig['signal_type'] == 'BUY' else 'SAT'}"
                else:
                    quality = f"ORTA {'AL' if sig['signal_type'] == 'BUY' else 'SAT'}"

                # Piyasa rejimi (bilgi amaçlı)
                regime = detect_market_regime(symbol, timeframe)
                regime_text = f"📈 Piyasa: {regime['regime']} (Eğim: %{regime['adx']})\n"

                last = get_last_signal(user_id, symbol)

                # Aynı yön → spam engelle
                if last == sig["signal_type"]:
                    continue

                # Yön değişti → mevcut açık pozisyonları kapat
                if last != "":
                    try:
                        cur_price_rev = get_current_price(symbol)
                    except Exception:
                        cur_price_rev = sig["entry_price"]
                    reversed_signals = close_all_open_for_coin(
                        user_id, symbol, close_price=cur_price_rev, status="reversed"
                    )
                    for old in reversed_signals:
                        try:
                            old_action = "AL" if old["signal_type"] == "BUY" else "SAT"
                            pnl_pct    = old.get("pnl_pct", 0.0)
                            close_px   = old.get("close_price", cur_price_rev)
                            pnl_icon   = "📈" if pnl_pct >= 0 else "📉"
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=(
                                    f"🔄 TERS SİNYAL — {symbol}\n\n"
                                    f"Önceki {old_action} pozisyonu kapatıldı.\n"
                                    f"Giriş: {format_price(old['entry_price'])}\n"
                                    f"Kapanış: {format_price(close_px)}\n"
                                    f"{pnl_icon} Sonuç: {pnl_pct:+.2f}%\n"
                                    f"Signal ID: {old['id']}"
                                ),
                            )
                        except Exception as e:
                            logger.error(f"Reversal notify error {old['id']}: {e}")

                # Yeni sinyali kaydet ve gönder
                update_last_signal(user_id, symbol, sig["signal_type"])
                saved = add_signal(
                    user_id=user_id,
                    symbol=symbol,
                    signal_type=sig["signal_type"],
                    entry_price=sig["entry_price"],
                    stop_loss=sig["stop_loss"],
                    take_profit=sig["take_profit"],
                    atr=sig["atr"],
                    timeframe=timeframe,
                    reason=sig["reason"],
                    strength=quality,
                )

                icon    = "🟢" if sig["signal_type"] == "BUY" else "🔴"
                action  = "AL" if sig["signal_type"] == "BUY" else "SAT"
                funding = get_funding_info(symbol)

                import asyncio
                await asyncio.sleep(3)

                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"{icon} {action} SİNYALİ — {symbol}\n"
                        f"💪 {quality}\n"
                        f"⏱ Zaman: {timeframe}\n\n"
                        f"💵 Giriş Fiyatı: {format_price(sig['entry_price'])}\n"
                        f"🛑 Stop Loss:    {format_price(sig['stop_loss'])} ({sig.get('sl_mult', 1.5)}×ATR)\n"
                        f"🎯 Take Profit:  {format_price(sig['take_profit'])} ({sig.get('tp_mult', 3.0)}×ATR)\n"
                        f"📏 ATR: {format_price(sig['atr'])}\n"
                        f"📊 R:K Oranı: 1:{sig.get('tp_mult', 3.0)/sig.get('sl_mult', 1.5):.1f}\n\n"
                        f"💪 Trend Gücü R²: %{sig.get('trend_strength', 0):.1f}\n"
                        f"📊 Fonlama: %{funding['rate']} {funding['icon']} {funding['text']}\n\n"
                        f"{regime_text}"
                        f"📝 Sebep:\n{sig['reason']}\n\n"
                        f"Signal ID: {saved['id']}\n"
                        f"⚠️ Yatırım tavsiyesi değildir."
                    ),
                )
                logger.info(f"Signal sent: {sig['signal_type']} {symbol} to user {user_id}")
            except Exception as e:
                logger.error(f"Scan error {symbol} user {user_id}: {e}")


async def check_open_signals(context: ContextTypes.DEFAULT_TYPE):
    """Her 5 dakikada açık sinyallerin SL/TP durumunu + trailing stop kontrol eder."""
    signals = get_all_open_signals()
    for s in signals:
        try:
            cur_price = get_current_price(s["symbol"])

            # Trailing stop güncelle
            new_sl = calc_trailing_sl(
                signal_type=s["signal_type"],
                entry_price=s["entry_price"],
                current_price=cur_price,
                atr=s.get("atr", 0),
                original_sl=s["stop_loss"],
                original_tp=s["take_profit"],
                sl_mult=s.get("sl_mult", 1.5),
            )
            if new_sl != s["stop_loss"]:
                s["stop_loss"] = new_sl
                _update_signal_sl(s["id"], new_sl)

            status = check_and_update_signal(s, cur_price)
            if status == "open":
                continue

            close_px = s["take_profit"] if status == "tp_hit" else s["stop_loss"]
            was_open = close_signal(s["id"], status, close_price=close_px)
            if not was_open:
                continue

            icon         = "✅" if status == "tp_hit" else "❌"
            label        = "TAKE PROFIT" if status == "tp_hit" else "STOP LOSS"
            signal_icon  = "🟢" if s["signal_type"] == "BUY" else "🔴"
            action       = "AL" if s["signal_type"] == "BUY" else "SAT"

            if s["signal_type"] == "BUY":
                pnl_pct = (close_px - s["entry_price"]) / s["entry_price"] * 100
            else:
                pnl_pct = (s["entry_price"] - close_px) / s["entry_price"] * 100
            pnl_icon = "📈" if pnl_pct >= 0 else "📉"

            await context.bot.send_message(
                chat_id=s["user_id"],
                text=(
                    f"{icon} {label} TETİKLENDİ!\n\n"
                    f"{signal_icon} {action} — {s['symbol']} [{s['timeframe']}]\n\n"
                    f"Giriş: {format_price(s['entry_price'])}\n"
                    f"Çıkış: {format_price(cur_price)}\n"
                    f"{pnl_icon} Sonuç: {pnl_pct:+.2f}%\n\n"
                    f"Yeni sinyal ancak ters yön oluştuğunda gelecektir.\n"
                    f"Signal ID: {s['id']}"
                ),
            )
            logger.info(f"Signal {s['id']} closed: {status}")
            # 🤖 AI eğitimi için trade verisini kaydet
            ai_filter.add_trade_data(s, status)
        except Exception as e:
            logger.error(f"Open signal check error {s['id']}: {e}")

async def setmtf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """MTF üst zaman dilimini ayarlar."""
    if not context.args or context.args[0] not in VALID_TIMEFRAMES:
        await update.message.reply_text(
            f"Kullanım: /setmtf <zaman>\n"
            f"Geçerli: {' | '.join(VALID_TIMEFRAMES)}\n"
            f"Örnek: /setmtf 4h\n\n"
            f"MTF: Üst zaman dilimi ana trendi belirler.\n"
            f"15dk'da tarama yaparken üst trende ters sinyaller engellenir."
        )
        return
    tf = context.args[0]
    set_mtf_timeframe(update.effective_user.id, tf)
    await update.message.reply_text(
        f"✅ MTF üst zaman dilimi *{tf}* olarak güncellendi.\n"
        f"Ana trend yönü bu zaman diliminden alınacak.",
        parse_mode="Markdown"
    )


async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    """Her 3 dakikada fiyat alarmlarını kontrol eder."""
    alerts = get_all_active_alerts()
    if not alerts:
        return
    for alert in alerts:
        try:
            price = get_current_price(alert.symbol)
            triggered = (
                (alert.condition == "above" and price >= alert.target_price) or
                (alert.condition == "below" and price <= alert.target_price)
            )
            if triggered:
                mark_alert_triggered(alert.id)
                direction_text = "üstüne çıktı" if alert.condition == "above" else "altına düştü"
                await context.bot.send_message(
                    chat_id=alert.user_id,
                    text=(
                        f"🚨 *ALARM TETİKLENDİ!*\n\n"
                        f"*{alert.symbol}* hedef fiyat {format_price(alert.target_price)} {direction_text}!\n\n"
                        f"Şu anki fiyat: *{format_price(price)}*\n"
                        f"Alarm ID: `{alert.id}`"
                    ),
                    
                )
        except Exception as e:
            logger.error(f"Alert check error {alert.id}: {e}")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcının tüm ayarlarını gösterir."""
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    
    timeframe = settings.get("timeframe", "1h")
    mtf = settings.get("mtf_timeframe", "1h")
    coins = settings.get("coins", [])
    
    lines = [
        "⚙️ *AYARLARIM*\n",
        f"⏱ Tetik Zaman Dilimi: *{timeframe}*",
        f"📊 MTF Ana Trend: *{mtf}*",
        f"📋 Takip Listesi: *{len(coins)}* coin",
    ]
    
    if coins:
        lines.append(f"   {', '.join(coins[:10])}")
        if len(coins) > 10:
            lines.append(f"   ... ve {len(coins)-10} coin daha")
    
    lines.append(f"\n📐 Trend Yöntemi: *{TREND_METHOD}*")
    lines.append(f"📏 Periyot: *{TREND_PERIOD}* bar")
    lines.append(f"🎯 Min R²: *%{TREND_STRENGTH_MIN}*")
    lines.append(f"💰 R:R Oranı: *1:2*")
    lines.append(f"🛡️ Dinamik SL: *Aktif*")
    lines.append(f"📊 MTF Filtresi: *{'Aktif' if timeframe in ('15m','5m','1m') else 'Pasif'}*")
    
    lines.append(f"\n⏱ Tarama: Her 10 dk")
    lines.append(f"🔔 Alarm: Her 3 dk")
    lines.append(f"🛡️ SL/TP: Her 5 dk")
    
    lines.append(f"\n💡 Değiştirmek için:")
    lines.append(f"  /setinterval <tf>")
    lines.append(f"  /setmtf <tf>")
    lines.append(f"  /smartwl")
    
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("del_"):
        alert_id = query.data[4:]
        if delete_alert(query.from_user.id, alert_id):
            await query.edit_message_text(f"✅ Alarm `{alert_id}` silindi.")
        else:
            await query.answer("❌ Alarm bulunamadı.", show_alert=True)

    elif query.data.startswith("hist:"):
        parts    = query.data.split(":", 2)
        page     = int(parts[1])
        sym_key  = parts[2] if len(parts) > 2 else ""
        symbol   = sym_key if sym_key else None
        user_id  = query.from_user.id
        text, keyboard = _build_history_message(user_id, symbol, page)
        await query.edit_message_text(text, reply_markup=keyboard)

    elif query.data == "train_ai":
            await query.answer("⏳ AI eğitiliyor...")

        # Geçmiş trade'leri MongoDB'den al ve ai_training_data koleksiyonuna aktar
            from open_signals import col as open_col
            closed = list(open_col.find({
                "user_id": query.from_user.id,
                "status": {"$ne": "open"}
            }))

            imported = 0
            for s in closed:
                s["id"] = s.get("_id", "")
                if "entry_price" not in s:
                    continue
                s.setdefault("trend_direction", 1 if s.get("signal_type") == "BUY" else -1)
                s.setdefault("trend_strength", 50.0)
                s.setdefault("rsi", 50.0)
                s.setdefault("atr", 0.01)
                s.setdefault("sl_mult", 1.5)
                s.setdefault("tp_mult", 3.0)
                s.setdefault("funding_rate", 0.0)
                ai_filter.add_trade_data(s, s.get("status", "sl_hit"))
                imported += 1

            # MongoDB'deki tüm veriyle eğit
            stats  = ai_filter.get_stats()
            result = ai_filter.train_from_mongo()

            if result:
                await query.edit_message_text(
                    f"✅ AI eğitildi!\n\n"
                    f"📊 Toplam veri: {stats['total']}\n"
                    f"✅ TP: {stats['tp']}  |  ❌ SL: {stats['sl']}\n"
                    f"📥 Bu oturumda aktarılan: {imported}"
                )
            else:
                await query.edit_message_text(
                    f"❌ AI eğitilemedi.\n\n"
                    f"📊 Toplam veri: {stats['total']}\n"
                    f"✅ TP: {stats['tp']}  |  ❌ SL: {stats['sl']}\n\n"
                    f"En az 10 trade ve 2'şer TP/SL gerekli."
                )


# ══════════════════════════════════════════════════════════════════════
# ANA UYGULAMA
# ══════════════════════════════════════════════════════════════════════


    def main():
        if not TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN bulunamadı!")
            return

        # 🤖 BOT BAŞLARKEN AI'I MONGODB'DEN OTOMATİK EĞİT
        try:
            stats = ai_filter.get_stats()
            if stats["total"] >= 10:
                result = ai_filter.train_from_mongo()
                logger.info(
                    f"AI auto-train: {'BAŞARILI' if result else 'BAŞARISIZ'} "
                    f"({stats['total']} trade, {stats['tp']} TP)"
                )
            else:
                logger.info(f"AI: Yetersiz veri ({stats['total']} trade), eğitim atlandı.")
        except Exception as e:
            logger.error(f"AI auto-train error: {e}")

    # ... geri kalanı aynı

    # Render Web Service sağlık kontrolü
    app_flask = Flask(__name__)

    @app_flask.route("/")
    def health():
        return "Bot çalışıyor!", 200

    threading.Thread(target=lambda: app_flask.run(host="0.0.0.0", port=10000), daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",        start))
    app.add_handler(CommandHandler("help",         help_command))
    app.add_handler(CommandHandler("price",        price_command))
    app.add_handler(CommandHandler("signals",      signals_command))
    app.add_handler(CommandHandler("smartwl",      smartwl_command))
    app.add_handler(CommandHandler("addcoin",      addcoin_command))
    app.add_handler(CommandHandler("removecoin",   removecoin_command))
    app.add_handler(CommandHandler("watchlist",    watchlist_command))
    app.add_handler(CommandHandler("setinterval",  setinterval_command))
    app.add_handler(CommandHandler("setmtf",       setmtf_command))
    app.add_handler(CommandHandler("top",          top_command))
    app.add_handler(CommandHandler("scan20",       scan20_command))
    app.add_handler(CommandHandler("dashboard",    dashboard_command))
    app.add_handler(CommandHandler("opensignals",  opensignals_command))
    app.add_handler(CommandHandler("stats",        stats_command))
    app.add_handler(CommandHandler("history",      history_command))
    app.add_handler(CommandHandler("alert",        alert_command))
    app.add_handler(CommandHandler("myalerts",     myalerts_command))
    app.add_handler(CommandHandler("delalert",     delalert_command))
    app.add_handler(CommandHandler("backtest",     backtest_command))
    app.add_handler(CommandHandler("ayar",         settings_command))
    app.add_handler(CommandHandler("settings",     settings_command))
    app.add_handler(CommandHandler("debug",        debug_command))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.job_queue.run_repeating(check_alerts,       interval=180,  first=10)
    app.job_queue.run_repeating(scan_watchlist,      interval=180,  first=15)
    app.job_queue.run_repeating(check_open_signals,  interval=300,  first=15)

    logger.info(f"Bot başlatılıyor — Yöntem: {TREND_METHOD}, Periyot: {TREND_PERIOD}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
