"""
Combined Confluence Strategy Module
====================================

Merges signals from Strategy 1 (RSI + MA200) and Strategy 2 (Bollinger Bands).

Rules:
1. CONFLUENCE MODE: Both strategies must agree on direction for a trade entry.
2. SIDEWAYS OVERRIDE: When BB detects sideways market, switch to mean-reversion
   mode on BB signals alone (RSI is used as a confirming filter, not required).
3. MA FILTER: Longs only when price > MA30, MA50, and MA200.
4. WARNING SIGNALS: Passed through from RSI strategy for risk management.
"""

from dataclasses import dataclass
from typing import Optional, List

from src.strategy.rsi_ma200 import RSIma200Strategy, StrategySignal, SignalType
from src.strategy.bollinger_bands import BollingerBandsStrategy, MarketRegime
from src.data.market_data import Indicators
from config.settings import BotConfig
from src.utils.logger import get_logger

logger = get_logger("strategy.confluence")


@dataclass
class ConfluenceSignal:
    """
    Final trade signal after confluence evaluation.
    Contains combined information from both strategies.
    """
    signal_type: SignalType
    symbol: str
    timeframe: str
    price: float
    reason: str
    strength: float  # Combined strength (0-1)
    market_regime: MarketRegime
    rsi_signal: Optional[StrategySignal] = None
    bb_signal: Optional[StrategySignal] = None
    is_mean_reversion: bool = False  # True if sideways mean-reversion trade

    @property
    def is_actionable(self) -> bool:
        """Whether this signal should trigger a trade."""
        return self.signal_type in (SignalType.BUY, SignalType.SELL)

    @property
    def is_warning(self) -> bool:
        """Whether this is a warning signal for risk management."""
        return self.signal_type == SignalType.WARNING


class ConfluenceEngine:
    """
    Merges both strategies into a single decision engine.
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self.require_both = config.confluence.require_both
        self.sideways_mean_reversion = config.confluence.sideways_mean_reversion
        self.long_only_above_ma = config.trading.long_only_above_ma

        # Initialize both strategies
        self.rsi_strategy = RSIma200Strategy(config.strategy_rsi_ma200)
        self.bb_strategy = BollingerBandsStrategy(
            config.strategy_bollinger,
            sideways_mean_reversion=self.sideways_mean_reversion,
        )

    def evaluate(
        self,
        indicators: Indicators,
        symbol: str,
        timeframe: str,
    ) -> ConfluenceSignal:
        """
        Evaluate both strategies and produce a confluence signal.
        
        Logic:
        1. If market is SIDEWAYS and mean-reversion is enabled:
           → Use BB mean-reversion signals, with RSI as optional confirmation
        2. If market is TRENDING:
           → Require BOTH strategies to agree (if require_both=True)
        3. MA filter for longs always applies
        4. WARNING signals always pass through
        
        Args:
            indicators: Computed indicators
            symbol: Trading pair
            timeframe: Candle timeframe
            
        Returns:
            ConfluenceSignal with final decision
        """
        # Evaluate both strategies independently
        rsi_signal = self.rsi_strategy.evaluate(
            indicators, symbol, timeframe,
            long_only_above_ma=self.long_only_above_ma,
        )
        bb_signal = self.bb_strategy.evaluate(indicators, symbol, timeframe)

        # Get current market regime
        regime = self.bb_strategy.get_regime(symbol, timeframe)

        # --- Handle WARNING signals (always pass through) ---
        if rsi_signal.signal_type == SignalType.WARNING:
            return ConfluenceSignal(
                signal_type=SignalType.WARNING,
                symbol=symbol,
                timeframe=timeframe,
                price=indicators.last_close,
                reason=rsi_signal.reason,
                strength=rsi_signal.strength,
                market_regime=regime,
                rsi_signal=rsi_signal,
                bb_signal=bb_signal,
                is_mean_reversion=False,
            )

        # --- SIDEWAYS MODE: Mean-reversion override ---
        if regime == MarketRegime.SIDEWAYS and self.sideways_mean_reversion:
            return self._evaluate_sideways(
                rsi_signal, bb_signal, indicators, symbol, timeframe, regime
            )

        # --- TRENDING MODE: Confluence required ---
        return self._evaluate_trending(
            rsi_signal, bb_signal, indicators, symbol, timeframe, regime
        )

    def _evaluate_trending(
        self,
        rsi_signal: StrategySignal,
        bb_signal: StrategySignal,
        indicators: Indicators,
        symbol: str,
        timeframe: str,
        regime: MarketRegime,
    ) -> ConfluenceSignal:
        """
        Trending market evaluation.
        Requires both strategies to agree for a valid signal.
        """
        # Both must agree
        if self.require_both:
            # BUY: both say BUY
            if (rsi_signal.signal_type == SignalType.BUY and 
                bb_signal.signal_type == SignalType.BUY):

                # Apply MA filter for longs
                if not self._check_long_filter(indicators):
                    return self._no_signal(symbol, timeframe, indicators, regime)

                combined_strength = (rsi_signal.strength + bb_signal.strength) / 2
                return ConfluenceSignal(
                    signal_type=SignalType.BUY,
                    symbol=symbol,
                    timeframe=timeframe,
                    price=indicators.last_close,
                    reason=(
                        f"CONFLUENCE BUY | RSI: {rsi_signal.reason} | "
                        f"BB: {bb_signal.reason}"
                    ),
                    strength=combined_strength,
                    market_regime=regime,
                    rsi_signal=rsi_signal,
                    bb_signal=bb_signal,
                    is_mean_reversion=False,
                )

            # SELL: both say SELL
            if (rsi_signal.signal_type == SignalType.SELL and 
                bb_signal.signal_type == SignalType.SELL):

                combined_strength = (rsi_signal.strength + bb_signal.strength) / 2
                return ConfluenceSignal(
                    signal_type=SignalType.SELL,
                    symbol=symbol,
                    timeframe=timeframe,
                    price=indicators.last_close,
                    reason=(
                        f"CONFLUENCE SELL | RSI: {rsi_signal.reason} | "
                        f"BB: {bb_signal.reason}"
                    ),
                    strength=combined_strength,
                    market_regime=regime,
                    rsi_signal=rsi_signal,
                    bb_signal=bb_signal,
                    is_mean_reversion=False,
                )

        else:
            # Either strategy can trigger (less strict)
            if rsi_signal.signal_type == SignalType.BUY or bb_signal.signal_type == SignalType.BUY:
                active = rsi_signal if rsi_signal.signal_type == SignalType.BUY else bb_signal
                if not self._check_long_filter(indicators):
                    return self._no_signal(symbol, timeframe, indicators, regime)
                return ConfluenceSignal(
                    signal_type=SignalType.BUY,
                    symbol=symbol,
                    timeframe=timeframe,
                    price=indicators.last_close,
                    reason=f"SINGLE BUY | {active.reason}",
                    strength=active.strength * 0.7,  # Lower strength for single
                    market_regime=regime,
                    rsi_signal=rsi_signal,
                    bb_signal=bb_signal,
                    is_mean_reversion=False,
                )

            if rsi_signal.signal_type == SignalType.SELL or bb_signal.signal_type == SignalType.SELL:
                active = rsi_signal if rsi_signal.signal_type == SignalType.SELL else bb_signal
                return ConfluenceSignal(
                    signal_type=SignalType.SELL,
                    symbol=symbol,
                    timeframe=timeframe,
                    price=indicators.last_close,
                    reason=f"SINGLE SELL | {active.reason}",
                    strength=active.strength * 0.7,
                    market_regime=regime,
                    rsi_signal=rsi_signal,
                    bb_signal=bb_signal,
                    is_mean_reversion=False,
                )

        return self._no_signal(symbol, timeframe, indicators, regime)

    def _evaluate_sideways(
        self,
        rsi_signal: StrategySignal,
        bb_signal: StrategySignal,
        indicators: Indicators,
        symbol: str,
        timeframe: str,
        regime: MarketRegime,
    ) -> ConfluenceSignal:
        """
        Sideways market evaluation — mean-reversion mode.
        BB signal is primary, RSI provides optional confirmation.
        """
        if bb_signal.signal_type == SignalType.BUY:
            # Mean-reversion BUY at lower band
            # RSI confirmation: ideally RSI should be in oversold territory
            rsi_confirms = (
                rsi_signal.rsi_value < 50  # at least below midline
            )
            strength = bb_signal.strength
            if rsi_confirms:
                strength = min(1.0, strength + 0.2)

            # Still apply MA filter for longs
            if not self._check_long_filter(indicators):
                return self._no_signal(symbol, timeframe, indicators, regime)

            return ConfluenceSignal(
                signal_type=SignalType.BUY,
                symbol=symbol,
                timeframe=timeframe,
                price=indicators.last_close,
                reason=(
                    f"SIDEWAYS MEAN-REVERSION BUY | BB: {bb_signal.reason} | "
                    f"RSI confirms: {rsi_confirms} (RSI={rsi_signal.rsi_value:.1f})"
                ),
                strength=strength,
                market_regime=regime,
                rsi_signal=rsi_signal,
                bb_signal=bb_signal,
                is_mean_reversion=True,
            )

        if bb_signal.signal_type == SignalType.SELL:
            # Mean-reversion SELL at upper band
            rsi_confirms = (
                rsi_signal.rsi_value > 50
            )
            strength = bb_signal.strength
            if rsi_confirms:
                strength = min(1.0, strength + 0.2)

            return ConfluenceSignal(
                signal_type=SignalType.SELL,
                symbol=symbol,
                timeframe=timeframe,
                price=indicators.last_close,
                reason=(
                    f"SIDEWAYS MEAN-REVERSION SELL | BB: {bb_signal.reason} | "
                    f"RSI confirms: {rsi_confirms} (RSI={rsi_signal.rsi_value:.1f})"
                ),
                strength=strength,
                market_regime=regime,
                rsi_signal=rsi_signal,
                bb_signal=bb_signal,
                is_mean_reversion=True,
            )

        return self._no_signal(symbol, timeframe, indicators, regime)

    def _check_long_filter(self, indicators: Indicators) -> bool:
        """
        Check MA filter: price must be above MA30, MA50, MA200 for longs.
        """
        import numpy as np

        close = indicators.last_close
        ma_values = {
            30: indicators.last_sma_30,
            50: indicators.last_sma_50,
            200: indicators.last_sma_200,
        }

        for period in self.long_only_above_ma:
            ma_val = ma_values.get(period)
            if ma_val is None or np.isnan(ma_val):
                continue  # Skip if not enough data
            if close <= ma_val:
                logger.debug(
                    f"Long filter BLOCKED: close {close:.4f} <= MA{period} {ma_val:.4f}"
                )
                return False

        return True

    def _no_signal(
        self,
        symbol: str,
        timeframe: str,
        indicators: Indicators,
        regime: MarketRegime,
    ) -> ConfluenceSignal:
        """Return no-action signal."""
        return ConfluenceSignal(
            signal_type=SignalType.NONE,
            symbol=symbol,
            timeframe=timeframe,
            price=indicators.last_close,
            reason="No confluence signal",
            strength=0.0,
            market_regime=regime,
            is_mean_reversion=False,
        )
