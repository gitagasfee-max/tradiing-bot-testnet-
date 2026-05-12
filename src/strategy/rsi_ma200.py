"""
Strategy 1: RSI + MA200 Trend Filter
=====================================

Logic (translated from Pine Script):
- Trend UP: close > SMA(200)
- Trend DOWN: close <= SMA(200)

Signals:
- BUY:  trend is UP AND RSI crosses UP through oversold level (30)
- SELL: trend is DOWN AND RSI crosses DOWN through overbought level (70)
- WARNING: RSI was >= 70 on prev bar, RSI is now falling, and still > 70
           (early reversal warning from overbought)

Additional filter (user spec):
- Long only when price > MA30, MA50, AND MA200
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

from src.data.market_data import Indicators
from config.settings import RSIStrategyConfig
from src.utils.logger import get_logger

logger = get_logger("strategy.rsi_ma200")


# ========================================
# SIGNAL TYPES
# ========================================

class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    WARNING = "WARNING"
    NONE = "NONE"


@dataclass
class StrategySignal:
    """Signal output from a strategy."""
    signal_type: SignalType
    symbol: str
    timeframe: str
    price: float
    reason: str
    strength: float = 0.0  # 0-1, used for confluence weighting
    rsi_value: float = 0.0
    ma200_value: float = 0.0


# ========================================
# HELPER: CROSS DETECTION
# ========================================

def crossover(series: np.ndarray, level: float, index: int = -1) -> bool:
    """
    Detect if series crosses ABOVE a level at the given index.
    series[index-1] < level AND series[index] >= level
    """
    if len(series) < 2:
        return False
    idx = index if index >= 0 else len(series) + index
    if idx < 1:
        return False
    prev = series[idx - 1]
    curr = series[idx]
    if np.isnan(prev) or np.isnan(curr):
        return False
    return prev < level and curr >= level


def crossunder(series: np.ndarray, level: float, index: int = -1) -> bool:
    """
    Detect if series crosses BELOW a level at the given index.
    series[index-1] > level AND series[index] <= level
    """
    if len(series) < 2:
        return False
    idx = index if index >= 0 else len(series) + index
    if idx < 1:
        return False
    prev = series[idx - 1]
    curr = series[idx]
    if np.isnan(prev) or np.isnan(curr):
        return False
    return prev > level and curr <= level


# ========================================
# RSI + MA200 STRATEGY
# ========================================

class RSIma200Strategy:
    """
    RSI + MA200 Strategy implementation.
    
    Entry conditions:
        BUY:  Close > MA200 (uptrend) AND RSI crosses up through 30
        SELL: Close <= MA200 (downtrend) AND RSI crosses down through 70
        
    Additional long filter:
        Price must be above MA30, MA50, and MA200 for longs.
    """

    def __init__(self, config: RSIStrategyConfig):
        self.config = config
        self.enabled = config.enabled

    def evaluate(
        self,
        indicators: Indicators,
        symbol: str,
        timeframe: str,
        long_only_above_ma: Optional[list] = None,
    ) -> StrategySignal:
        """
        Evaluate the RSI + MA200 strategy on current indicators.
        
        Args:
            indicators: Computed indicators for the symbol/timeframe
            symbol: Trading pair
            timeframe: Candle timeframe
            long_only_above_ma: List of MA periods price must be above for longs
            
        Returns:
            StrategySignal with signal type and metadata
        """
        if not self.enabled:
            return self._no_signal(symbol, timeframe, indicators)

        # Validate we have enough data
        if np.isnan(indicators.last_rsi) or np.isnan(indicators.last_sma_200):
            logger.debug(f"{symbol} {timeframe}: Insufficient data for RSI/MA200")
            return self._no_signal(symbol, timeframe, indicators)

        close = indicators.last_close
        rsi = indicators.rsi
        sma200 = indicators.last_sma_200

        # Determine trend
        trend_up = close > sma200
        trend_down = close <= sma200

        # Check WARNING first (informational)
        warning = self._check_warning(indicators)

        # Check BUY signal
        if trend_up and crossover(rsi, self.config.rsi_oversold):
            # Additional MA filter for longs
            if long_only_above_ma and not self._price_above_all_ma(indicators, long_only_above_ma):
                logger.debug(
                    f"{symbol} {timeframe}: BUY signal suppressed - "
                    f"price not above all required MAs"
                )
                # Still return warning if present
                if warning:
                    return warning
                return self._no_signal(symbol, timeframe, indicators)

            signal = StrategySignal(
                signal_type=SignalType.BUY,
                symbol=symbol,
                timeframe=timeframe,
                price=close,
                reason=(
                    f"RSI({indicators.last_rsi:.1f}) crossed above {self.config.rsi_oversold} "
                    f"in UPTREND (close {close:.4f} > MA200 {sma200:.4f})"
                ),
                strength=self._compute_buy_strength(indicators),
                rsi_value=indicators.last_rsi,
                ma200_value=sma200,
            )
            logger.info(f"🟢 BUY SIGNAL | {symbol} {timeframe} | {signal.reason}")
            return signal

        # Check SELL signal
        if trend_down and crossunder(rsi, self.config.rsi_overbought):
            signal = StrategySignal(
                signal_type=SignalType.SELL,
                symbol=symbol,
                timeframe=timeframe,
                price=close,
                reason=(
                    f"RSI({indicators.last_rsi:.1f}) crossed below {self.config.rsi_overbought} "
                    f"in DOWNTREND (close {close:.4f} <= MA200 {sma200:.4f})"
                ),
                strength=self._compute_sell_strength(indicators),
                rsi_value=indicators.last_rsi,
                ma200_value=sma200,
            )
            logger.info(f"🔴 SELL SIGNAL | {symbol} {timeframe} | {signal.reason}")
            return signal

        # Return warning if present
        if warning:
            return warning

        return self._no_signal(symbol, timeframe, indicators)

    def _check_warning(self, indicators: Indicators) -> Optional[StrategySignal]:
        """
        Check for WARNING signal.
        WARNING: RSI was >= overbought on prev bar, now falling, and still > overbought.
        """
        if len(indicators.rsi) < 2:
            return None

        prev_rsi = indicators.prev_rsi
        curr_rsi = indicators.last_rsi

        if np.isnan(prev_rsi) or np.isnan(curr_rsi):
            return None

        overbought = self.config.rsi_overbought

        # RSI was >= overbought, now falling, still above overbought
        if prev_rsi >= overbought and curr_rsi < prev_rsi and curr_rsi > overbought:
            signal = StrategySignal(
                signal_type=SignalType.WARNING,
                symbol="",  # will be set by caller
                timeframe="",
                price=indicators.last_close,
                reason=(
                    f"RSI falling from overbought: {prev_rsi:.1f} -> {curr_rsi:.1f} "
                    f"(still above {overbought}). Potential reversal."
                ),
                strength=0.5,
                rsi_value=curr_rsi,
                ma200_value=indicators.last_sma_200,
            )
            return signal

        return None

    def _price_above_all_ma(self, indicators: Indicators, ma_periods: list) -> bool:
        """Check if price is above all specified moving averages."""
        close = indicators.last_close
        ma_map = {
            30: indicators.last_sma_30,
            50: indicators.last_sma_50,
            200: indicators.last_sma_200,
        }

        for period in ma_periods:
            ma_val = ma_map.get(period)
            if ma_val is None or np.isnan(ma_val):
                continue  # Skip if MA not available (insufficient data)
            if close <= ma_val:
                return False

        return True

    def _compute_buy_strength(self, indicators: Indicators) -> float:
        """
        Compute signal strength (0-1) for a BUY signal.
        Stronger when RSI is deeply oversold and price is well above MA200.
        """
        rsi = indicators.last_rsi
        # RSI closer to 0 = stronger buy signal
        rsi_strength = max(0, (self.config.rsi_oversold - rsi + 10) / 40)  # 0-1 range

        # Price distance above MA200
        close = indicators.last_close
        ma200 = indicators.last_sma_200
        if ma200 > 0:
            distance_pct = (close - ma200) / ma200 * 100
            trend_strength = min(1.0, distance_pct / 5.0)  # cap at 5%
        else:
            trend_strength = 0.5

        return min(1.0, (rsi_strength + trend_strength) / 2)

    def _compute_sell_strength(self, indicators: Indicators) -> float:
        """
        Compute signal strength (0-1) for a SELL signal.
        Stronger when RSI is deeply overbought and price is well below MA200.
        """
        rsi = indicators.last_rsi
        # RSI closer to 100 = stronger sell signal
        rsi_strength = max(0, (rsi - self.config.rsi_overbought + 10) / 40)

        # Price distance below MA200
        close = indicators.last_close
        ma200 = indicators.last_sma_200
        if ma200 > 0:
            distance_pct = (ma200 - close) / ma200 * 100
            trend_strength = min(1.0, distance_pct / 5.0)
        else:
            trend_strength = 0.5

        return min(1.0, (rsi_strength + trend_strength) / 2)

    def _no_signal(self, symbol: str, timeframe: str, indicators: Indicators) -> StrategySignal:
        """Return a NONE signal."""
        return StrategySignal(
            signal_type=SignalType.NONE,
            symbol=symbol,
            timeframe=timeframe,
            price=indicators.last_close if indicators is not None else 0.0,
            reason="No signal",
            rsi_value=indicators.last_rsi if indicators is not None else 0.0,
            ma200_value=indicators.last_sma_200 if indicators is not None else 0.0,
        )
