import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
from telegram.request import HTTPXRequest

from signals import (
    get_current_price,
    calculate_signals,
    detect_signal,
    get_dashboard_data,
    format_price,
    normalize_symbol,
)
from alerts import add_alert, get_user_alerts, get_all_active_alerts, mark_alert_triggered, delete_alert
from watchlist import (
    add_coin,
    remove_coin,
    set_timeframe,
    get_user_settings,
    get_all_users_with_coins,
    update_last_signal,
    get_last_signal,
    VALID_TIMEFRAMES,
)
from open_signals import (
    add_signal,
    get_open_signals,
    get_all_open_signals,
    get_open_signals_for_coin,
    close_signal,
    close_all_open_for_coin,
    check_and_update_signal,
    get_stats,
    get_history,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

HELP_TEXT = """
*Kripto Sinyal Botu — Komutlar*

📊 *Fiyat & Analiz*
/price <coin> — Anlık fiyat
/signals <coin> — EMA, SuperTrend, ATR analizi

📋 *Takip Listesi*
/addcoin <coin> — Coin ekle
/removecoin <coin> — Coin çıkar
/setinterval <zaman> — Zaman dilimi (1m 5m 15m 30m 1h 4h 1d)
/dashboard — Tüm takip coinlerin son durumu

📡 *Sinyaller*
/opensignals — Açık sinyaller ve güncel durum
/stats — Sinyal geçmişi, başarı oranı ve kâr/zarar istatistikleri
/stats <coin> — Belirli bir coin için istatistik
/history — Son kapatılan sinyaller ve kâr/zarar detayları
/history <coin> — Belirli bir coin için geçmiş

🔔 *Fiyat Alarmları*
/alert <coin> <üstünde|altında> <fiyat> — Alarm kur
/myalerts — Aktif alarmlarım
/delalert <id> — Alarm sil

📌 *Örnekler*
/addcoin BTC
/setinterval 4h
/signals ETH
/alert BTC üstünde 80000

*Strateji:* EMA12/26 kesişimi + SuperTrend
SL = 1.5×ATR | TP = 3×ATR | R:R = 1:2
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Kripto Sinyal Botuna Hoş Geldiniz!*\n\n"
        "EMA 12/26 kesişimi ve SuperTrend kombinasyonuyla otomatik AL/SAT sinyalleri üretirim.\n"
        "ATR tabanlı Stop Loss ve Take Profit hesaplıyorum (SL=1.5×ATR, TP=3×ATR).\n\n"
        + HELP_TEXT,
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /price <coin>\nÖrnek: /price BTC")
        return
    raw = context.args[0]
    try:
        symbol = normalize_symbol(raw)
        msg = await update.message.reply_text(f"⏳ {symbol} fiyatı alınıyor...")
        price = get_current_price(symbol)
        await msg.edit_text(
            f"💰 *{symbol}*\n\nAnlık Fiyat: *{format_price(price)}*",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Price error for {raw}: {e}")
        await update.message.reply_text(
            f"❌ '{raw}' için fiyat alınamadı. Coin sembolünü kontrol edin.\nÖrnek: BTC, ETH, SOL"
        )


async def signals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /signals <coin>\nÖrnek: /signals BTC")
        return
    raw = context.args[0]
    tf = context.args[1] if len(context.args) > 1 else None
    try:
        symbol = normalize_symbol(raw)
        settings = get_user_settings(update.effective_user.id)
        timeframe = tf if tf in VALID_TIMEFRAMES else settings.get("timeframe", "1h")
        msg = await update.message.reply_text(f"⏳ {symbol} analiz ediliyor...")
        s = calculate_signals(symbol, timeframe)

        text = (
            f"📊 *{s['symbol']} — Teknik Analiz*\n"
            f"⏱ Zaman: {s['timeframe']} | Fiyat: *{format_price(s['price'])}*\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🎯 *KARAR: {s['overall']}*\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"📈 *EMA 12 / 26*\n"
            f"EMA12: `{format_price(s['ema12'])}`\n"
            f"EMA26: `{format_price(s['ema26'])}`\n"
            f"Durum: {s['ema_text']}\n\n"
            f"🌊 *SuperTrend (10, 3)*\n"
            f"Değer: `{format_price(s['supertrend'])}`\n"
            f"Durum: {s['supertrend_text']}\n\n"
            f"📏 *ATR (Stop / Hedef)*\n"
            f"ATR: `{format_price(s['atr'])}`\n"
            f"AL için → SL: `{format_price(s['sl_buy'])}` | TP: `{format_price(s['tp_buy'])}`\n"
            f"SAT için → SL: `{format_price(s['sl_sell'])}` | TP: `{format_price(s['tp_sell'])}`\n\n"
            f"RSI (14): `{s['rsi']}`\n\n"
            f"⚠️ _Bu bilgiler yatırım tavsiyesi değildir._"
        )
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Signals error for {raw}: {e}")
        await update.message.reply_text(f"❌ '{raw}' için analiz yapılamadı.")


async def addcoin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /addcoin <coin>\nÖrnek: /addcoin BTC")
        return
    raw = context.args[0]
    try:
        symbol = normalize_symbol(raw)
        price = get_current_price(symbol)
        user_id = update.effective_user.id
        added = add_coin(user_id, symbol)
        settings = get_user_settings(user_id)
        if added:
            await update.message.reply_text(
                f"✅ *{symbol}* takip listesine eklendi!\n"
                f"Anlık fiyat: {format_price(price)}\n"
                f"Zaman dilimi: {settings.get('timeframe', '1h')}\n\n"
                f"EMA12/26 kesişimi + SuperTrend sinyali geldiğinde bildirim alacaksınız.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(f"*{symbol}* zaten takip listenizdeydi.", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Addcoin error {raw}: {e}")
        await update.message.reply_text(f"❌ '{raw}' eklenemedi. Coin sembolünü kontrol edin.")


async def removecoin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /removecoin <coin>\nÖrnek: /removecoin BTC")
        return
    raw = context.args[0]
    symbol = normalize_symbol(raw)
    user_id = update.effective_user.id
    if remove_coin(user_id, symbol):
        await update.message.reply_text(f"✅ *{symbol}* takip listesinden çıkarıldı.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"*{symbol}* takip listenizde bulunamadı.", parse_mode="Markdown")


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
        parse_mode="Markdown",
    )


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    coins = settings.get("coins", [])
    timeframe = settings.get("timeframe", "1h")

    if not coins:
        await update.message.reply_text(
            "Takip listeniz boş.\n\nCoin eklemek için: /addcoin BTC"
        )
        return

    msg = await update.message.reply_text(f"⏳ {len(coins)} coin analiz ediliyor...")

    lines = [f"📊 *DASHBOARD* — {timeframe}\n"]
    for symbol in coins:
        try:
            d = get_dashboard_data(symbol, timeframe)
            st_icon = "🟢" if d["supertrend_dir"] == 1 else "🔴"
            ema_icon = "🟢" if d["ema12"] > d["ema26"] else "🔴"
            lines.append(
                f"*{symbol}*\n"
                f"  💵 {format_price(d['price'])}\n"
                f"  {ema_icon} EMA12: `{format_price(d['ema12'])}` | EMA26: `{format_price(d['ema26'])}`\n"
                f"  {st_icon} SuperTrend: `{format_price(d['supertrend'])}`\n"
                f"  📏 ATR: `{format_price(d['atr'])}` | RSI: `{d['rsi']}`\n"
            )
        except Exception as e:
            logger.error(f"Dashboard error {symbol}: {e}")
            lines.append(f"*{symbol}* — ❌ Veri alınamadı\n")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def opensignals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    signals = get_open_signals(user_id)

    if not signals:
        await update.message.reply_text(
            "Açık sinyal bulunmuyor.\n\n"
            "Coin takip listesine ekleyerek otomatik sinyal almaya başlayın: /addcoin BTC"
        )
        return

    msg = await update.message.reply_text("⏳ Açık sinyaller güncelleniyor...")
    lines = [f"📡 *AÇIK SİNYALLER* ({len(signals)} adet)\n"]

    for s in signals:
        try:
            cur_price = get_current_price(s["symbol"])
            status_now = check_and_update_signal(s, cur_price)
            if status_now != "open":
                cp = s["take_profit"] if status_now == "tp_hit" else s["stop_loss"]
                close_signal(s["id"], status_now, close_price=cp)

            if s["signal_type"] == "BUY":
                pnl_pct = ((cur_price - s["entry_price"]) / s["entry_price"]) * 100
                pnl_icon = "📈" if pnl_pct >= 0 else "📉"
                status_icon = "✅ TP HIT" if status_now == "tp_hit" else ("❌ SL HIT" if status_now == "sl_hit" else "🟡 AÇIK")
            else:
                pnl_pct = ((s["entry_price"] - cur_price) / s["entry_price"]) * 100
                pnl_icon = "📈" if pnl_pct >= 0 else "📉"
                status_icon = "✅ TP HIT" if status_now == "tp_hit" else ("❌ SL HIT" if status_now == "sl_hit" else "🟡 AÇIK")

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

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw = context.args[0] if context.args else None
    symbol = normalize_symbol(raw) if raw else None

    st = get_stats(user_id, symbol)
    title = f"*{symbol}* için" if symbol else "Tüm coinler için"

    if st["total"] == 0:
        await update.message.reply_text(
            f"📊 {title} henüz kapalı sinyal bulunmuyor.\n\n"
            "Coin ekleyerek başlayın: /addcoin BTC"
        )
        return

    win_rate_text = f"`{st['win_rate']:.1f}%`" if st["win_rate"] is not None else "`-`"
    net_pnl = st["net_pnl"]
    net_icon = "📈" if (net_pnl or 0) >= 0 else "📉"
    net_text = f"`{net_pnl:+.2f}%`" if net_pnl is not None else "`-`"
    avg_win_text = f"`+{st['avg_win']:.2f}%`" if st["avg_win"] is not None else "`-`"
    avg_loss_text = f"`{st['avg_loss']:.2f}%`" if st["avg_loss"] is not None else "`-`"

    lines = [
        f"📊 *SİNYAL İSTATİSTİKLERİ*\n{title}\n",
        f"━━━━━━━━━━━━━━━━",
        f"Toplam Kapalı Sinyal: *{st['total']}*",
        f"✅ Take Profit: *{st['tp_count']}*  |  ❌ Stop Loss: *{st['sl_count']}*",
        f"🔄 Ters Sinyal: *{st['rev_count']}*",
        f"",
        f"🎯 Kazanma Oranı: {win_rate_text}",
        f"📈 Ort. Kazanç: {avg_win_text}",
        f"📉 Ort. Kayıp: {avg_loss_text}",
        f"{net_icon} Net P&L: {net_text}",
    ]

    if not symbol and st["by_coin"]:
        lines.append(f"\n━━━━━━━━━━━━━━━━")
        lines.append("*Coin Bazında Özet*\n")
        for sym, data in st["by_coin"].items():
            net = round(sum(data["pnl"]), 2) if data["pnl"] else 0
            net_i = "📈" if net >= 0 else "📉"
            decided = data["tp"] + data["sl"]
            wr = f"{data['tp']/decided*100:.0f}%" if decided > 0 else "-"
            lines.append(
                f"*{sym}*: ✅{data['tp']} ❌{data['sl']} 🔄{data['rev']}  "
                f"WR:{wr}  {net_i}{net:+.2f}%"
            )

    lines.append(f"\n⚠️ _Yatırım tavsiyesi değildir._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


PER_PAGE = 5

STATUS_LABELS = {
    "tp_hit": "✅ TP",
    "sl_hit": "❌ SL",
    "reversed": "🔄 Ters",
}


def _build_history_message(user_id: int, symbol: str | None, page: int) -> tuple[str, object]:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    result = get_history(user_id, symbol=symbol, page=page, per_page=PER_PAGE)
    items = result["items"]
    total = result["total"]
    current_page = result["page"]
    total_pages = result["total_pages"]
    filter_label = f" — *{symbol}*" if symbol else ""

    if total == 0:
        coin_hint = f"/history {symbol}" if not symbol else ""
        return (
            f"📜 Henüz kapatılmış sinyal yok{filter_label}.\n\n"
            "Sinyal almak için coin ekleyin: /addcoin BTC",
            None,
        )

    lines = [f"📜 *SİNYAL GEÇMİŞİ*{filter_label}\n"
             f"Toplam {total} kayıt | Sayfa {current_page + 1}/{total_pages}\n"
             f"━━━━━━━━━━━━━━━━\n"]

    for s in items:
        direction = "🟢 AL" if s["signal_type"] == "BUY" else "🔴 SAT"
        status_label = STATUS_LABELS.get(s["status"], s["status"])
        pnl = s.get("pnl_pct")
        pnl_text = f"`{pnl:+.2f}%`" if pnl is not None else "`-`"
        pnl_icon = "📈" if (pnl or 0) >= 0 else "📉"
        entry = format_price(s["entry_price"])
        close = format_price(s["close_price"]) if s.get("close_price") else "-"
        closed_at = s.get("closed_at", s.get("timestamp", "-"))
        lines.append(
            f"{direction} *{s['symbol']}* [{s['timeframe']}]\n"
            f"  {status_label}  {pnl_icon} {pnl_text}\n"
            f"  Giriş: `{entry}` → Çıkış: `{close}`\n"
            f"  🕐 {closed_at}\n"
        )

    sym_key = symbol or ""
    buttons = []
    if current_page > 0:
        buttons.append(InlineKeyboardButton("◀ Önceki", callback_data=f"hist:{current_page - 1}:{sym_key}"))
    if current_page < total_pages - 1:
        buttons.append(InlineKeyboardButton("Sonraki ▶", callback_data=f"hist:{current_page + 1}:{sym_key}"))

    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
    return "\n".join(lines), keyboard


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw = context.args[0] if context.args else None
    symbol = normalize_symbol(raw) if raw else None

    text, keyboard = _build_history_message(user_id, symbol, page=0)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Kullanım: /alert <coin> <üstünde|altında> <fiyat>\n"
            "Örnek: /alert BTC üstünde 80000\n"
            "Örnek: /alert ETH altında 3000"
        )
        return
    raw_symbol = context.args[0]
    direction = context.args[1].lower()
    raw_price = context.args[2].replace(",", ".")

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
        symbol = normalize_symbol(raw_symbol)
        current_price = get_current_price(symbol)
        alert = add_alert(update.effective_user.id, symbol, condition, target_price)
        direction_text = "üstüne çıktığında" if condition == "above" else "altına düştüğünde"
        await update.message.reply_text(
            f"✅ *Alarm Kuruldu!*\n\n"
            f"Coin: *{symbol}*\n"
            f"Koşul: Fiyat *{format_price(target_price)}* {direction_text}\n"
            f"Şu anki fiyat: {format_price(current_price)}\n"
            f"Alarm ID: `{alert.id}`",
            parse_mode="Markdown",
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
    text = "🔔 *Aktif Alarmlarınız*\n\n"
    keyboard = []
    for a in alerts:
        direction = ">" if a.condition == "above" else "<"
        text += f"• `{a.id}` — *{a.symbol}* {direction} {format_price(a.target_price)}\n"
        keyboard.append([InlineKeyboardButton(f"❌ Sil: {a.id}", callback_data=f"del_{a.id}")])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def delalert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /delalert <alarm_id>")
        return
    alert_id = context.args[0]
    if delete_alert(update.effective_user.id, alert_id):
        await update.message.reply_text(f"✅ Alarm `{alert_id}` silindi.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Alarm bulunamadı veya size ait değil.")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("del_"):
        alert_id = query.data[4:]
        if delete_alert(query.from_user.id, alert_id):
            await query.edit_message_text(f"✅ Alarm `{alert_id}` silindi.", parse_mode="Markdown")
        else:
            await query.answer("❌ Alarm bulunamadı.", show_alert=True)

    elif query.data.startswith("hist:"):
        parts = query.data.split(":", 2)
        page = int(parts[1])
        sym_key = parts[2] if len(parts) > 2 else ""
        symbol = sym_key if sym_key else None
        user_id = query.from_user.id
        text, keyboard = _build_history_message(user_id, symbol, page)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def scan_watchlist(context: ContextTypes.DEFAULT_TYPE):
    """
    Her 5 dakikada takip listesindeki coinlerde sinyal tarar.

    Spam önleme kuralları:
    - Aynı yön (BUY→BUY veya SELL→SELL) tekrar gelmez; yön değişene kadar beklenir.
    - Yön değiştiğinde (BUY→SELL veya SELL→BUY):
        * Mevcut açık pozisyon varsa "ters sinyal" bildirimi ile kapatılır.
        * Yeni sinyal gönderilir.
    - TP veya SL tetiklendiğinde check_open_signals ayrı bildirim gönderir;
      last_signal sıfırlanmaz → yön değişene kadar aynı yön tekrar gelmez.
    """
    users = get_all_users_with_coins()
    for user in users:
        user_id = user["user_id"]
        timeframe = user["timeframe"]
        for symbol in user["coins"]:
            try:
                sig = detect_signal(symbol, timeframe)
                if sig is None:
                    continue

                last = get_last_signal(user_id, symbol)

                # Aynı yön → spam engelle, atla
                if last == sig["signal_type"]:
                    continue

                # Yön değişti → mevcut açık pozisyonları kapat ve bildir
                if last != "":
                    try:
                        cur_price_rev = get_current_price(symbol)
                    except Exception:
                        cur_price_rev = sig["entry_price"]
                    reversed_signals = close_all_open_for_coin(user_id, symbol, close_price=cur_price_rev, status="reversed")
                    for old in reversed_signals:
                        try:
                            old_action = "AL" if old["signal_type"] == "BUY" else "SAT"
                            pnl_pct = old.get("pnl_pct", 0.0)
                            close_px = old.get("close_price", cur_price_rev)
                            pnl_icon = "📈" if pnl_pct >= 0 else "📉"
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=(
                                    f"🔄 *TERS SİNYAL — {symbol}*\n\n"
                                    f"Önceki {old_action} pozisyonu kapatıldı.\n"
                                    f"Giriş: `{format_price(old['entry_price'])}`\n"
                                    f"Kapanış: `{format_price(close_px)}`\n"
                                    f"{pnl_icon} Sonuç: *{pnl_pct:+.2f}%*\n"
                                    f"Signal ID: `{old['id']}`"
                                ),
                                parse_mode="Markdown",
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
                )

                icon = "🟢" if sig["signal_type"] == "BUY" else "🔴"
                action = "AL" if sig["signal_type"] == "BUY" else "SAT"
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"{icon} *{action} SİNYALİ — {symbol}*\n"
                        f"⏱ Zaman: {timeframe}\n\n"
                        f"💵 Giriş Fiyatı: *{format_price(sig['entry_price'])}*\n"
                        f"🛑 Stop Loss: *{format_price(sig['stop_loss'])}* (1.5×ATR)\n"
                        f"🎯 Take Profit: *{format_price(sig['take_profit'])}* (3×ATR)\n"
                        f"📏 ATR: `{format_price(sig['atr'])}`\n"
                        f"📊 R:K Oranı: 1:2\n\n"
                        f"📝 *Sebep:*\n{sig['reason']}\n\n"
                        f"Signal ID: `{saved['id']}`\n"
                        f"⚠️ _Yatırım tavsiyesi değildir._"
                    ),
                    parse_mode="Markdown",
                )
                logger.info(f"Signal sent: {sig['signal_type']} {symbol} to user {user_id}")
            except Exception as e:
                logger.error(f"Scan error {symbol} user {user_id}: {e}")


async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    """Her dakika fiyat alarmlarını kontrol eder."""
    alerts = get_all_active_alerts()
    if not alerts:
        return
    for alert in alerts:
        try:
            price = get_current_price(alert.symbol)
            triggered = (
                alert.condition == "above" and price >= alert.target_price
            ) or (
                alert.condition == "below" and price <= alert.target_price
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
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.error(f"Alert check error {alert.id}: {e}")


async def check_open_signals(context: ContextTypes.DEFAULT_TYPE):
    """
    Her 2 dakikada açık sinyallerin SL/TP durumunu kontrol eder.
    - TP/SL tetiklendiğinde bildirim gönderir ve sinyali kapatır.
    - last_signal SIFIRLANMAZ → yön değişene kadar aynı yön tekrar gelmez.
    - close_signal False dönerse (zaten kapalı) bildirim gönderilmez.
    """
    signals = get_all_open_signals()
    for s in signals:
        try:
            cur_price = get_current_price(s["symbol"])
            status = check_and_update_signal(s, cur_price)
            if status == "open":
                continue

            # TP/SL fiyatını belirle: TP hit ise take_profit, SL hit ise stop_loss
            close_px = s["take_profit"] if status == "tp_hit" else s["stop_loss"]

            # Çift kapama koruması: close_signal False dönerse zaten kapatılmış
            was_open = close_signal(s["id"], status, close_price=close_px)
            if not was_open:
                continue

            icon = "✅" if status == "tp_hit" else "❌"
            label = "TAKE PROFIT" if status == "tp_hit" else "STOP LOSS"
            signal_icon = "🟢" if s["signal_type"] == "BUY" else "🔴"
            action = "AL" if s["signal_type"] == "BUY" else "SAT"

            if s["signal_type"] == "BUY":
                pnl_pct = ((close_px - s["entry_price"]) / s["entry_price"]) * 100
            else:
                pnl_pct = ((s["entry_price"] - close_px) / s["entry_price"]) * 100
            pnl_icon = "📈" if pnl_pct >= 0 else "📉"

            await context.bot.send_message(
                chat_id=s["user_id"],
                text=(
                    f"{icon} *{label} TETİKLENDİ!*\n\n"
                    f"{signal_icon} {action} — *{s['symbol']}* [{s['timeframe']}]\n\n"
                    f"Giriş: `{format_price(s['entry_price'])}`\n"
                    f"Çıkış: *{format_price(cur_price)}*\n"
                    f"{pnl_icon} Sonuç: *{pnl_pct:+.2f}%*\n\n"
                    f"Yeni sinyal ancak ters yön oluştuğunda gelecektir.\n"
                    f"Signal ID: `{s['id']}`"
                ),
                parse_mode="Markdown",
            )
            logger.info(f"Signal {s['id']} closed: {status}")
        except Exception as e:
            logger.error(f"Open signal check error {s['id']}: {e}")


def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN bulunamadı!")
        return

    # Proxy olmadan, ama özel timeout ve bağlantı havuzu ayarlarıyla
    import httpx
    httpx_client = httpx.AsyncClient(
        proxy="http://proxy.server:3128",
        timeout=30.0,
    )
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("price", price_command))
    app.add_handler(CommandHandler("signals", signals_command))
    app.add_handler(CommandHandler("addcoin", addcoin_command))
    app.add_handler(CommandHandler("removecoin", removecoin_command))
    app.add_handler(CommandHandler("setinterval", setinterval_command))
    app.add_handler(CommandHandler("dashboard", dashboard_command))
    app.add_handler(CommandHandler("opensignals", opensignals_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("alert", alert_command))
    app.add_handler(CommandHandler("myalerts", myalerts_command))
    app.add_handler(CommandHandler("delalert", delalert_command))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.job_queue.run_repeating(check_alerts, interval=120, first=10)
    app.job_queue.run_repeating(scan_watchlist, interval=600, first=30)
    app.job_queue.run_repeating(check_open_signals, interval=300, first=15)

    logger.info("Bot başlatılıyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
