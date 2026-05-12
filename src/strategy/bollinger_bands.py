"""
Strategy 2: Bollinger Bands Trend Detection
=============================================

Logic (translated from Pine Script):

Trend State Machine:
- If close > previous bar's upper band → trend = UP (+1)
- If close < previous bar's lower band → trend = DOWN (-1)
- Otherwise → trend persists (same as previous bar)

Sideways Detection:
- isSideways = |upper - lower| <= 0.5 * ATR(14)
  (Very tight bands = consolidation / no-trade zone)

Entry Signals (BREAKOUT MODE - normal trending market):
- BUY:  close > previous bar's upper band (breakout up)
- SELL: close < previous bar's lower band (breakout down)

Entry Signals (MEAN-REVERSION MODE - sideways market):
- BUY:  price crosses up through lower band (buy the dip)
- SELL: price crosses down through upper band (sell the rip)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

from src.data.market_data import Indicators
from config.settings import BollingerStrategyConfig
from src.strategy.rsi_ma200 import SignalType, StrategySignal, crossover, crossunder
from src.utils.logger import get_logger

logger = get_logger("strategy.bollinger")


# ========================================
# BOLLINGER BANDS STRATEGY
# ========================================

class MarketRegime(Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    SIDEWAYS = "SIDEWAYS"


@dataclass
class BBState:
    """Persistent state for BB trend tracking."""
    trend: int = 0  # +1 = up, -1 = down, 0 = neutral
    regime: MarketRegime = MarketRegime.SIDEWAYS


class BollingerBandsStrategy:
    """
    Bollinger Bands Trend Detection Strategy.
    
    In trending markets: Breakout entries (close > prev upper = long).
    In sideways markets: Mean-reversion entries (buy lower, sell upper).
    """

    def __init__(self, config: BollingerStrategyConfig, sideways_mean_reversion: bool = True):
        self.config = config
        self.enabled = config.enabled
        self.sideways_mean_reversion = sideways_mean_reversion
        # Per-symbol state tracking
        self._states: dict = {}  # {(symbol, timeframe): BBState}

    def get_state(self, symbol: str, timeframe: str) -> BBState:
        """Get or create BB state for a symbol/timeframe."""
        key = (symbol, timeframe)
        if key not in self._states:
            self._states[key] = BBState()
        return self._states[key]

    def evaluate(
        self,
        indicators: Indicators,
        symbol: str,
        timeframe: str,
    ) -> StrategySignal:
        """
        Evaluate the Bollinger Bands strategy.
        
        Args:
            indicators: Computed indicators
            symbol: Trading pair
            timeframe: Candle timeframe
            
        Returns:
            StrategySignal with signal type and metadata
        """
        if not self.enabled:
            return self._no_signal(symbol, timeframe, indicators)

        # Validate data
        if (np.isnan(indicators.last_bb_upper) or 
            np.isnan(indicators.last_bb_lower) or
            np.isnan(indicators.last_atr)):
            logger.debug(f"{symbol} {timeframe}: Insufficient data for BB")
            return self._no_signal(symbol, timeframe, indicators)

        state = self.get_state(symbol, timeframe)
        close = indicators.last_close
        prev_upper = indicators.prev_bb_upper
        prev_lower = indicators.prev_bb_lower

        # ---- Update trend state machine ----
        if close > prev_upper:
            state.trend = 1
        elif close < prev_lower:
            state.trend = -1
        # else: trend persists

        # ---- Detect sideways market ----
        bb_width = indicators.last_bb_width
        atr = indicators.last_atr
        is_sideways = bb_width <= (self.config.sideways_atr_mult * atr)

        if is_sideways:
            state.regime = MarketRegime.SIDEWAYS
        elif state.trend == 1:
            state.regime = MarketRegime.TRENDING_UP
        else:
            state.regime = MarketRegime.TRENDING_DOWN

        # ---- Generate signals based on regime ----
        if is_sideways and self.sideways_mean_reversion:
            return self._evaluate_mean_reversion(indicators, symbol, timeframe, state)
        else:
            return self._evaluate_breakout(indicators, symbol, timeframe, state)

    def _evaluate_breakout(
        self,
        indicators: Indicators,
        symbol: str,
        timeframe: str,
        state: BBState,
    ) -> StrategySignal:
        """
        Breakout mode: enter when close breaks previous bar's band.
        """
        close = indicators.last_close
        prev_close = indicators.prev_close
        prev_upper = indicators.prev_bb_upper
        prev_lower = indicators.prev_bb_lower

        # BUY: close breaks above previous upper band
        if close > prev_upper and prev_close <= prev_upper:
            signal = StrategySignal(
                signal_type=SignalType.BUY,
                symbol=symbol,
                timeframe=timeframe,
                price=close,
                reason=(
                    f"BB BREAKOUT UP: close {close:.4f} > prev upper {prev_upper:.4f} | "
                    f"Trend: {state.regime.value}"
                ),
                strength=self._compute_breakout_strength(indicators, "buy"),
                rsi_value=indicators.last_rsi if not np.isnan(indicators.last_rsi) else 0,
                ma200_value=indicators.last_sma_200 if not np.isnan(indicators.last_sma_200) else 0,
            )
            logger.info(f"🟢 BB BUY (breakout) | {symbol} {timeframe} | {signal.reason}")
            return signal

        # SELL: close breaks below previous lower band
        if close < prev_lower and prev_close >= prev_lower:
            signal = StrategySignal(
                signal_type=SignalType.SELL,
                symbol=symbol,
                timeframe=timeframe,
                price=close,
                reason=(
                    f"BB BREAKOUT DOWN: close {close:.4f} < prev lower {prev_lower:.4f} | "
                    f"Trend: {state.regime.value}"
                ),
                strength=self._compute_breakout_strength(indicators, "sell"),
                rsi_value=indicators.last_rsi if not np.isnan(indicators.last_rsi) else 0,
                ma200_value=indicators.last_sma_200 if not np.isnan(indicators.last_sma_200) else 0,
            )
            logger.info(f"🔴 BB SELL (breakout) | {symbol} {timeframe} | {signal.reason}")
            return signal

        return self._no_signal(symbol, timeframe, indicators)

    def _evaluate_mean_reversion(
        self,
        indicators: Indicators,
        symbol: str,
        timeframe: str,
        state: BBState,
    ) -> StrategySignal:
        """
        Mean-reversion mode (sideways market): buy at lower band, sell at upper band.
        """
        closes = indicators.close
        bb_lower = indicators.bb_lower
        bb_upper = indicators.bb_upper

        # Check if we have enough data for cross detection
        if len(closes) < 2 or len(bb_lower) < 2 or len(bb_upper) < 2:
            return self._no_signal(symbol, timeframe, indicators)

        # BUY: price crosses up through lower band (mean reversion buy)
        prev_close = float(closes[-2])
        curr_close = float(closes[-1])
        prev_lower = float(bb_lower[-2])
        curr_lower = float(bb_lower[-1])
        prev_upper = float(bb_upper[-2])
        curr_upper = float(bb_upper[-1])

        # Price was below lower band, now crossing above
        if prev_close <= prev_lower and curr_close > curr_lower:
            signal = StrategySignal(
                signal_type=SignalType.BUY,
                symbol=symbol,
                timeframe=timeframe,
                price=curr_close,
                reason=(
                    f"BB MEAN REVERSION BUY: price crossed above lower band "
                    f"({curr_close:.4f} > {curr_lower:.4f}) | SIDEWAYS market"
                ),
                strength=0.6,  # Mean reversion signals are moderate strength
                rsi_value=indicators.last_rsi if not np.isnan(indicators.last_rsi) else 0,
                ma200_value=indicators.last_sma_200 if not np.isnan(indicators.last_sma_200) else 0,
            )
            logger.info(f"🟢 BB BUY (mean-reversion) | {symbol} {timeframe} | {signal.reason}")
            return signal

        # SELL: price crosses down through upper band (mean reversion sell)
        if prev_close >= prev_upper and curr_close < curr_upper:
            signal = StrategySignal(
                signal_type=SignalType.SELL,
                symbol=symbol,
                timeframe=timeframe,
                price=curr_close,
                reason=(
                    f"BB MEAN REVERSION SELL: price crossed below upper band "
                    f"({curr_close:.4f} < {curr_upper:.4f}) | SIDEWAYS market"
                ),
                strength=0.6,
                rsi_value=indicators.last_rsi if not np.isnan(indicators.last_rsi) else 0,
                ma200_value=indicators.last_sma_200 if not np.isnan(indicators.last_sma_200) else 0,
            )
            logger.info(f"🔴 BB SELL (mean-reversion) | {symbol} {timeframe} | {signal.reason}")
            return signal

        return self._no_signal(symbol, timeframe, indicators)

    def _compute_breakout_strength(self, indicators: Indicators, direction: str) -> float:
        """
        Compute breakout signal strength.
        Stronger when: large candle, high volume, clear trend direction.
        """
        close = indicators.last_close
        bb_middle = indicators.last_bb_middle
        bb_width = indicators.last_bb_width

        if bb_width <= 0:
            return 0.5

        # Distance from middle band as % of band width
        distance_from_middle = abs(close - bb_middle) / bb_width
        strength = min(1.0, distance_from_middle * 2)

        return max(0.3, strength)  # minimum 0.3 for any valid signal

    def get_regime(self, symbol: str, timeframe: str) -> MarketRegime:
        """Get current market regime for a symbol."""
        state = self.get_state(symbol, timeframe)
        return state.regime

    def _no_signal(self, symbol: str, timeframe: str, indicators: Indicators) -> StrategySignal:
        """Return a NONE signal."""
        return StrategySignal(
            signal_type=SignalType.NONE,
            symbol=symbol,
            timeframe=timeframe,
            price=indicators.last_close if indicators is not None else 0.0,
            reason="No BB signal",
            rsi_value=indicators.last_rsi if (indicators is not None and not np.isnan(indicators.last_rsi)) else 0,
            ma200_value=indicators.last_sma_200 if (indicators is not None and not np.isnan(indicators.last_sma_200)) else 0,
        )
