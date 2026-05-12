"""
Market Data Module
Fetches candle data and computes all technical indicators
needed by both strategies (RSI, SMA, Bollinger Bands, ATR).
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from src.exchange.client import BinanceClient
from src.utils.logger import get_logger

logger = get_logger("market_data")


# ========================================
# DATA STRUCTURES
# ========================================

@dataclass
class Indicators:
    """All computed indicators for a symbol/timeframe."""
    # Price data
    close: np.ndarray
    high: np.ndarray
    low: np.ndarray
    open: np.ndarray
    volume: np.ndarray
    timestamps: np.ndarray

    # Moving Averages
    sma_30: np.ndarray
    sma_50: np.ndarray
    sma_200: np.ndarray

    # RSI
    rsi: np.ndarray

    # Bollinger Bands
    bb_upper: np.ndarray
    bb_middle: np.ndarray
    bb_lower: np.ndarray
    bb_width: np.ndarray

    # ATR
    atr: np.ndarray

    @property
    def last_close(self) -> float:
        """Most recent close price."""
        return float(self.close[-1])

    @property
    def prev_close(self) -> float:
        """Previous bar close price."""
        return float(self.close[-2]) if len(self.close) > 1 else float(self.close[-1])

    @property
    def last_rsi(self) -> float:
        return float(self.rsi[-1])

    @property
    def prev_rsi(self) -> float:
        return float(self.rsi[-2]) if len(self.rsi) > 1 else float(self.rsi[-1])

    @property
    def last_sma_30(self) -> float:
        return float(self.sma_30[-1])

    @property
    def last_sma_50(self) -> float:
        return float(self.sma_50[-1])

    @property
    def last_sma_200(self) -> float:
        return float(self.sma_200[-1])

    @property
    def last_bb_upper(self) -> float:
        return float(self.bb_upper[-1])

    @property
    def prev_bb_upper(self) -> float:
        return float(self.bb_upper[-2]) if len(self.bb_upper) > 1 else float(self.bb_upper[-1])

    @property
    def last_bb_lower(self) -> float:
        return float(self.bb_lower[-1])

    @property
    def prev_bb_lower(self) -> float:
        return float(self.bb_lower[-2]) if len(self.bb_lower) > 1 else float(self.bb_lower[-1])

    @property
    def last_bb_middle(self) -> float:
        return float(self.bb_middle[-1])

    @property
    def last_bb_width(self) -> float:
        return float(self.bb_width[-1])

    @property
    def last_atr(self) -> float:
        return float(self.atr[-1])


# ========================================
# INDICATOR CALCULATIONS (Pure Functions)
# ========================================

def compute_sma(data: np.ndarray, period: int) -> np.ndarray:
    """Compute Simple Moving Average."""
    if len(data) < period:
        return np.full(len(data), np.nan)

    sma = np.full(len(data), np.nan)
    for i in range(period - 1, len(data)):
        sma[i] = np.mean(data[i - period + 1: i + 1])
    return sma


def compute_rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
    """
    Compute RSI using Wilder's smoothing method (same as TradingView).
    """
    if len(data) < period + 1:
        return np.full(len(data), np.nan)

    rsi = np.full(len(data), np.nan)
    deltas = np.diff(data)

    # First RSI calculation uses simple average
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))

    # Subsequent RSI uses Wilder's smoothing
    for i in range(period, len(deltas)):
        gain = gains[i]
        loss = losses[i]

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


def compute_bollinger_bands(
    data: np.ndarray, period: int = 20, mult: float = 2.0
) -> tuple:
    """
    Compute Bollinger Bands.
    Returns: (upper, middle, lower, width)
    """
    middle = compute_sma(data, period)
    std = np.full(len(data), np.nan)

    for i in range(period - 1, len(data)):
        std[i] = np.std(data[i - period + 1: i + 1], ddof=0)  # population std (like Pine)

    upper = middle + mult * std
    lower = middle - mult * std
    width = upper - lower

    return upper, middle, lower, width


def compute_atr(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14
) -> np.ndarray:
    """
    Compute Average True Range using Wilder's smoothing.
    """
    if len(high) < 2:
        return np.full(len(high), np.nan)

    atr = np.full(len(high), np.nan)

    # True Range
    tr = np.zeros(len(high))
    tr[0] = high[0] - low[0]
    for i in range(1, len(high)):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    # First ATR is simple average
    if len(tr) >= period:
        atr[period - 1] = np.mean(tr[:period])

        # Wilder's smoothing
        for i in range(period, len(tr)):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


# ========================================
# MARKET DATA MANAGER
# ========================================

class MarketDataManager:
    """
    Manages fetching and computing indicators for all configured pairs/timeframes.
    """

    def __init__(self, client: BinanceClient, config: Any):
        self.client = client
        self.config = config
        # Cache: {(symbol, timeframe, market_type): Indicators}
        self._cache: Dict[tuple, Indicators] = {}

    def fetch_and_compute(
        self,
        symbol: str,
        timeframe: str,
        market_type: str = "futures",
        limit: int = 500,
    ) -> Optional[Indicators]:
        """
        Fetch candles and compute all indicators for a symbol/timeframe.
        
        Args:
            symbol: Trading pair (e.g., "SOL/USDT")
            timeframe: Candle timeframe (e.g., "15m", "2h")
            market_type: "spot" or "futures"
            limit: Number of candles to fetch (need 200+ for MA200)
            
        Returns:
            Indicators object or None if fetch fails
        """
        try:
            # Fetch candles
            candles = self.client.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                market_type=market_type,
            )

            if not candles or len(candles) < 200:
                logger.warning(
                    f"Insufficient candles for {symbol} {timeframe}: "
                    f"got {len(candles) if candles else 0}, need 200+"
                )
                # Still compute with what we have if > 50 bars
                if not candles or len(candles) < 50:
                    return None

            # Convert to numpy arrays
            data = np.array(candles, dtype=float)
            timestamps = data[:, 0]
            opens = data[:, 1]
            highs = data[:, 2]
            lows = data[:, 3]
            closes = data[:, 4]
            volumes = data[:, 5]

            # Compute indicators
            rsi_cfg = self.config.strategy_rsi_ma200
            bb_cfg = self.config.strategy_bollinger

            # Moving Averages
            sma_30 = compute_sma(closes, 30)
            sma_50 = compute_sma(closes, 50)
            sma_200 = compute_sma(closes, rsi_cfg.ma_length)

            # RSI
            rsi = compute_rsi(closes, rsi_cfg.rsi_length)

            # Bollinger Bands
            bb_upper, bb_middle, bb_lower, bb_width = compute_bollinger_bands(
                closes, bb_cfg.bb_length, bb_cfg.bb_mult
            )

            # ATR
            atr = compute_atr(highs, lows, closes, bb_cfg.atr_length)

            indicators = Indicators(
                close=closes,
                high=highs,
                low=lows,
                open=opens,
                volume=volumes,
                timestamps=timestamps,
                sma_30=sma_30,
                sma_50=sma_50,
                sma_200=sma_200,
                rsi=rsi,
                bb_upper=bb_upper,
                bb_middle=bb_middle,
                bb_lower=bb_lower,
                bb_width=bb_width,
                atr=atr,
            )

            # Cache it
            cache_key = (symbol, timeframe, market_type)
            self._cache[cache_key] = indicators

            logger.debug(
                f"Computed indicators for {symbol} {timeframe} | "
                f"RSI={indicators.last_rsi:.1f} | "
                f"Close={indicators.last_close:.4f} | "
                f"SMA200={indicators.last_sma_200:.4f}"
            )

            return indicators

        except Exception as e:
            logger.error(f"Error computing indicators for {symbol} {timeframe}: {e}")
            return None

    def get_cached(
        self, symbol: str, timeframe: str, market_type: str = "futures"
    ) -> Optional[Indicators]:
        """Get cached indicators without re-fetching."""
        return self._cache.get((symbol, timeframe, market_type))

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache.clear()

    def fetch_all_pairs(
        self, timeframe: str, market_type: str = "futures"
    ) -> Dict[str, Indicators]:
        """
        Fetch and compute indicators for all configured pairs.
        Returns dict of {symbol: Indicators}.
        """
        results = {}
        for symbol in self.config.trading.pairs:
            indicators = self.fetch_and_compute(symbol, timeframe, market_type)
            if indicators is not None:
                results[symbol] = indicators
        return results
