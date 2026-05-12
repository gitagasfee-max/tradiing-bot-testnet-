"""
Risk Management Module
=======================

Handles:
- Position sizing (3% for futures, 25% for spot)
- Stop-loss and take-profit calculation
- Max open positions enforcement
- Daily loss tracking and circuit breaker
- Cooldown between trades on same pair
- WARNING signal → tighten SL by 50%
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from datetime import datetime, timezone

from config.settings import BotConfig, FuturesRiskConfig, SpotRiskConfig
from src.strategy.confluence import ConfluenceSignal
from src.strategy.rsi_ma200 import SignalType
from src.exchange.client import BinanceClient, Position
from src.utils.logger import get_logger

logger = get_logger("risk")


# ========================================
# DATA STRUCTURES
# ========================================

@dataclass
class TradeOrder:
    """Represents a validated trade to be executed."""
    symbol: str
    side: str  # "buy" or "sell"
    amount: float  # position size in base currency
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    market_type: str  # "spot" or "futures"
    leverage: int = 1
    reason: str = ""
    signal_strength: float = 0.0
    is_mean_reversion: bool = False


@dataclass
class DailyPnL:
    """Track daily profit/loss."""
    date: str  # YYYY-MM-DD
    realized_pnl: float = 0.0
    trades_count: int = 0
    wins: int = 0
    losses: int = 0

    @property
    def win_rate(self) -> float:
        if self.trades_count == 0:
            return 0.0
        return self.wins / self.trades_count * 100


# ========================================
# RISK MANAGER
# ========================================

class RiskManager:
    """
    Manages all risk decisions before a trade is placed.
    Acts as the final gate between strategy signals and order execution.
    """

    def __init__(self, config: BotConfig, client: BinanceClient):
        self.config = config
        self.client = client

        # Track open positions per market type
        self._open_positions: Dict[str, List[Position]] = {
            "spot": [],
            "futures": [],
        }

        # Track last trade time per (symbol, market_type) for cooldown
        self._last_trade_time: Dict[tuple, float] = {}

        # Daily P&L tracking
        self._daily_pnl: DailyPnL = DailyPnL(date=self._today())

        # Track capital at start of day for daily loss calculation
        self._daily_start_balance: Dict[str, float] = {}

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _reset_daily_if_new_day(self) -> None:
        """Reset daily tracking if it's a new day."""
        today = self._today()
        if self._daily_pnl.date != today:
            logger.info(
                f"New day detected. Yesterday's P&L: "
                f"${self._daily_pnl.realized_pnl:.2f} | "
                f"Trades: {self._daily_pnl.trades_count} | "
                f"Win rate: {self._daily_pnl.win_rate:.1f}%"
            )
            self._daily_pnl = DailyPnL(date=today)
            self._daily_start_balance = {}

    # ========================================
    # MAIN VALIDATION METHOD
    # ========================================

    def validate_trade(
        self,
        signal: ConfluenceSignal,
        market_type: str = "futures",
    ) -> Optional[TradeOrder]:
        """
        Validate a confluence signal against all risk rules.
        
        Returns:
            TradeOrder if trade is approved, None if rejected.
        """
        self._reset_daily_if_new_day()

        symbol = signal.symbol
        side = "buy" if signal.signal_type == SignalType.BUY else "sell"

        # --- Check 1: Is signal actionable? ---
        if not signal.is_actionable:
            return None

        # --- Check 2: Cooldown ---
        if self._is_on_cooldown(symbol, market_type):
            logger.info(f"BLOCKED: {symbol} on cooldown ({self.config.risk.cooldown_seconds}s)")
            return None

        # --- Check 3: Max open positions ---
        if self._exceeds_max_positions(market_type):
            risk_config = self._get_risk_config(market_type)
            logger.info(
                f"BLOCKED: Max positions reached ({risk_config.max_open_positions}) "
                f"for {market_type}"
            )
            return None

        # --- Check 4: Daily loss limit ---
        if self._daily_loss_exceeded(market_type):
            logger.warning(f"BLOCKED: Daily loss limit reached for {market_type}")
            return None

        # --- Check 5: Already in position for this symbol? ---
        if self._has_open_position(symbol, market_type):
            logger.info(f"BLOCKED: Already have open position for {symbol} ({market_type})")
            return None

        # --- Check 6: Calculate position size ---
        trade_order = self._calculate_trade(signal, market_type, side)
        if trade_order is None:
            return None

        logger.info(
            f"✅ TRADE APPROVED | {symbol} {side.upper()} | "
            f"Amount: {trade_order.amount:.6f} | "
            f"Entry: {trade_order.entry_price:.4f} | "
            f"SL: {trade_order.stop_loss_price:.4f} | "
            f"TP: {trade_order.take_profit_price:.4f} | "
            f"Market: {market_type}"
        )

        return trade_order

    # ========================================
    # POSITION SIZING
    # ========================================

    def _calculate_trade(
        self,
        signal: ConfluenceSignal,
        market_type: str,
        side: str,
    ) -> Optional[TradeOrder]:
        """
        Calculate position size, SL, and TP for a trade.
        """
        risk_config = self._get_risk_config(market_type)
        entry_price = signal.price

        if entry_price <= 0:
            logger.error(f"Invalid entry price: {entry_price}")
            return None

        # Get available balance
        try:
            free_balance = self.client.get_free_balance("USDT", market_type)
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return None

        if free_balance <= 0:
            logger.warning(f"No free balance available for {market_type}")
            return None

        # Calculate position value
        risk_pct = risk_config.risk_per_trade_pct / 100.0
        position_value_usdt = free_balance * risk_pct

        # For futures, apply leverage
        leverage = 1
        if market_type == "futures":
            leverage = self.config.risk.futures.leverage
            position_value_usdt *= leverage

        # Convert to base currency amount
        amount = position_value_usdt / entry_price

        # Check minimum order size
        try:
            min_amount = self.client.get_min_order_amount(signal.symbol, market_type)
            if amount < min_amount:
                logger.warning(
                    f"Position too small: {amount:.6f} < min {min_amount:.6f} for {signal.symbol}"
                )
                return None
        except Exception:
            pass  # If can't fetch min, proceed anyway

        # Round to exchange precision
        try:
            precision = self.client.get_amount_precision(signal.symbol, market_type)
            amount = round(amount, precision)
        except Exception:
            amount = round(amount, 6)

        # Calculate SL and TP
        sl_pct = risk_config.stop_loss_pct / 100.0
        tp_pct = risk_config.take_profit_pct / 100.0

        if side == "buy":
            stop_loss_price = entry_price * (1 - sl_pct)
            take_profit_price = entry_price * (1 + tp_pct)
        else:  # sell/short
            stop_loss_price = entry_price * (1 + sl_pct)
            take_profit_price = entry_price * (1 - tp_pct)

        # Round prices
        try:
            price_precision = self.client.get_price_precision(signal.symbol, market_type)
            stop_loss_price = round(stop_loss_price, price_precision)
            take_profit_price = round(take_profit_price, price_precision)
        except Exception:
            stop_loss_price = round(stop_loss_price, 4)
            take_profit_price = round(take_profit_price, 4)

        return TradeOrder(
            symbol=signal.symbol,
            side=side,
            amount=amount,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            market_type=market_type,
            leverage=leverage,
            reason=signal.reason,
            signal_strength=signal.strength,
            is_mean_reversion=signal.is_mean_reversion,
        )

    # ========================================
    # WARNING SIGNAL HANDLING
    # ========================================

    def handle_warning(self, signal: ConfluenceSignal, market_type: str = "futures") -> Optional[float]:
        """
        Handle a WARNING signal by tightening the stop-loss.
        
        Returns:
            New stop-loss price if tightened, None otherwise.
        """
        if not self.config.risk.warning_tightens_sl:
            return None

        symbol = signal.symbol

        # Find open position for this symbol
        positions = self._get_positions_for_symbol(symbol, market_type)
        if not positions:
            return None

        for pos in positions:
            if pos.side == "long":
                # Tighten SL: move it 50% closer to entry
                current_price = signal.price
                entry = pos.entry_price
                risk_config = self._get_risk_config(market_type)
                original_sl = entry * (1 - risk_config.stop_loss_pct / 100.0)
                
                # New SL is halfway between original SL and entry
                new_sl = (original_sl + entry) / 2
                
                logger.warning(
                    f"⚠️ WARNING: Tightening SL for {symbol} LONG | "
                    f"Original SL: {original_sl:.4f} → New SL: {new_sl:.4f}"
                )
                return new_sl

        return None

    # ========================================
    # POSITION TRACKING
    # ========================================

    def refresh_positions(self, market_type: str = "futures") -> None:
        """Refresh open positions from the exchange."""
        try:
            if market_type == "futures":
                positions = self.client.fetch_positions()
                self._open_positions["futures"] = positions
            # For spot, we track manually
        except Exception as e:
            logger.error(f"Failed to refresh positions: {e}")

    def record_trade_opened(self, symbol: str, market_type: str) -> None:
        """Record that a trade was opened (for cooldown tracking)."""
        self._last_trade_time[(symbol, market_type)] = time.time()

    def record_trade_closed(self, pnl: float, market_type: str) -> None:
        """Record a closed trade for daily P&L tracking."""
        self._daily_pnl.realized_pnl += pnl
        self._daily_pnl.trades_count += 1
        if pnl >= 0:
            self._daily_pnl.wins += 1
        else:
            self._daily_pnl.losses += 1

    # ========================================
    # INTERNAL CHECKS
    # ========================================

    def _is_on_cooldown(self, symbol: str, market_type: str) -> bool:
        """Check if symbol is on cooldown."""
        key = (symbol, market_type)
        last_time = self._last_trade_time.get(key, 0)
        elapsed = time.time() - last_time
        return elapsed < self.config.risk.cooldown_seconds

    def _exceeds_max_positions(self, market_type: str) -> bool:
        """Check if max open positions is reached."""
        risk_config = self._get_risk_config(market_type)
        current = len(self._open_positions.get(market_type, []))
        return current >= risk_config.max_open_positions

    def _daily_loss_exceeded(self, market_type: str) -> bool:
        """Check if daily loss limit is exceeded."""
        risk_config = self._get_risk_config(market_type)
        max_loss_pct = risk_config.max_daily_loss_pct

        # Get starting balance for today
        if market_type not in self._daily_start_balance:
            try:
                balance = self.client.get_free_balance("USDT", market_type)
                self._daily_start_balance[market_type] = balance
            except Exception:
                return False  # Can't check, allow trading

        start_balance = self._daily_start_balance.get(market_type, 0)
        if start_balance <= 0:
            return False

        daily_loss_pct = abs(min(0, self._daily_pnl.realized_pnl)) / start_balance * 100
        return daily_loss_pct >= max_loss_pct

    def _has_open_position(self, symbol: str, market_type: str) -> bool:
        """Check if we already have an open position for this symbol."""
        positions = self._open_positions.get(market_type, [])
        for pos in positions:
            if pos.symbol == symbol:
                return True
        return False

    def _get_positions_for_symbol(self, symbol: str, market_type: str) -> List[Position]:
        """Get all positions for a symbol."""
        positions = self._open_positions.get(market_type, [])
        return [p for p in positions if p.symbol == symbol]

    def _get_risk_config(self, market_type: str):
        """Get the appropriate risk config for market type."""
        if market_type == "futures":
            return self.config.risk.futures
        return self.config.risk.spot

    # ========================================
    # DAILY SUMMARY
    # ========================================

    def get_daily_summary(self) -> Dict:
        """Get daily trading summary."""
        return {
            "date": self._daily_pnl.date,
            "pnl": self._daily_pnl.realized_pnl,
            "trades": self._daily_pnl.trades_count,
            "wins": self._daily_pnl.wins,
            "losses": self._daily_pnl.losses,
            "win_rate": self._daily_pnl.win_rate,
        }
