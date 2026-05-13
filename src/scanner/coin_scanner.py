"""
Coin Scanner Module
====================

Scans multiple exchanges to find coins that match the strategy criteria:
- RSI oversold/overbought + MA200 trend
- Bollinger Bands breakout/squeeze
- Volume spike detection
- Multi-timeframe confluence

Supports: Binance, Bybit, Bitget, OKX
"""

import asyncio
import numpy as np
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

try:
    import ccxt.async_support as ccxt_async
    import ccxt
except ImportError:
    ccxt_async = None
    ccxt = None


class SignalStrength(Enum):
    STRONG_BUY = "🟢🟢🟢 STRONG BUY"
    BUY = "🟢 BUY"
    WEAK_BUY = "🟡 WEAK BUY"
    NEUTRAL = "⚪ NEUTRAL"
    WEAK_SELL = "🟡 WEAK SELL"
    SELL = "🔴 SELL"
    STRONG_SELL = "🔴🔴🔴 STRONG SELL"


@dataclass
class CoinSignal:
    """Signal result for a scanned coin"""
    symbol: str
    exchange: str
    market_type: str  # spot or futures
    timeframe: str
    price: float
    signal: SignalStrength
    score: float  # -100 to +100
    
    # Indicator values
    rsi: float = 0.0
    ma30: float = 0.0
    ma50: float = 0.0
    ma200: float = 0.0
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_width_pct: float = 0.0
    atr: float = 0.0
    volume_ratio: float = 1.0  # current vol / avg vol
    
    # Analysis
    trend: str = "NEUTRAL"  # UPTREND, DOWNTREND, SIDEWAYS
    reasons: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_telegram_message(self) -> str:
        """Format signal for Telegram"""
        emoji_trend = "📈" if self.trend == "UPTREND" else "📉" if self.trend == "DOWNTREND" else "➡️"
        
        msg = (
            f"{self.signal.value}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *{self.symbol}* | {self.exchange.upper()}\n"
            f"💰 Price: `${self.price:,.4f}`\n"
            f"📊 Timeframe: `{self.timeframe}`\n"
            f"🎯 Score: `{self.score:+.1f}/100`\n"
            f"{emoji_trend} Trend: `{self.trend}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Indicators:*\n"
            f"• RSI(14): `{self.rsi:.1f}`\n"
            f"• Price vs MA200: `{((self.price/self.ma200)-1)*100:+.2f}%`\n"
            f"• BB Width: `{self.bb_width_pct:.2f}%`\n"
            f"• Volume: `{self.volume_ratio:.1f}x avg`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Reasons:*\n"
        )
        for reason in self.reasons[:5]:
            msg += f"• {reason}\n"
        
        return msg


# ========================================
# INDICATOR CALCULATIONS
# ========================================

def calc_rsi(closes: np.ndarray, period: int = 14) -> float:
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


def calc_sma(data: np.ndarray, period: int) -> float:
    """Calculate Simple Moving Average"""
    if len(data) < period:
        return data[-1] if len(data) > 0 else 0
    return np.mean(data[-period:])


def calc_bollinger_bands(closes: np.ndarray, period: int = 20, mult: float = 2.0):
    """Calculate Bollinger Bands"""
    if len(closes) < period:
        return closes[-1], closes[-1], closes[-1], 0
    
    sma = np.mean(closes[-period:])
    std = np.std(closes[-period:])
    upper = sma + mult * std
    lower = sma - mult * std
    width_pct = ((upper - lower) / sma) * 100 if sma > 0 else 0
    
    return upper, sma, lower, width_pct


def calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Calculate ATR"""
    if len(highs) < 2:
        return 0
    
    tr = []
    for i in range(1, len(highs)):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        ))
    
    if len(tr) < period:
        return np.mean(tr) if tr else 0
    
    return np.mean(tr[-period:])


# ========================================
# COIN SCANNER CLASS
# ========================================

class CoinScanner:
    """
    Multi-exchange coin scanner that finds trading opportunities
    based on RSI+MA200 and Bollinger Bands confluence strategy.
    """
    
    SUPPORTED_EXCHANGES = {
        'binance': {'class': 'binance', 'has_futures': True},
        'bybit': {'class': 'bybit', 'has_futures': True},
        'bitget': {'class': 'bitget', 'has_futures': True},
        'okx': {'class': 'okx', 'has_futures': True},
        'kucoin': {'class': 'kucoin', 'has_futures': True},
        'mexc': {'class': 'mexc', 'has_futures': True},
    }
    
    # Top coins to scan by default
    DEFAULT_COINS = [
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
        'ADA/USDT', 'AVAX/USDT', 'DOGE/USDT', 'DOT/USDT', 'MATIC/USDT',
        'LINK/USDT', 'UNI/USDT', 'ATOM/USDT', 'LTC/USDT', 'ETC/USDT',
        'FIL/USDT', 'APT/USDT', 'ARB/USDT', 'OP/USDT', 'INJ/USDT',
        'SUI/USDT', 'SEI/USDT', 'TIA/USDT', 'NEAR/USDT', 'FTM/USDT',
        'RUNE/USDT', 'IMX/USDT', 'SAND/USDT', 'MANA/USDT', 'GALA/USDT',
    ]
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.exchanges: Dict[str, Any] = {}
        
        # Strategy params
        self.rsi_oversold = self.config.get('rsi_oversold', 30)
        self.rsi_overbought = self.config.get('rsi_overbought', 70)
        self.bb_squeeze_threshold = self.config.get('bb_squeeze_pct', 3.0)
        self.volume_spike_threshold = self.config.get('volume_spike', 1.5)
    
    def init_exchange(self, exchange_name: str, api_key: str = None, 
                      api_secret: str = None, testnet: bool = False) -> bool:
        """Initialize an exchange connection"""
        if exchange_name not in self.SUPPORTED_EXCHANGES:
            return False
        
        if ccxt is None:
            print("ccxt not installed!")
            return False
        
        try:
            exchange_class = getattr(ccxt, self.SUPPORTED_EXCHANGES[exchange_name]['class'])
            
            options = {
                'enableRateLimit': True,
                'timeout': 30000,
            }
            
            if api_key and api_secret:
                options['apiKey'] = api_key
                options['secret'] = api_secret
            
            if testnet:
                options['sandbox'] = True
            
            self.exchanges[exchange_name] = exchange_class(options)
            return True
            
        except Exception as e:
            print(f"Failed to init {exchange_name}: {e}")
            return False
    
    def analyze_coin(self, ohlcv: List[List], symbol: str, exchange: str,
                     timeframe: str, market_type: str = 'spot') -> Optional[CoinSignal]:
        """
        Analyze a single coin using the confluence strategy.
        
        ohlcv format: [[timestamp, open, high, low, close, volume], ...]
        """
        if not ohlcv or len(ohlcv) < 200:
            return None
        
        # Extract data
        data = np.array(ohlcv)
        opens = data[:, 1]
        highs = data[:, 2]
        lows = data[:, 3]
        closes = data[:, 4]
        volumes = data[:, 5]
        
        current_price = closes[-1]
        
        # Calculate indicators
        rsi = calc_rsi(closes, 14)
        ma30 = calc_sma(closes, 30)
        ma50 = calc_sma(closes, 50)
        ma200 = calc_sma(closes, 200)
        bb_upper, bb_mid, bb_lower, bb_width = calc_bollinger_bands(closes, 20, 2.0)
        atr = calc_atr(highs, lows, closes, 14)
        
        # Volume analysis
        avg_volume = np.mean(volumes[-20:])
        current_volume = volumes[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        # Determine trend
        if current_price > ma30 > ma50 > ma200:
            trend = "UPTREND"
        elif current_price < ma30 < ma50 < ma200:
            trend = "DOWNTREND"
        else:
            trend = "SIDEWAYS"
        
        # ========================================
        # SCORING SYSTEM (-100 to +100)
        # ========================================
        score = 0
        reasons = []
        
        # --- RSI Analysis ---
        if rsi <= self.rsi_oversold:
            score += 25
            reasons.append(f"RSI oversold ({rsi:.1f})")
        elif rsi <= 40:
            score += 10
            reasons.append(f"RSI low ({rsi:.1f})")
        elif rsi >= self.rsi_overbought:
            score -= 25
            reasons.append(f"RSI overbought ({rsi:.1f})")
        elif rsi >= 60:
            score -= 10
            reasons.append(f"RSI high ({rsi:.1f})")
        
        # --- MA200 Trend Filter ---
        if current_price > ma200:
            score += 20
            pct_above = ((current_price / ma200) - 1) * 100
            reasons.append(f"Above MA200 (+{pct_above:.1f}%)")
        else:
            score -= 20
            pct_below = ((ma200 / current_price) - 1) * 100
            reasons.append(f"Below MA200 (-{pct_below:.1f}%)")
        
        # --- MA Stack (30 > 50 > 200 for uptrend) ---
        if current_price > ma30 > ma50 > ma200:
            score += 15
            reasons.append("Bullish MA stack")
        elif current_price < ma30 < ma50 < ma200:
            score -= 15
            reasons.append("Bearish MA stack")
        
        # --- Bollinger Bands ---
        if current_price <= bb_lower:
            score += 20
            reasons.append("At lower BB (potential bounce)")
        elif current_price >= bb_upper:
            score -= 20
            reasons.append("At upper BB (potential rejection)")
        
        # BB Squeeze (low volatility = potential breakout)
        if bb_width <= self.bb_squeeze_threshold:
            score += 10
            reasons.append(f"BB squeeze ({bb_width:.2f}%)")
        
        # --- Volume Analysis ---
        if volume_ratio >= self.volume_spike_threshold:
            # Volume spike in direction of trend
            if trend == "UPTREND":
                score += 15
                reasons.append(f"Volume spike {volume_ratio:.1f}x (bullish)")
            elif trend == "DOWNTREND":
                score -= 15
                reasons.append(f"Volume spike {volume_ratio:.1f}x (bearish)")
            else:
                reasons.append(f"Volume spike {volume_ratio:.1f}x")
        
        # --- Confluence Bonus ---
        bullish_signals = sum([
            rsi <= 40,
            current_price > ma200,
            current_price <= bb_lower * 1.02,
            trend == "UPTREND"
        ])
        
        bearish_signals = sum([
            rsi >= 60,
            current_price < ma200,
            current_price >= bb_upper * 0.98,
            trend == "DOWNTREND"
        ])
        
        if bullish_signals >= 3:
            score += 15
            reasons.append("Strong confluence (BUY)")
        elif bearish_signals >= 3:
            score -= 15
            reasons.append("Strong confluence (SELL)")
        
        # Clamp score
        score = max(-100, min(100, score))
        
        # Determine signal strength
        if score >= 60:
            signal = SignalStrength.STRONG_BUY
        elif score >= 30:
            signal = SignalStrength.BUY
        elif score >= 10:
            signal = SignalStrength.WEAK_BUY
        elif score <= -60:
            signal = SignalStrength.STRONG_SELL
        elif score <= -30:
            signal = SignalStrength.SELL
        elif score <= -10:
            signal = SignalStrength.WEAK_SELL
        else:
            signal = SignalStrength.NEUTRAL
        
        return CoinSignal(
            symbol=symbol,
            exchange=exchange,
            market_type=market_type,
            timeframe=timeframe,
            price=current_price,
            signal=signal,
            score=score,
            rsi=rsi,
            ma30=ma30,
            ma50=ma50,
            ma200=ma200,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
            bb_width_pct=bb_width,
            atr=atr,
            volume_ratio=volume_ratio,
            trend=trend,
            reasons=reasons,
        )
    
    async def scan_exchange_async(self, exchange_name: str, symbols: List[str] = None,
                                   timeframe: str = '1h', market_type: str = 'spot',
                                   min_score: float = 20) -> List[CoinSignal]:
        """
        Scan an exchange for trading opportunities (async version).
        """
        if exchange_name not in self.exchanges:
            return []
        
        exchange = self.exchanges[exchange_name]
        symbols = symbols or self.DEFAULT_COINS
        results = []
        
        for symbol in symbols:
            try:
                # Fetch OHLCV data
                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=250)
                
                if ohlcv and len(ohlcv) >= 200:
                    signal = self.analyze_coin(ohlcv, symbol, exchange_name, 
                                               timeframe, market_type)
                    if signal and abs(signal.score) >= min_score:
                        results.append(signal)
                
                # Rate limiting
                await asyncio.sleep(0.1)
                
            except Exception as e:
                print(f"Error scanning {symbol} on {exchange_name}: {e}")
                continue
        
        # Sort by absolute score (strongest signals first)
        results.sort(key=lambda x: abs(x.score), reverse=True)
        return results
    
    def scan_with_sample_data(self, symbols: List[str] = None, 
                               timeframe: str = '1h') -> List[CoinSignal]:
        """
        Scan using simulated data (for demo/testing when exchange is unavailable).
        """
        import random
        
        symbols = symbols or self.DEFAULT_COINS[:10]
        results = []
        
        for symbol in symbols:
            # Generate realistic sample data
            base_price = random.uniform(0.5, 50000)
            
            # Generate 250 candles
            ohlcv = []
            price = base_price
            for i in range(250):
                change = random.gauss(0, 0.02)  # 2% std dev
                price *= (1 + change)
                high = price * (1 + abs(random.gauss(0, 0.005)))
                low = price * (1 - abs(random.gauss(0, 0.005)))
                volume = random.uniform(100000, 10000000)
                ohlcv.append([i * 3600000, price, high, low, price, volume])
            
            signal = self.analyze_coin(ohlcv, symbol, 'demo', timeframe, 'spot')
            if signal and abs(signal.score) >= 15:
                results.append(signal)
        
        results.sort(key=lambda x: abs(x.score), reverse=True)
        return results


# ========================================
# MULTI-EXCHANGE SCANNER
# ========================================

class MultiExchangeScanner:
    """
    Scans multiple exchanges simultaneously for the best opportunities.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.scanner = CoinScanner(config)
        
        # Exchange credentials (loaded from config)
        self.credentials = self.config.get('exchanges', {})
    
    def add_exchange(self, name: str, api_key: str = None, 
                     api_secret: str = None, testnet: bool = False) -> bool:
        """Add an exchange to scan"""
        return self.scanner.init_exchange(name, api_key, api_secret, testnet)
    
    async def scan_all_async(self, symbols: List[str] = None, 
                              timeframe: str = '1h',
                              min_score: float = 25) -> Dict[str, List[CoinSignal]]:
        """
        Scan all configured exchanges asynchronously.
        Returns dict of {exchange_name: [signals]}
        """
        results = {}
        tasks = []
        
        for exchange_name in self.scanner.exchanges.keys():
            task = self.scanner.scan_exchange_async(
                exchange_name, symbols, timeframe, 'spot', min_score
            )
            tasks.append((exchange_name, task))
        
        for exchange_name, task in tasks:
            try:
                signals = await task
                results[exchange_name] = signals
            except Exception as e:
                print(f"Error scanning {exchange_name}: {e}")
                results[exchange_name] = []
        
        return results
    
    def get_top_opportunities(self, all_results: Dict[str, List[CoinSignal]], 
                               top_n: int = 10) -> List[CoinSignal]:
        """
        Get the top N opportunities across all exchanges.
        """
        all_signals = []
        for signals in all_results.values():
            all_signals.extend(signals)
        
        # Sort by score
        all_signals.sort(key=lambda x: x.score, reverse=True)
        
        # Return top buys and top sells separately
        buys = [s for s in all_signals if s.score > 0][:top_n//2]
        sells = [s for s in all_signals if s.score < 0]
        sells.sort(key=lambda x: x.score)
        sells = sells[:top_n//2]
        
        return buys + sells


# ========================================
# QUICK TEST
# ========================================

if __name__ == "__main__":
    print("🔍 Testing Coin Scanner with sample data...\n")
    
    scanner = CoinScanner()
    results = scanner.scan_with_sample_data(
        symbols=['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'DOGE/USDT', 'XRP/USDT'],
        timeframe='1h'
    )
    
    print(f"Found {len(results)} signals:\n")
    
    for signal in results[:5]:
        print(signal.to_telegram_message())
        print()
