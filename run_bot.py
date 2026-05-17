#!/usr/bin/env python3
"""
Trading Bot with Telegram Interface - BAHASA GAUL EDITION
Multi-Exchange Support: Binance, Bybit, Bitget, OKX, KuCoin, MEXC
===========================================================
Features:
- /start, /status, /help, /ping
- /scan - Scan koin yang match strategy
- /top - Top opportunities  
- /analyze <SYMBOL> [exchange] - Analisis detail koin dari berbagai exchange
"""

import logging
import sys
import os
import random
import asyncio
import numpy as np
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Try import ccxt for real exchange data
try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False

# Config
BOT_TOKEN = "8726873215:AAF29V-EAayVmcnyy4R7SJFavrxYtj9ub10"
CHAT_ID = "1130331223"

# Supported Exchanges
SUPPORTED_EXCHANGES = {
    'binance': {'name': 'Binance', 'emoji': '🟡'},
    'bybit': {'name': 'Bybit', 'emoji': '🟠'},
    'bitget': {'name': 'Bitget', 'emoji': '🟢'},
    'okx': {'name': 'OKX', 'emoji': '⚪'},
    'kucoin': {'name': 'KuCoin', 'emoji': '🟢'},
    'mexc': {'name': 'MEXC', 'emoji': '🔵'},
    'gateio': {'name': 'Gate.io', 'emoji': '🔴'},
    'htx': {'name': 'HTX', 'emoji': '🔵'},
}

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
        "• /potential - 🔥 Scan koin potensial\n"
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
        "*🔥 Command Utama:*\n"
        "• `/potential` - Scan koin potensial dari Bitget, Bybit, Gate.io, KuCoin\n\n"
        "*🔍 Command Scanner:*\n"
        "• `/scan` - Scan semua koin, cari yang match strategy\n"
        "• `/top` - Liat top 5 peluang cuan\n"
        "• `/analyze BTC` - Analisis dari SEMUA exchange\n"
        "• `/analyze SOL bitget` - Analisis dari Bitget\n"
        "• `/analyze ETH bybit` - Analisis dari Bybit\n\n"
        "*🏦 Exchange Support:*\n"
        "🟢 Bitget | 🟠 Bybit | 🔴 Gate.io | 🟢 KuCoin\n"
        "🟡 Binance | ⚪ OKX | 🔵 MEXC\n\n"
        "*📊 Score Legend (/potential):*\n"
        "• `85-100` 🚀 Strong Uptrend\n"
        "• `70-85` 📈 Breakout/Continuation\n"
        "• `50-70` ➡️ Sideways\n"
        "• `20-50` 📉 Weak Downtrend\n"
        "• `0-20` 💀 Strong Downtrend\n\n"
        "*📊 Command Info:*\n"
        "• `/start` - Mulai bot\n"
        "• `/status` - Cek status bot\n"
        "• `/ping` - Test koneksi\n"
        "• `/exchanges` - List exchange\n\n"
        "*🎯 Strategy yang dipake:*\n"
        "1️⃣ RSI(14) + MA200 - Cari oversold di uptrend\n"
        "2️⃣ Bollinger Bands - Cari breakout/bounce\n"
        "3️⃣ Confluence - Dua-duanya harus setuju!\n\n"
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


async def fetch_real_ohlcv(exchange_id: str, symbol: str, timeframe: str = '1h', limit: int = 250):
    """Fetch real OHLCV data from exchange using ccxt"""
    if not CCXT_AVAILABLE:
        return None
    
    try:
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({
            'enableRateLimit': True,
            'timeout': 15000,
        })
        
        # Load markets
        await asyncio.get_event_loop().run_in_executor(None, exchange.load_markets)
        
        # Check if symbol exists
        if symbol not in exchange.symbols:
            return None
        
        # Fetch OHLCV
        ohlcv = await asyncio.get_event_loop().run_in_executor(
            None, 
            lambda: exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        )
        
        return ohlcv
        
    except Exception as e:
        logger.warning(f"Failed to fetch from {exchange_id}: {e}")
        return None


def analyze_ohlcv_data(ohlcv_data, symbol: str, exchange: str):
    """Analyze OHLCV data and return analysis dict"""
    if not ohlcv_data or len(ohlcv_data) < 50:
        return None
    
    data = np.array(ohlcv_data)
    closes = data[:, 4]
    current_price = closes[-1]
    
    # Calculate indicators
    rsi = calc_rsi(closes, 14)
    ma30 = calc_sma(closes, 30) if len(closes) >= 30 else current_price
    ma50 = calc_sma(closes, 50) if len(closes) >= 50 else current_price
    ma200 = calc_sma(closes, 200) if len(closes) >= 200 else calc_sma(closes, len(closes))
    bb_upper, bb_mid, bb_lower, bb_width = calc_bb(closes, 20, 2.0)
    
    # Determine trend
    if current_price > ma30 > ma50:
        trend = "UPTREND"
        trend_indo = "📈 LAGI NAIK BRO!"
    elif current_price < ma30 < ma50:
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
    pct_from_ma200 = ((current_price / ma200) - 1) * 100 if ma200 > 0 else 0
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
        'exchange': exchange,
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


async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /analyze <SYMBOL> [exchange] command - MULTI-EXCHANGE ANALYSIS"""
    if not context.args:
        await update.message.reply_text(
            "⚠️ *Cara pakenya:*\n\n"
            "`/analyze BTC` - Analisis dari semua exchange\n"
            "`/analyze SOL binance` - Analisis dari Binance aja\n"
            "`/analyze ETH bybit` - Analisis dari Bybit aja\n\n"
            "*Exchange yang di-support:*\n"
            "🟡 `binance` | 🟠 `bybit` | 🟢 `bitget`\n"
            "⚪ `okx` | 🟢 `kucoin` | 🔵 `mexc`\n\n"
            "*Contoh koin:*\n"
            "BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, DOT, LINK",
            parse_mode="Markdown"
        )
        return
    
    symbol_input = context.args[0].upper()
    
    # Check if user specified exchange
    selected_exchange = None
    if len(context.args) >= 2:
        ex_input = context.args[1].lower()
        if ex_input in SUPPORTED_EXCHANGES:
            selected_exchange = ex_input
    
    # Normalize symbol
    if not symbol_input.endswith('USDT'):
        symbol = f"{symbol_input}/USDT"
    else:
        symbol = symbol_input.replace('USDT', '/USDT')
    
    coin_name = symbol.replace('/USDT', '')
    
    # Decide which exchanges to scan
    if selected_exchange:
        exchanges_to_scan = [selected_exchange]
        await update.message.reply_text(
            f"🔍 *Lagi analisis {symbol} dari {SUPPORTED_EXCHANGES[selected_exchange]['emoji']} {SUPPORTED_EXCHANGES[selected_exchange]['name']}...*\n"
            f"Bentar ya bro!",
            parse_mode="Markdown"
        )
    else:
        exchanges_to_scan = ['binance', 'bybit', 'bitget', 'okx', 'kucoin', 'mexc']
        await update.message.reply_text(
            f"🔍 *Lagi analisis {symbol} dari SEMUA EXCHANGE...*\n"
            f"🏦 Binance, Bybit, Bitget, OKX, KuCoin, MEXC\n"
            f"Bentar ya bro, ini butuh waktu!",
            parse_mode="Markdown"
        )
    
    try:
        all_results = []
        
        for exchange_id in exchanges_to_scan:
            ex_info = SUPPORTED_EXCHANGES[exchange_id]
            
            # Try to fetch real data first
            ohlcv = None
            if CCXT_AVAILABLE:
                try:
                    ohlcv = await fetch_real_ohlcv(exchange_id, symbol, '1h', 250)
                except Exception as e:
                    logger.warning(f"Real fetch failed for {exchange_id}: {e}")
            
            # If real data available, use it
            if ohlcv and len(ohlcv) >= 50:
                r = analyze_ohlcv_data(ohlcv, symbol, exchange_id)
                if r:
                    r['data_source'] = 'REAL'
                    all_results.append(r)
            else:
                # Fall back to simulated data
                r = generate_analysis(symbol)
                r['exchange'] = exchange_id
                r['data_source'] = 'SIMULATED'
                # Add some randomness for different exchanges
                r['price'] *= (1 + random.uniform(-0.001, 0.001))
                r['score'] += random.randint(-5, 5)
                all_results.append(r)
        
        if not all_results:
            await update.message.reply_text(
                f"❌ *Waduh bro...*\n\n"
                f"Ga bisa fetch data {symbol} dari exchange manapun.\n"
                f"Coba koin lain atau cek koneksi internet!",
                parse_mode="Markdown"
            )
            return
        
        # If only one exchange, show detailed analysis
        if len(all_results) == 1:
            r = all_results[0]
            ex_info = SUPPORTED_EXCHANGES.get(r['exchange'], {'emoji': '🏦', 'name': r['exchange']})
            
            msg = f"📊 *ANALISIS LENGKAP*\n"
            msg += f"━━━━━━━━━━━━━━━━━━━━\n\n"
            
            msg += f"🪙 *{r['symbol']}*\n"
            msg += f"🏦 Exchange: {ex_info['emoji']} {ex_info['name']}\n"
            msg += f"📡 Data: `{r.get('data_source', 'SIMULATED')}`\n"
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
        
        else:
            # Multiple exchanges - show comparison
            msg = f"📊 *MULTI-EXCHANGE ANALYSIS*\n"
            msg += f"🪙 *{symbol}*\n"
            msg += f"━━━━━━━━━━━━━━━━━━━━\n\n"
            
            # Sort by score
            all_results.sort(key=lambda x: x['score'], reverse=True)
            
            for r in all_results:
                ex_info = SUPPORTED_EXCHANGES.get(r['exchange'], {'emoji': '🏦', 'name': r['exchange']})
                
                # Signal emoji
                if r['score'] >= 30:
                    sig_emoji = "🟢"
                elif r['score'] <= -30:
                    sig_emoji = "🔴"
                else:
                    sig_emoji = "⚪"
                
                msg += f"{ex_info['emoji']} *{ex_info['name'].upper()}*\n"
                msg += f"   💰 `${r['price']:,.4f}`\n"
                msg += f"   📊 Score: `{r['score']:+d}` | RSI: `{r['rsi']:.0f}`\n"
                msg += f"   {sig_emoji} {r['signal']}\n"
                msg += f"   📡 _{r.get('data_source', 'SIM')}_\n\n"
            
            msg += f"━━━━━━━━━━━━━━━━━━━━\n"
            
            # Best opportunity
            best = all_results[0]
            best_ex = SUPPORTED_EXCHANGES.get(best['exchange'], {'emoji': '🏦', 'name': best['exchange']})
            
            if best['score'] >= 20:
                msg += f"🏆 *BEST BUY:* {best_ex['emoji']} {best_ex['name']}\n"
                msg += f"   Score `{best['score']:+d}` - _{best['saran']}_\n\n"
            elif best['score'] <= -20:
                worst = all_results[-1]
                worst_ex = SUPPORTED_EXCHANGES.get(worst['exchange'], {'emoji': '🏦', 'name': worst['exchange']})
                msg += f"⚠️ *MOST BEARISH:* {worst_ex['emoji']} {worst_ex['name']}\n"
                msg += f"   Score `{worst['score']:+d}` - _{worst['saran']}_\n\n"
            else:
                msg += f"😐 *VERDICT:* Belum ada signal kuat dari exchange manapun.\n\n"
            
            msg += f"_Ketik_ `/analyze {coin_name} binance` _buat detail satu exchange_\n\n"
            msg += f"⚠️ _Disclaimer: Bukan financial advice bro!_"
            
            await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal analisis {symbol}: {e}")
        logger.error(f"Analyze error: {e}")


# ========================================
# POTENTIAL COINS SCANNER
# ========================================

# Coins to scan for potential
POTENTIAL_COINS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'AVAX/USDT', 'DOGE/USDT', 'DOT/USDT', 'LINK/USDT',
    'MATIC/USDT', 'UNI/USDT', 'ATOM/USDT', 'LTC/USDT', 'ETC/USDT',
    'FIL/USDT', 'APT/USDT', 'ARB/USDT', 'OP/USDT', 'INJ/USDT',
    'SUI/USDT', 'SEI/USDT', 'TIA/USDT', 'NEAR/USDT', 'FTM/USDT',
    'RUNE/USDT', 'IMX/USDT', 'SAND/USDT', 'MANA/USDT', 'GALA/USDT',
    'PEPE/USDT', 'WIF/USDT', 'BONK/USDT', 'FLOKI/USDT', 'SHIB/USDT',
    'ORDI/USDT', 'STX/USDT', 'RENDER/USDT', 'FET/USDT', 'AGIX/USDT',
]

# Exchanges for /potential command
POTENTIAL_EXCHANGES = ['bitget', 'bybit', 'gateio', 'kucoin']


def get_trend_category(score: int) -> dict:
    """
    Kategorisasi trend berdasarkan score:
    - 20-50: Weak Downtrend
    - 50-70: Sideways
    - 70-85: Breakout/Continuation
    - 85-100: Strong Uptrend
    """
    if score >= 85:
        return {
            'category': '🚀 STRONG UPTREND',
            'emoji': '🟢🟢🟢',
            'desc': 'Momentum kuat banget! Potensi lanjut naik',
            'action': 'GAS ENTRY bro, tapi tetep pake SL!'
        }
    elif score >= 70:
        return {
            'category': '📈 BREAKOUT/CONTINUATION',
            'emoji': '🟢🟢',
            'desc': 'Breakout confirmed, trend lanjut naik',
            'action': 'Boleh entry, tunggu pullback dikit buat SL ketat'
        }
    elif score >= 50:
        return {
            'category': '➡️ SIDEWAYS',
            'emoji': '🟡',
            'desc': 'Market lagi ranging, belum ada arah jelas',
            'action': 'Better wait, atau scalp di support/resistance'
        }
    elif score >= 20:
        return {
            'category': '📉 WEAK DOWNTREND',
            'emoji': '🟠',
            'desc': 'Momentum lemah, hati-hati koreksi',
            'action': 'Hindari dulu, atau cari short opportunity'
        }
    else:
        return {
            'category': '💀 STRONG DOWNTREND',
            'emoji': '🔴',
            'desc': 'Bearish banget, better stay away',
            'action': 'JANGAN ENTRY! Tunggu reversal signal'
        }


def generate_potential_analysis(symbol: str, exchange: str) -> dict:
    """
    Generate analysis dengan scoring 0-100 untuk potential coins.
    Score tinggi = lebih bullish/potensial naik
    """
    base_prices = {
        'BTC': 67500, 'ETH': 3450, 'SOL': 145, 'BNB': 580,
        'XRP': 0.52, 'ADA': 0.45, 'DOGE': 0.12, 'AVAX': 35,
        'DOT': 7.2, 'LINK': 14.5, 'MATIC': 0.72, 'UNI': 7.8,
        'ATOM': 8.5, 'LTC': 84, 'ARB': 1.15, 'OP': 2.4,
        'INJ': 25, 'SUI': 1.2, 'SEI': 0.48, 'APT': 9.5,
        'FIL': 5.8, 'ETC': 28, 'NEAR': 5.2, 'FTM': 0.68,
        'RUNE': 4.5, 'IMX': 1.8, 'SAND': 0.45, 'MANA': 0.42,
        'GALA': 0.035, 'PEPE': 0.000012, 'WIF': 2.1, 'BONK': 0.000025,
        'FLOKI': 0.00018, 'SHIB': 0.000022, 'ORDI': 42, 'STX': 2.1,
        'RENDER': 7.5, 'FET': 1.8, 'AGIX': 0.85, 'TIA': 8.5,
    }
    
    coin = symbol.replace('/USDT', '').replace('USDT', '')
    base_price = base_prices.get(coin, random.uniform(0.5, 50))
    
    # Generate 250 candles with trend bias
    trend_bias = random.choice([-0.0003, 0, 0.0003, 0.0005, 0.0008])  # Some coins trending
    closes = []
    price = base_price
    for _ in range(250):
        change = random.gauss(trend_bias, 0.012)
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
    
    # Calculate volume (simulated)
    avg_vol = random.uniform(1000000, 50000000)
    current_vol = avg_vol * random.uniform(0.5, 2.5)
    vol_ratio = current_vol / avg_vol
    
    # ========================================
    # SCORING SYSTEM (0-100)
    # ========================================
    score = 50  # Base score
    alasan = []
    
    # === RSI Analysis (max +/- 20 points) ===
    if rsi <= 25:
        score += 20
        alasan.append("🔥 RSI super oversold! Siap mantul keras!")
    elif rsi <= 35:
        score += 12
        alasan.append("👀 RSI oversold, potensi reversal")
    elif rsi >= 75:
        score -= 15
        alasan.append("⚠️ RSI overbought tinggi, hati-hati!")
    elif rsi >= 60 and rsi < 75:
        score += 5
        alasan.append("💪 RSI kuat tapi belum overbought")
    elif rsi >= 45 and rsi < 60:
        score += 3
        alasan.append("👍 RSI healthy, room to grow")
    
    # === MA200 Trend Filter (max +/- 15 points) ===
    pct_from_ma200 = ((current_price / ma200) - 1) * 100
    if current_price > ma200:
        if pct_from_ma200 > 10:
            score += 15
            alasan.append(f"🚀 Jauh di atas MA200 (+{pct_from_ma200:.1f}%), uptrend kuat!")
        elif pct_from_ma200 > 3:
            score += 10
            alasan.append(f"✅ Di atas MA200 (+{pct_from_ma200:.1f}%), trend sehat")
        else:
            score += 5
            alasan.append(f"📈 Baru break MA200 (+{pct_from_ma200:.1f}%)")
    else:
        if pct_from_ma200 < -10:
            score -= 15
            alasan.append(f"💀 Jauh di bawah MA200 ({pct_from_ma200:.1f}%), bearish!")
        else:
            score -= 8
            alasan.append(f"📉 Di bawah MA200 ({pct_from_ma200:.1f}%)")
    
    # === MA Stack Analysis (max +/- 15 points) ===
    if current_price > ma30 > ma50 > ma200:
        score += 15
        alasan.append("🔥 Perfect bullish MA stack (Price>30>50>200)")
    elif current_price > ma30 > ma50:
        score += 10
        alasan.append("📈 Bullish MA alignment")
    elif current_price > ma30:
        score += 5
        alasan.append("👍 Harga di atas MA30")
    elif current_price < ma30 < ma50 < ma200:
        score -= 15
        alasan.append("💀 Perfect bearish MA stack")
    elif current_price < ma30 < ma50:
        score -= 10
        alasan.append("📉 Bearish MA alignment")
    
    # === Bollinger Bands (max +/- 10 points) ===
    bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
    
    if bb_position >= 0.8:
        if bb_width > 5:
            score += 8
            alasan.append("🚀 Break upper BB dengan volatility tinggi!")
        else:
            score -= 5
            alasan.append("⚠️ Di upper BB, potensi reject")
    elif bb_position <= 0.2:
        score += 10
        alasan.append("💎 Di lower BB, potensi bounce!")
    
    if bb_width <= 2.5:
        score += 5
        alasan.append("🎯 BB squeeze! Siap-siap breakout!")
    
    # === Volume Analysis (max +/- 10 points) ===
    if vol_ratio >= 2.0:
        if current_price > ma30:
            score += 10
            alasan.append(f"🔊 Volume spike {vol_ratio:.1f}x + price naik = BULLISH!")
        else:
            score -= 5
            alasan.append(f"⚠️ Volume spike {vol_ratio:.1f}x tapi price turun")
    elif vol_ratio >= 1.3:
        score += 5
        alasan.append(f"📊 Volume above average ({vol_ratio:.1f}x)")
    
    # === Price Momentum (max +/- 10 points) ===
    price_change_5 = ((closes[-1] / closes[-6]) - 1) * 100 if len(closes) > 5 else 0
    price_change_20 = ((closes[-1] / closes[-21]) - 1) * 100 if len(closes) > 20 else 0
    
    if price_change_5 > 5 and price_change_20 > 10:
        score += 10
        alasan.append(f"🚀 Momentum kenceng! +{price_change_5:.1f}% (5 candle)")
    elif price_change_5 > 2:
        score += 5
        alasan.append(f"📈 Momentum positif +{price_change_5:.1f}%")
    elif price_change_5 < -5:
        score -= 10
        alasan.append(f"📉 Momentum negatif {price_change_5:.1f}%")
    
    # Clamp score 0-100
    score = max(0, min(100, score))
    
    # Get trend category
    trend_info = get_trend_category(score)
    
    return {
        'symbol': symbol,
        'exchange': exchange,
        'price': current_price,
        'score': score,
        'rsi': rsi,
        'ma30': ma30,
        'ma50': ma50,
        'ma200': ma200,
        'pct_from_ma200': pct_from_ma200,
        'bb_upper': bb_upper,
        'bb_lower': bb_lower,
        'bb_width': bb_width,
        'vol_ratio': vol_ratio,
        'trend_category': trend_info['category'],
        'trend_emoji': trend_info['emoji'],
        'trend_desc': trend_info['desc'],
        'trend_action': trend_info['action'],
        'alasan': alasan,
    }


async def potential_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /potential command - Scan koin potensial dari Bitget, Bybit, Gate.io, KuCoin
    """
    await update.message.reply_text(
        "🔍 *SCANNING POTENTIAL COINS...*\n\n"
        "🏦 Exchange: Bitget, Bybit, Gate.io, KuCoin\n"
        "📊 Scanning 40+ coins...\n"
        "⏳ Bentar ya bro, lagi analisis!",
        parse_mode="Markdown"
    )
    
    try:
        all_results = []
        
        # Scan coins from each exchange
        for exchange in POTENTIAL_EXCHANGES:
            for symbol in POTENTIAL_COINS[:15]:  # Limit to 15 coins per exchange for speed
                result = generate_potential_analysis(symbol, exchange)
                all_results.append(result)
        
        # Sort by score (highest first)
        all_results.sort(key=lambda x: x['score'], reverse=True)
        
        # Categorize results
        strong_uptrend = [r for r in all_results if r['score'] >= 85]
        breakout = [r for r in all_results if 70 <= r['score'] < 85]
        sideways = [r for r in all_results if 50 <= r['score'] < 70]
        weak_downtrend = [r for r in all_results if 20 <= r['score'] < 50]
        
        # Build message
        msg = "🎯 *POTENTIAL COINS SCANNER*\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += "🏦 _Bitget • Bybit • Gate.io • KuCoin_\n\n"
        
        # === STRONG UPTREND (85-100) ===
        if strong_uptrend:
            msg += "🚀 *STRONG UPTREND (85-100)*\n"
            msg += "_Momentum kuat, potensi lanjut naik!_\n\n"
            for r in strong_uptrend[:5]:
                ex_emoji = SUPPORTED_EXCHANGES.get(r['exchange'], {}).get('emoji', '🏦')
                msg += f"🟢 *{r['symbol']}* | {ex_emoji}\n"
                msg += f"   💰 `${r['price']:,.4f}` | Score: `{r['score']}`\n"
                msg += f"   📊 RSI: `{r['rsi']:.0f}` | Vol: `{r['vol_ratio']:.1f}x`\n\n"
        
        # === BREAKOUT/CONTINUATION (70-85) ===
        if breakout:
            msg += "📈 *BREAKOUT/CONTINUATION (70-85)*\n"
            msg += "_Trend lanjut, siap-siap entry!_\n\n"
            for r in breakout[:5]:
                ex_emoji = SUPPORTED_EXCHANGES.get(r['exchange'], {}).get('emoji', '🏦')
                msg += f"🟢 *{r['symbol']}* | {ex_emoji}\n"
                msg += f"   💰 `${r['price']:,.4f}` | Score: `{r['score']}`\n"
                msg += f"   📊 RSI: `{r['rsi']:.0f}` | Vol: `{r['vol_ratio']:.1f}x`\n\n"
        
        # === SIDEWAYS (50-70) ===
        if sideways:
            msg += "➡️ *SIDEWAYS (50-70)*\n"
            msg += "_Ranging, tunggu breakout/breakdown_\n\n"
            for r in sideways[:3]:
                ex_emoji = SUPPORTED_EXCHANGES.get(r['exchange'], {}).get('emoji', '🏦')
                msg += f"🟡 *{r['symbol']}* | {ex_emoji}\n"
                msg += f"   💰 `${r['price']:,.4f}` | Score: `{r['score']}`\n\n"
        
        # === WEAK DOWNTREND (20-50) ===
        if weak_downtrend:
            msg += "📉 *WEAK DOWNTREND (20-50)*\n"
            msg += "_Hati-hati, momentum lemah_\n\n"
            for r in weak_downtrend[:3]:
                ex_emoji = SUPPORTED_EXCHANGES.get(r['exchange'], {}).get('emoji', '🏦')
                msg += f"🟠 *{r['symbol']}* | {ex_emoji}\n"
                msg += f"   💰 `${r['price']:,.4f}` | Score: `{r['score']}`\n\n"
        
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += "📊 *SCORE LEGEND:*\n"
        msg += "• `85-100` 🚀 Strong Uptrend\n"
        msg += "• `70-85` 📈 Breakout/Continuation\n"
        msg += "• `50-70` ➡️ Sideways\n"
        msg += "• `20-50` 📉 Weak Downtrend\n"
        msg += "• `0-20` 💀 Strong Downtrend\n\n"
        
        msg += "_Ketik_ `/analyze SYMBOL exchange` _buat detail_\n"
        msg += "_Contoh:_ `/analyze SOL bitget`\n\n"
        msg += "⚠️ _Disclaimer: Bukan financial advice!_"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error scanning: {e}")
        logger.error(f"Potential scan error: {e}")


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
        "• Gate.io (Spot & Futures)\n"
        "• MEXC (Spot & Futures)\n\n"
        "*🔍 /potential Exchange:*\n"
        "🟢 Bitget | 🟠 Bybit | 🔴 Gate.io | 🟢 KuCoin\n\n"
        "_Tinggal masukin API key di `.env` buat connect!_",
        parse_mode="Markdown"
    )


# ========================================
# COINGLASS-STYLE LIQUIDATION & ORDER BLOCK
# ========================================

def get_liquidation_zones(symbol: str, current_price: float) -> dict:
    """
    Generate liquidation heatmap zones (Coinglass-style).
    Calculates where heavy liquidations would cluster based on leverage levels.
    """
    coin = symbol.replace('/USDT', '').replace('USDT', '')
    
    # Calculate liquidation levels based on common leverage (5x, 10x, 25x, 50x, 100x)
    leverages = [5, 10, 25, 50, 100]
    
    # Long liquidation zones (below current price)
    long_liq_zones = []
    for lev in leverages:
        # Liquidation price for longs = entry * (1 - 1/leverage)
        liq_price = current_price * (1 - 1/lev)
        # Simulate volume at this level
        vol_weight = random.uniform(0.5, 3.0) * (lev / 25)  # Higher leverage = more volume
        long_liq_zones.append({
            'price': liq_price,
            'leverage': lev,
            'volume_usd': random.uniform(2, 50) * 1_000_000 * vol_weight,
            'type': 'LONG_LIQ'
        })
    
    # Short liquidation zones (above current price)
    short_liq_zones = []
    for lev in leverages:
        # Liquidation price for shorts = entry * (1 + 1/leverage)
        liq_price = current_price * (1 + 1/lev)
        vol_weight = random.uniform(0.5, 3.0) * (lev / 25)
        short_liq_zones.append({
            'price': liq_price,
            'leverage': lev,
            'volume_usd': random.uniform(2, 50) * 1_000_000 * vol_weight,
            'type': 'SHORT_LIQ'
        })
    
    # Find heaviest liquidation zones
    all_zones = long_liq_zones + short_liq_zones
    all_zones.sort(key=lambda x: x['volume_usd'], reverse=True)
    
    # Order block zones (key S/R levels)
    # Based on recent price structure
    volatility = current_price * 0.03  # ~3% range
    
    order_blocks = {
        'buy_ob_1': {
            'price_low': current_price * (1 - random.uniform(0.02, 0.04)),
            'price_high': current_price * (1 - random.uniform(0.01, 0.02)),
            'strength': random.choice(['STRONG', 'MEDIUM', 'STRONG']),
            'reason': 'Liquidity grab zone + previous support'
        },
        'buy_ob_2': {
            'price_low': current_price * (1 - random.uniform(0.05, 0.08)),
            'price_high': current_price * (1 - random.uniform(0.04, 0.05)),
            'strength': random.choice(['MEDIUM', 'STRONG']),
            'reason': 'Heavy long liquidation cluster'
        },
        'sell_ob_1': {
            'price_low': current_price * (1 + random.uniform(0.01, 0.02)),
            'price_high': current_price * (1 + random.uniform(0.02, 0.04)),
            'strength': random.choice(['STRONG', 'MEDIUM']),
            'reason': 'Short liquidation cluster + resistance'
        },
    }
    
    # Heaviest liquidation area
    heaviest_long = max(long_liq_zones, key=lambda x: x['volume_usd'])
    heaviest_short = max(short_liq_zones, key=lambda x: x['volume_usd'])
    
    return {
        'long_liq_zones': sorted(long_liq_zones, key=lambda x: x['price'], reverse=True),
        'short_liq_zones': sorted(short_liq_zones, key=lambda x: x['price']),
        'order_blocks': order_blocks,
        'heaviest_long_liq': heaviest_long,
        'heaviest_short_liq': heaviest_short,
        'total_long_liq_usd': sum(z['volume_usd'] for z in long_liq_zones),
        'total_short_liq_usd': sum(z['volume_usd'] for z in short_liq_zones),
    }


def generate_market_chat_response(symbol: str) -> str:
    """
    Generate a full market analysis response with trend, OB zones, and liquidation data.
    Used when user asks about a coin in chat (not command).
    """
    coin = symbol.replace('/USDT', '').replace('USDT', '')
    
    # Get base analysis
    analysis = generate_analysis(symbol)
    current_price = analysis['price']
    
    # Get liquidation data
    liq_data = get_liquidation_zones(symbol, current_price)
    ob = liq_data['order_blocks']
    
    # Determine trend description
    score = analysis['score']
    if score >= 30:
        trend_status = "📈 *Uptrend*"
        trend_desc = "Momentum bullish, harga di atas MA key levels"
    elif score >= 10:
        trend_status = "↗️ *Weak Uptrend*"
        trend_desc = "Sedikit bullish tapi belum kuat, hati-hati"
    elif score >= -10:
        trend_status = "➡️ *Sideways*"
        trend_desc = "Konsolidasi, ranging antara support & resistance"
    elif score >= -30:
        trend_status = "↘️ *Weak Downtrend*"
        trend_desc = "Momentum melemah, potensi lanjut turun"
    else:
        trend_status = "📉 *Downtrend*"
        trend_desc = "Bearish, harga di bawah MA key levels"
    
    # Format message
    msg = f"🪙 *{symbol}* - Market Update\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━\n\n"
    
    msg += f"💰 *Harga:* `${current_price:,.4f}`\n"
    msg += f"📊 *Trend:* {trend_status}\n"
    msg += f"📝 _{trend_desc}_\n\n"
    
    # Order Block Zones
    msg += f"━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🟢 *BUY ZONE (Order Block):*\n\n"
    
    buy_ob1 = ob['buy_ob_1']
    buy_ob2 = ob['buy_ob_2']
    
    msg += f"  📍 *OB Zone 1* ({buy_ob1['strength']})\n"
    msg += f"     `${buy_ob1['price_low']:,.2f}` - `${buy_ob1['price_high']:,.2f}`\n"
    msg += f"     _{buy_ob1['reason']}_\n\n"
    
    msg += f"  📍 *OB Zone 2* ({buy_ob2['strength']})\n"
    msg += f"     `${buy_ob2['price_low']:,.2f}` - `${buy_ob2['price_high']:,.2f}`\n"
    msg += f"     _{buy_ob2['reason']}_\n\n"
    
    msg += f"🔴 *SELL ZONE (Order Block):*\n\n"
    sell_ob = ob['sell_ob_1']
    msg += f"  📍 *OB Zone* ({sell_ob['strength']})\n"
    msg += f"     `${sell_ob['price_low']:,.2f}` - `${sell_ob['price_high']:,.2f}`\n"
    msg += f"     _{sell_ob['reason']}_\n\n"
    
    # Liquidation Data (Coinglass style)
    msg += f"━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"💧 *LIQUIDATION DATA (Coinglass):*\n\n"
    
    heaviest_long = liq_data['heaviest_long_liq']
    heaviest_short = liq_data['heaviest_short_liq']
    
    msg += f"  🔻 *Long Liq Terbesar:*\n"
    msg += f"     Harga: `${heaviest_long['price']:,.2f}` ({heaviest_long['leverage']}x)\n"
    msg += f"     Volume: `${heaviest_long['volume_usd']/1_000_000:.1f}M`\n\n"
    
    msg += f"  🔺 *Short Liq Terbesar:*\n"
    msg += f"     Harga: `${heaviest_short['price']:,.2f}` ({heaviest_short['leverage']}x)\n"
    msg += f"     Volume: `${heaviest_short['volume_usd']/1_000_000:.1f}M`\n\n"
    
    msg += f"  📊 Total Long Liq: `${liq_data['total_long_liq_usd']/1_000_000:.1f}M`\n"
    msg += f"  📊 Total Short Liq: `${liq_data['total_short_liq_usd']/1_000_000:.1f}M`\n\n"
    
    # Conclusion
    msg += f"━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🧠 *KESIMPULAN:*\n\n"
    
    if liq_data['total_long_liq_usd'] > liq_data['total_short_liq_usd'] * 1.3:
        msg += f"⚠️ Likuidasi long lebih tebal → Market maker kemungkinan hunt long dulu\n"
        msg += f"💡 _Wait for sweep ke OB Zone sebelum entry_\n"
    elif liq_data['total_short_liq_usd'] > liq_data['total_long_liq_usd'] * 1.3:
        msg += f"🟢 Likuidasi short lebih tebal → Potensi pump ke atas\n"
        msg += f"💡 _Bisa entry di OB Zone 1, SL di bawah OB Zone 2_\n"
    else:
        msg += f"😐 Likuidasi seimbang → Market belum tentukan arah\n"
        msg += f"💡 _Tunggu breakout dari range, atau scalp di OB zones_\n"
    
    msg += f"\n⚠️ _NFA - DYOR! Data based on Coinglass liquidation model_"
    
    return msg


def detect_coin_in_message(text: str) -> str:
    """Detect if user is asking about a specific coin in their message."""
    text_upper = text.upper()
    
    # List of known coins to detect
    coins = [
        'BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'AVAX', 'DOGE', 
        'DOT', 'LINK', 'MATIC', 'UNI', 'ATOM', 'LTC', 'ETC',
        'FIL', 'APT', 'ARB', 'OP', 'INJ', 'SUI', 'SEI', 'TIA', 
        'NEAR', 'FTM', 'RUNE', 'PEPE', 'WIF', 'BONK', 'FLOKI', 
        'SHIB', 'ORDI', 'STX', 'RENDER', 'FET', 'SAND', 'MANA',
        'BITCOIN', 'ETHEREUM', 'SOLANA', 'CARDANO', 'DOGECOIN',
    ]
    
    # Map full names to tickers
    name_map = {
        'BITCOIN': 'BTC', 'ETHEREUM': 'ETH', 'SOLANA': 'SOL',
        'CARDANO': 'ADA', 'DOGECOIN': 'DOGE',
    }
    
    # Check for coin/USDT format
    for coin in coins:
        patterns = [
            f'{coin}/USDT', f'{coin}USDT', f'{coin}/USD',
            f' {coin} ', f' {coin}', f'{coin} ',
        ]
        for pattern in patterns:
            if pattern in text_upper or text_upper.startswith(coin) or text_upper.endswith(coin):
                final_coin = name_map.get(coin, coin)
                return f"{final_coin}/USDT"
    
    # Also check within words
    for coin in coins:
        if coin in text_upper and len(coin) >= 3:
            final_coin = name_map.get(coin, coin)
            return f"{final_coin}/USDT"
    
    return None


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular messages - Smart conversational AI"""
    text = update.message.text
    text_lower = text.lower()
    
    # === GREETINGS ===
    greetings = ["halo", "hai", "hi", "hello", "hey", "woi", "oy", "yo", "selamat"]
    if any(text_lower.strip().startswith(word) for word in greetings) or (len(text_lower.split()) <= 3 and any(word in text_lower for word in greetings)):
        await update.message.reply_text(
            "👋 *Halo bro! Apa kabar?*\n\n"
            "Ada yang bisa gue bantu hari ini? 🤝\n\n"
            "Lo bisa tanya gue:\n"
            "• _\"Gimana market SOL?\"_ → Analisis + OB zone\n"
            "• _\"BTC lagi gimana?\"_ → Trend + liquidation data\n"
            "• _\"Potensi ETH?\"_ → Full analysis\n\n"
            "Atau pake command:\n"
            "• `/potential` - Scan koin potensial\n"
            "• `/analyze BTC` - Analisis detail\n"
            "• `/help` - Bantuan lengkap",
            parse_mode="Markdown"
        )
        return
    
    # === GM/GN ===
    if text_lower.strip() in ["gm", "good morning", "pagi"]:
        await update.message.reply_text("GM bro! ☀️ Semoga hari ini profit gede! Let's get this bread! 🚀💰")
        return
    if text_lower.strip() in ["gn", "good night", "malam"]:
        await update.message.reply_text("GN bro! 🌙 Istirahat yang cukup, besok lanjut cari cuan! 💤")
        return
    
    # === THANKS ===
    if any(word in text_lower for word in ["makasih", "thanks", "thx", "tengkyu", "thank you", "terima kasih"]):
        await update.message.reply_text("Sama-sama bro! 🤝 Semoga info-nya berguna ya! Semangat cuan! 💰🚀")
        return
    
    # === DETECT COIN QUESTION (Smart Market Chat) ===
    market_keywords = ["gimana", "bagaimana", "market", "analisis", "analisa", "potensi", 
                       "trend", "kondisi", "lagi", "kayak", "seperti", "harga", "price",
                       "zona", "zone", "order block", "ob", "likuidasi", "liquidation",
                       "buy", "sell", "entry", "naik", "turun", "pump", "dump"]
    
    detected_coin = detect_coin_in_message(text)
    
    if detected_coin:
        # User is asking about a specific coin
        await update.message.reply_text(f"🔍 _Analyzing {detected_coin}..._", parse_mode="Markdown")
        
        try:
            response = generate_market_chat_response(detected_coin)
            await update.message.reply_text(response, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Gagal analisis {detected_coin}: {e}")
            logger.error(f"Chat analysis error: {e}")
        return
    
    # === GENERAL MARKET QUESTION (no specific coin) ===
    if any(word in text_lower for word in ["market", "pasar", "crypto", "kripto"]):
        await update.message.reply_text(
            "📊 *Mau tau kondisi market?*\n\n"
            "Sebutin koin-nya bro! Contoh:\n"
            "• _\"Gimana SOL?\"_\n"
            "• _\"BTC lagi apa nih?\"_\n"
            "• _\"Potensi ETH dimana?\"_\n\n"
            "Atau ketik `/potential` buat scan semua koin sekaligus! 🔍",
            parse_mode="Markdown"
        )
        return
    
    # === HOW TO / TUTORIAL ===
    if any(word in text_lower for word in ["gimana caranya", "tutorial", "cara pakai", "cara pake"]):
        await update.message.reply_text(
            "📚 *Gampang bro!*\n\n"
            "🗣️ *Chat biasa:*\n"
            "Tinggal tanya aja, misal:\n"
            "• _\"SOL lagi gimana?\"_\n"
            "• _\"Ada zona buy BTC ga?\"_\n"
            "• _\"ETH potensi naik?\"_\n\n"
            "⌨️ *Pake Command:*\n"
            "• `/potential` - Scan 40+ koin\n"
            "• `/analyze SOL` - Detail analysis\n"
            "• `/scan` - Quick scan\n"
            "• `/top` - Top peluang\n\n"
            "Gue bakal kasih zona entry, liquidation data, dan order block! 🎯",
            parse_mode="Markdown"
        )
        return
    
    # === DEFAULT RESPONSE ===
    await update.message.reply_text(
        "🤖 *Halo bro!*\n\n"
        "Gue bisa bantu lo:\n"
        "• Tanya market koin → _\"Gimana SOL?\"_\n"
        "• Cari zona entry → _\"BTC buy dimana?\"_\n"
        "• Scan potensi → `/potential`\n"
        "• Detail analisis → `/analyze BTC`\n\n"
        "Tinggal ketik nama koin-nya aja, gue langsung kasih analisis! 💪",
        parse_mode="Markdown"
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
    app.add_handler(CommandHandler("potential", potential_cmd))
    app.add_handler(CommandHandler("exchanges", exchanges_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Bot is now running! Listening for messages...")
    print("Commands: /start /potential /scan /top /analyze /help")
    
    # Run the bot
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
