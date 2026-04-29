from backtest import run_backtest

async def backtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Geçmiş verilerde stratejiyi test eder."""
    if not context.args:
        await update.message.reply_text(
            "Kullanım: /backtest <coin> <gün>\n"
            "Örnek: /backtest BTC 30\n"
            "Örnek: /backtest ETH 60"
        )
        return
    
    raw = context.args[0]
    days = int(context.args[1]) if len(context.args) > 1 else 30
    days = min(days, 90)  # Max 90 gün
    
    symbol = normalize_symbol(raw)
    msg = await update.message.reply_text(f"⏳ {symbol} için {days} günlük backtest yapılıyor...")
    
    try:
        result = run_backtest(symbol, "1h", days)
        
        if "error" in result:
            await msg.edit_text(f"❌ {result['error']}")
            return
        
        text = (
            f"📊 *BACKTEST SONUCU*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Coin: *{symbol}*\n"
            f"Periyot: {result['period']}\n"
            f"Zaman Dilimi: {result['timeframe']}\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📡 Toplam Sinyal: *{result['total_signals']}*\n"
            f"✅ TP: *{result['tp_count']}* | ❌ SL: *{result['sl_count']}*\n"
            f"🎯 Kazanma Oranı: *%{result['win_rate']}*\n\n"
            f"💰 Toplam P&L: *%{result['total_pnl']:+.2f}*\n"
            f"📈 Ort. Kâr: *%+{result['avg_win']:.2f}*\n"
            f"📉 Ort. Zarar: *%{result['avg_loss']:.2f}*\n"
            f"🔻 Max Drawdown: *%{result['max_drawdown']:.2f}*\n\n"
            f"📋 *Son İşlemler:*\n"
        )
        
        for t in result["trades"][-5:]:
            icon = "✅" if t["result"] == "TP" else "❌"
            text += f"{icon} {t['type']}: %{t['pnl']:+.2f} ({t['exit_time'].strftime('%d/%m %H:%M')})\n"
        
        text += f"\n⚠️ _Geçmiş performans geleceği garanti etmez._"
        await msg.edit_text(text, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Backtest error: {e}")
        await msg.edit_text(f"❌ Backtest başarısız: {e}")
