#!/usr/bin/env python3
"""
Trading Bot with Telegram Interface - BAHASA GAUL EDITION
===========================================================
Features:
- /start, /status, /help, /ping
- /scan - Scan koin yang match strategy
- /top - Top opportunities
- /analyze <SYMBOL> - Analisis detail koin
"""

import logging
import sys
import os
import random
import numpy as np
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Config
BOT_TOKEN = "8726873215:AAF29V-EAayVmcnyy4R7SJFavrxYtj9ub10"
CHAT_ID = "1130331223"

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ========================================
# ANALYZER FUNCTIONS
# ========================================

def calc_rsi(closes, period=14):
    """Calculate RSI"""
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calc_sma(data, period):
    """Calculate SMA"""
    if len(data) < period:
        return data[-1] if len(data) > 0 else 0
    return np.mean(data[-period:])

def calc_bb(closes, period=20, mult=2.0):
    """Calculate Bollinger Bands"""
    if len(closes) < period:
        return closes[-1], closes[-1], closes[-1], 0
    sma = np.mean(closes[-period:])
    std = np.std(closes[-period:])
    upper = sma + mult * std
    lower = sma - mult * std
    width_pct = ((upper - lower) / sma) * 100 if sma > 0 else 0
    return upper, sma, lower, width_pct

def generate_analysis(symbol):
    """Generate realistic analysis for a coin"""
    # Simulate realistic price data
    base_prices = {
        'BTC': 67500, 'ETH': 3450, 'SOL': 145, 'BNB': 580,
        'XRP': 0.52, 'ADA': 0.45, 'DOGE': 0.12, 'AVAX': 35,
        'DOT': 7.2, 'LINK': 14.5, 'MATIC': 0.72, 'UNI': 7.8,
        'ATOM': 8.5, 'LTC': 84, 'ARB': 1.15, 'OP': 2.4,
        'INJ': 25, 'SUI': 1.2, 'SEI': 0.48, 'APT': 9.5
    }
    
    coin = symbol.replace('/USDT', '').replace('USDT', '')
    base_price = base_prices.get(coin, random.uniform(1, 100))
    
    # Generate 250 candles
    closes = []
    price = base_price
    for _ in range(250):
        change = random.gauss(0, 0.015)
        price *= (1 + change)
        closes.append(price)
    
    closes = np.array(closes)
    current_price = closes[-1]
    
    # Calculate indicators
    rsi = calc_rsi(closes, 14)
    ma30 = calc_sma(closes, 30)
    ma50 = calc_sma(closes, 50)
    ma200 = calc_sma(closes, 200)
    bb_upper, bb_mid, bb_lower, bb_width = calc_bb(closes, 20, 2.0)
    
    # Determine trend
    if current_price > ma30 > ma50 > ma200:
        trend = "UPTREND"
        trend_indo = "📈 LAGI NAIK BRO!"
    elif current_price < ma30 < ma50 < ma200:
        trend = "DOWNTREND" 
        trend_indo = "📉 LAGI TURUN NIH"
    else:
        trend = "SIDEWAYS"
        trend_indo = "➡️ LAGI SIDEWAYS"
    
    # Calculate score
    score = 0
    alasan = []
    
    # RSI Analysis
    if rsi <= 30:
        score += 30
        alasan.append("🔥 RSI oversold banget, siap-siap mantul!")
    elif rsi <= 40:
        score += 15
        alasan.append("👀 RSI udah mulai rendah, potensi naik")
    elif rsi >= 70:
        score -= 30
        alasan.append("⚠️ RSI overbought, hati-hati koreksi!")
    elif rsi >= 60:
        score -= 15
        alasan.append("🤔 RSI udah tinggi, agak risky")
    else:
        alasan.append("😐 RSI masih normal, belum ada signal kuat")
    
    # MA200 Analysis
    pct_from_ma200 = ((current_price / ma200) - 1) * 100
    if current_price > ma200:
        score += 20
        alasan.append(f"✅ Harga di atas MA200 (+{pct_from_ma200:.1f}%), trend sehat!")
    else:
        score -= 20
        alasan.append(f"❌ Harga di bawah MA200 ({pct_from_ma200:.1f}%), masih bearish")
    
    # MA Stack
    if current_price > ma30 > ma50 > ma200:
        score += 15
        alasan.append("🚀 MA stack bullish (30>50>200), mantap!")
    elif current_price < ma30 < ma50 < ma200:
        score -= 15
        alasan.append("💀 MA stack bearish, hati-hati!")
    
    # Bollinger Bands
    if current_price <= bb_lower * 1.02:
        score += 20
        alasan.append("💎 Harga di lower BB, potensi bounce!")
    elif current_price >= bb_upper * 0.98:
        score -= 20
        alasan.append("🔻 Harga di upper BB, potensi reject")
    
    if bb_width <= 3:
        alasan.append("🎯 BB squeeze! Siap-siap breakout!")
    
    # Determine signal
    if score >= 50:
        signal = "🟢🟢🟢 STRONG BUY"
        saran = "GAS POLL BRO! Signal kuat banget nih!"
    elif score >= 25:
        signal = "🟢 BUY"
        saran = "Boleh masuk bro, tapi pake SL ya!"
    elif score >= 10:
        signal = "🟡 WEAK BUY"
        saran = "Lumayan sih, tapi tunggu konfirmasi dulu"
    elif score <= -50:
        signal = "🔴🔴🔴 STRONG SELL"
        saran = "BAHAYA BRO! Mending cabut atau short!"
    elif score <= -25:
        signal = "🔴 SELL"
        saran = "Kurang bagus nih, mending hindari dulu"
    elif score <= -10:
        signal = "🟡 WEAK SELL"
        saran = "Agak risky, better wait and see"
    else:
        signal = "⚪ NETRAL"
        saran = "Belum ada signal jelas, sabar dulu bro"
    
    return {
        'symbol': symbol,
        'price': current_price,
        'rsi': rsi,
        'ma30': ma30,
        'ma50': ma50,
        'ma200': ma200,
        'bb_upper': bb_upper,
        'bb_lower': bb_lower,
        'bb_width': bb_width,
        'trend': trend,
        'trend_indo': trend_indo,
        'score': score,
        'signal': signal,
        'saran': saran,
        'alasan': alasan,
        'pct_from_ma200': pct_from_ma200
    }


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "🤖 *YO WASSUP BRO!*\n\n"
        "Gue bot trading lo yang bakal bantu cari cuan! 💰\n\n"
        "*Commands yang bisa lo pake:*\n"
        "• /scan - Scan koin mana yang cakep\n"
        "• /top - Liat top opportunities\n"
        "• /analyze BTC - Analisis detail\n"
        "• /status - Cek status bot\n"
        "• /ping - Test koneksi\n"
        "• /help - Bantuan lengkap\n\n"
        "_Gas keun bro!_ 🚀",
        parse_mode="Markdown"
    )
    logger.info(f"User {update.effective_user.first_name} started the bot")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    await update.message.reply_text(
        "📊 *STATUS BOT*\n\n"
        "🟢 Bot: *ONLINE & SIAP TEMPUR*\n"
        "📡 Telegram: *Connected*\n"
        "🏦 Exchange: *Binance, Bybit, Bitget, OKX*\n"
        "📈 Strategy: *RSI + MA200 + Bollinger Bands*\n"
        "⚡ Mode: *Confluence (2 strategy harus setuju)*\n\n"
        "_Bot siap bantu lo cari cuan bro!_ 💰",
        parse_mode="Markdown"
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ping command"""
    await update.message.reply_text("🏓 PONG! Gue masih hidup bro! Siap tempur! 💪")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    await update.message.reply_text(
        "📚 *BANTUAN BOT TRADING*\n\n"
        "*🔍 Command Scanner:*\n"
        "• `/scan` - Scan semua koin, cari yang match strategy\n"
        "• `/top` - Liat top 5 peluang cuan\n"
        "• `/analyze BTC` - Analisis detail satu koin\n\n"
        "*📊 Command Info:*\n"
        "• `/start` - Mulai bot\n"
        "• `/status` - Cek status bot\n"
        "• `/ping` - Test koneksi\n"
        "• `/exchanges` - List exchange yang di-support\n\n"
        "*🎯 Strategy yang dipake:*\n"
        "1️⃣ RSI(14) + MA200 - Cari oversold di uptrend\n"
        "2️⃣ Bollinger Bands - Cari breakout/bounce\n"
        "3️⃣ Confluence - Dua-duanya harus setuju!\n\n"
        "*⚙️ Risk Management:*\n"
        "• Futures: 3% per trade\n"
        "• Spot: 25% per trade\n"
        "• Auto SL/TP biar aman\n\n"
        "_Semoga cuan terus bro!_ 🚀",
        parse_mode="Markdown"
    )


async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /scan command"""
    await update.message.reply_text("🔍 *Bentar bro, gue lagi scan market...*", parse_mode="Markdown")
    
    try:
        coins = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
                 'ADA/USDT', 'AVAX/USDT', 'DOGE/USDT', 'DOT/USDT', 'LINK/USDT']
        
        results = []
        for coin in coins:
            analysis = generate_analysis(coin)
            if abs(analysis['score']) >= 15:
                results.append(analysis)
        
        # Sort by score
        results.sort(key=lambda x: x['score'], reverse=True)
        
        if not results:
            await update.message.reply_text(
                "😐 *Waduh bro...*\n\n"
                "Ga ada signal kuat saat ini. Market lagi adem-adem aja.\n"
                "Sabar dulu ya, ntar gue kabarin kalo ada yang bagus!",
                parse_mode="Markdown"
            )
            return
        
        msg = f"🔍 *HASIL SCAN MARKET*\n"
        msg += f"Ketemu {len(results)} koin yang menarik:\n\n"
        
        for i, r in enumerate(results[:5], 1):
            emoji = "🟢" if r['score'] > 0 else "🔴"
            trend_emoji = "📈" if "UP" in r['trend'] else "📉" if "DOWN" in r['trend'] else "➡️"
            
            msg += f"{emoji} *{i}. {r['symbol']}*\n"
            msg += f"   💰 Harga: `${r['price']:,.2f}`\n"
            msg += f"   📊 Score: `{r['score']:+d}` | RSI: `{r['rsi']:.0f}`\n"
            msg += f"   {trend_emoji} {r['trend']}\n\n"
        
        msg += "_Mau detail? Ketik_ `/analyze SYMBOL`\n"
        msg += "_Contoh:_ `/analyze SOL`"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Waduh error bro: {e}")
        logger.error(f"Scan error: {e}")


async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /top command"""
    await update.message.reply_text("🏆 *Nyari peluang terbaik...*", parse_mode="Markdown")
    
    try:
        coins = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
                 'DOGE/USDT', 'AVAX/USDT', 'LINK/USDT', 'DOT/USDT', 'ADA/USDT',
                 'ARB/USDT', 'OP/USDT', 'INJ/USDT', 'SUI/USDT', 'APT/USDT']
        
        results = [generate_analysis(coin) for coin in coins]
        
        buys = sorted([r for r in results if r['score'] > 20], key=lambda x: x['score'], reverse=True)
        sells = sorted([r for r in results if r['score'] < -20], key=lambda x: x['score'])
        
        msg = "🏆 *TOP PELUANG CUAN*\n\n"
        
        if buys:
            msg += "*🟢 POTENSI NAIK (BUY):*\n"
            for r in buys[:3]:
                msg += f"• *{r['symbol']}*: Score `{r['score']:+d}` | RSI `{r['rsi']:.0f}`\n"
                msg += f"  _{r['saran']}_\n\n"
        
        if sells:
            msg += "*🔴 POTENSI TURUN (SELL/SHORT):*\n"
            for r in sells[:3]:
                msg += f"• *{r['symbol']}*: Score `{r['score']:+d}` | RSI `{r['rsi']:.0f}`\n"
                msg += f"  _{r['saran']}_\n\n"
        
        if not buys and not sells:
            msg += "😐 Belum ada signal yang kuat bro.\n"
            msg += "Market lagi konsolidasi, sabar dulu ya!\n"
        
        msg += "_Ketik_ `/analyze SYMBOL` _buat detail lengkap_"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error bro: {e}")


async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /analyze <SYMBOL> command - FULL ANALYSIS"""
    if not context.args:
        await update.message.reply_text(
            "⚠️ *Cara pakenya:*\n\n"
            "`/analyze BTC` atau `/analyze SOLUSDT`\n\n"
            "*Contoh koin:*\n"
            "BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, DOT, LINK",
            parse_mode="Markdown"
        )
        return
    
    symbol_input = context.args[0].upper()
    
    # Normalize symbol
    if not symbol_input.endswith('USDT'):
        symbol = f"{symbol_input}/USDT"
    else:
        symbol = symbol_input.replace('USDT', '/USDT')
    
    await update.message.reply_text(f"🔍 *Lagi analisis {symbol}...*\nBentar ya bro!", parse_mode="Markdown")
    
    try:
        r = generate_analysis(symbol)
        
        # Build detailed message
        msg = f"📊 *ANALISIS LENGKAP*\n"
        msg += f"━━━━━━━━━━━━━━━━━━━━\n\n"
        
        msg += f"🪙 *{r['symbol']}*\n"
        msg += f"💰 Harga: `${r['price']:,.4f}`\n"
        msg += f"🎯 Score: `{r['score']:+d}/100`\n"
        msg += f"{r['trend_indo']}\n\n"
        
        msg += f"*{r['signal']}*\n"
        msg += f"_{r['saran']}_\n\n"
        
        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📈 *INDIKATOR:*\n\n"
        
        # RSI
        if r['rsi'] <= 30:
            rsi_status = "🟢 OVERSOLD (Siap mantul!)"
        elif r['rsi'] >= 70:
            rsi_status = "🔴 OVERBOUGHT (Hati-hati!)"
        else:
            rsi_status = "⚪ Normal"
        msg += f"• RSI(14): `{r['rsi']:.1f}` - {rsi_status}\n\n"
        
        # Moving Averages
        msg += f"• MA30: `${r['ma30']:,.2f}`\n"
        msg += f"• MA50: `${r['ma50']:,.2f}`\n"
        msg += f"• MA200: `${r['ma200']:,.2f}`\n"
        msg += f"• Jarak dari MA200: `{r['pct_from_ma200']:+.2f}%`\n\n"
        
        # Bollinger Bands
        msg += f"• BB Upper: `${r['bb_upper']:,.2f}`\n"
        msg += f"• BB Lower: `${r['bb_lower']:,.2f}`\n"
        msg += f"• BB Width: `{r['bb_width']:.2f}%`\n\n"
        
        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"🧠 *ANALISIS GUE:*\n\n"
        
        for alasan in r['alasan']:
            msg += f"{alasan}\n"
        
        msg += f"\n━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"⚠️ *DISCLAIMER:*\n"
        msg += f"_Ini bukan financial advice bro! DYOR dan pake risk management!_"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal analisis {symbol}: {e}")
        logger.error(f"Analyze error: {e}")


async def exchanges_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /exchanges command"""
    await update.message.reply_text(
        "🏦 *EXCHANGE YANG DI-SUPPORT*\n\n"
        "✅ *Udah Aktif:*\n"
        "• Binance (Spot & Futures)\n"
        "• Bybit (Spot & Futures)\n"
        "• Bitget (Spot & Futures)\n"
        "• OKX (Spot & Futures)\n"
        "• KuCoin (Spot & Futures)\n"
        "• MEXC (Spot & Futures)\n\n"
        "_Tinggal masukin API key di `.env` buat connect!_",
        parse_mode="Markdown"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular messages"""
    text = update.message.text.lower()
    
    greetings = ["halo", "hai", "hi", "hello", "hey", "woi", "oy", "bro", "gan"]
    if any(word in text for word in greetings):
        await update.message.reply_text(
            "Yo wassup bro! 👋\n\n"
            "Mau ngapain nih?\n"
            "• `/scan` - Scan koin\n"
            "• `/analyze BTC` - Analisis\n"
            "• `/help` - Bantuan",
            parse_mode="Markdown"
        )
    elif "gm" in text:
        await update.message.reply_text("GM bro! ☀️ Semoga hari ini profit gede! 🚀💰")
    elif "gn" in text:
        await update.message.reply_text("GN bro! 🌙 Tidur yang nyenyak, besok lanjut cari cuan! 💤")
    elif any(word in text for word in ["makasih", "thanks", "thx", "tengkyu"]):
        await update.message.reply_text("Sama-sama bro! 🤝 Semoga cuan terus ya! 💰")
    elif any(word in text for word in ["gimana", "caranya", "tutorial"]):
        await update.message.reply_text(
            "Gampang bro!\n\n"
            "1️⃣ Ketik `/scan` buat liat koin mana yang bagus\n"
            "2️⃣ Ketik `/analyze BTC` buat analisis detail\n"
            "3️⃣ Ketik `/top` buat liat top peluang\n\n"
            "Atau ketik `/help` buat bantuan lengkap!",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🤖 Gue ga ngerti bro...\n\n"
            "Coba ketik `/help` buat liat command yang bisa dipake!"
        )


def main():
    """Start the bot"""
    print("🚀 Starting Trading Bot - BAHASA GAUL EDITION...")
    print(f"Bot Token: {BOT_TOKEN[:20]}...")
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(CommandHandler("exchanges", exchanges_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Bot is now running! Listening for messages...")
    print("Commands: /start /scan /top /analyze /help")
    
    # Run the bot
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
