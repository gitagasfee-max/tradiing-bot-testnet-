"""
Order Executor Module
======================

Handles:
- Placing market orders with SL/TP
- Managing open orders
- Position closure
- Fill tracking and confirmation
"""

import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from src.exchange.client import BinanceClient, ExchangeError, Position
from src.risk.risk_manager import TradeOrder, RiskManager
from config.settings import BotConfig
from src.utils.logger import get_logger

logger = get_logger("executor")


# ========================================
# DATA STRUCTURES
# ========================================

@dataclass
class ActiveTrade:
    """Tracks an active trade with its associated orders."""
    symbol: str
    side: str
    market_type: str
    entry_order_id: str
    entry_price: float
    amount: float
    stop_loss_order_id: Optional[str] = None
    take_profit_order_id: Optional[str] = None
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    timestamp: float = field(default_factory=time.time)
    status: str = "open"  # "open", "closed", "error"
    exit_price: Optional[float] = None
    pnl: Optional[float] = None


# ========================================
# ORDER EXECUTOR
# ========================================

class OrderExecutor:
    """
    Executes validated trades on the exchange.
    Manages the full lifecycle: entry → SL/TP placement → exit tracking.
    """

    def __init__(self, config: BotConfig, client: BinanceClient, risk_manager: RiskManager):
        self.config = config
        self.client = client
        self.risk_manager = risk_manager
        
        # Track active trades: {symbol: ActiveTrade}
        self._active_trades: Dict[str, ActiveTrade] = {}

    # ========================================
    # EXECUTE TRADE
    # ========================================

    def execute_trade(self, trade_order: TradeOrder) -> Optional[ActiveTrade]:
        """
        Execute a validated trade order.
        
        Steps:
        1. Set leverage (futures only)
        2. Place market entry order
        3. Place stop-loss order
        4. Place take-profit order
        5. Track the trade
        
        Returns:
            ActiveTrade if successful, None if failed.
        """
        symbol = trade_order.symbol
        market_type = trade_order.market_type

        try:
            # Step 1: Set leverage for futures
            if market_type == "futures":
                try:
                    self.client.set_leverage(symbol, trade_order.leverage)
                    self.client.set_margin_mode(symbol, "isolated")
                except Exception as e:
                    logger.warning(f"Could not set leverage/margin: {e} (continuing)")

            # Step 2: Place entry order
            logger.info(
                f"📤 EXECUTING: {trade_order.side.upper()} {trade_order.amount} "
                f"{symbol} @ market | SL: {trade_order.stop_loss_price} | "
                f"TP: {trade_order.take_profit_price}"
            )

            entry_order = self.client.place_market_order(
                symbol=symbol,
                side=trade_order.side,
                amount=trade_order.amount,
                market_type=market_type,
            )

            entry_order_id = entry_order.get("id", "unknown")
            # Get actual fill price
            fill_price = float(entry_order.get("average", 0) or entry_order.get("price", 0) or trade_order.entry_price)

            logger.info(
                f"✅ ENTRY FILLED | {symbol} {trade_order.side.upper()} | "
                f"ID: {entry_order_id} | Fill: {fill_price}"
            )

            # Step 3: Place stop-loss
            sl_order_id = None
            try:
                sl_side = "sell" if trade_order.side == "buy" else "buy"
                sl_order = self.client.place_stop_loss(
                    symbol=symbol,
                    side=sl_side,
                    amount=trade_order.amount,
                    stop_price=trade_order.stop_loss_price,
                    market_type=market_type,
                )
                sl_order_id = sl_order.get("id")
                logger.info(f"🛡️ SL placed: {trade_order.stop_loss_price} | ID: {sl_order_id}")
            except Exception as e:
                logger.error(f"Failed to place SL for {symbol}: {e}")

            # Step 4: Place take-profit
            tp_order_id = None
            try:
                tp_side = "sell" if trade_order.side == "buy" else "buy"
                tp_order = self.client.place_take_profit(
                    symbol=symbol,
                    side=tp_side,
                    amount=trade_order.amount,
                    tp_price=trade_order.take_profit_price,
                    market_type=market_type,
                )
                tp_order_id = tp_order.get("id")
                logger.info(f"🎯 TP placed: {trade_order.take_profit_price} | ID: {tp_order_id}")
            except Exception as e:
                logger.error(f"Failed to place TP for {symbol}: {e}")

            # Step 5: Track the trade
            active_trade = ActiveTrade(
                symbol=symbol,
                side=trade_order.side,
                market_type=market_type,
                entry_order_id=entry_order_id,
                entry_price=fill_price,
                amount=trade_order.amount,
                stop_loss_order_id=sl_order_id,
                stop_loss_price=trade_order.stop_loss_price,
                take_profit_order_id=tp_order_id,
                take_profit_price=trade_order.take_profit_price,
            )

            self._active_trades[symbol] = active_trade
            self.risk_manager.record_trade_opened(symbol, market_type)

            return active_trade

        except ExchangeError as e:
            logger.error(f"❌ Trade execution failed for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error executing trade for {symbol}: {e}")
            return None

    # ========================================
    # CLOSE POSITION
    # ========================================

    def close_position(
        self,
        symbol: str,
        market_type: str = "futures",
        reason: str = "Manual close",
    ) -> Optional[float]:
        """
        Close an open position by placing a market order in the opposite direction.
        Also cancels associated SL/TP orders.
        
        Returns:
            Realized PnL if successful, None if failed.
        """
        active_trade = self._active_trades.get(symbol)
        if not active_trade:
            logger.warning(f"No active trade found for {symbol}")
            return None

        try:
            # Cancel SL/TP orders first
            self._cancel_sl_tp(active_trade)

            # Close with opposite market order
            close_side = "sell" if active_trade.side == "buy" else "buy"
            close_order = self.client.place_market_order(
                symbol=symbol,
                side=close_side,
                amount=active_trade.amount,
                market_type=market_type,
            )

            exit_price = float(
                close_order.get("average", 0) or 
                close_order.get("price", 0) or 0
            )

            # Calculate P&L
            if active_trade.side == "buy":
                pnl = (exit_price - active_trade.entry_price) * active_trade.amount
            else:
                pnl = (active_trade.entry_price - exit_price) * active_trade.amount

            # Update trade record
            active_trade.status = "closed"
            active_trade.exit_price = exit_price
            active_trade.pnl = pnl

            # Record in risk manager
            self.risk_manager.record_trade_closed(pnl, market_type)

            # Remove from active trades
            del self._active_trades[symbol]

            logger.info(
                f"📕 POSITION CLOSED | {symbol} | {reason} | "
                f"Entry: {active_trade.entry_price:.4f} → Exit: {exit_price:.4f} | "
                f"PnL: ${pnl:.2f}"
            )

            return pnl

        except Exception as e:
            logger.error(f"Failed to close position for {symbol}: {e}")
            return None

    # ========================================
    # UPDATE STOP LOSS (for WARNING signals)
    # ========================================

    def update_stop_loss(
        self,
        symbol: str,
        new_sl_price: float,
        market_type: str = "futures",
    ) -> bool:
        """
        Update (tighten) the stop-loss for an active trade.
        Cancels old SL and places new one.
        """
        active_trade = self._active_trades.get(symbol)
        if not active_trade:
            return False

        try:
            # Cancel old SL
            if active_trade.stop_loss_order_id:
                try:
                    self.client.cancel_order(
                        active_trade.stop_loss_order_id, symbol, market_type
                    )
                except Exception:
                    pass

            # Place new SL
            sl_side = "sell" if active_trade.side == "buy" else "buy"
            sl_order = self.client.place_stop_loss(
                symbol=symbol,
                side=sl_side,
                amount=active_trade.amount,
                stop_price=new_sl_price,
                market_type=market_type,
            )

            active_trade.stop_loss_order_id = sl_order.get("id")
            active_trade.stop_loss_price = new_sl_price

            logger.info(
                f"🔄 SL UPDATED | {symbol} | New SL: {new_sl_price:.4f}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to update SL for {symbol}: {e}")
            return False

    # ========================================
    # CHECK ACTIVE TRADES
    # ========================================

    def check_active_trades(self) -> List[Dict[str, Any]]:
        """
        Check status of all active trades.
        Returns list of closed trades (SL/TP hit).
        """
        closed_trades = []

        for symbol in list(self._active_trades.keys()):
            trade = self._active_trades[symbol]

            try:
                # Check if SL was triggered
                if trade.stop_loss_order_id:
                    sl_order = self.client.fetch_order(
                        trade.stop_loss_order_id, symbol, trade.market_type
                    )
                    if sl_order.get("status") == "closed":
                        exit_price = float(sl_order.get("average", 0) or trade.stop_loss_price)
                        pnl = self._calc_pnl(trade, exit_price)
                        trade.status = "closed"
                        trade.exit_price = exit_price
                        trade.pnl = pnl
                        self.risk_manager.record_trade_closed(pnl, trade.market_type)
                        closed_trades.append({
                            "symbol": symbol,
                            "exit_type": "STOP_LOSS",
                            "exit_price": exit_price,
                            "pnl": pnl,
                        })
                        del self._active_trades[symbol]
                        logger.info(f"🛑 SL HIT | {symbol} | PnL: ${pnl:.2f}")
                        continue

                # Check if TP was triggered
                if trade.take_profit_order_id:
                    tp_order = self.client.fetch_order(
                        trade.take_profit_order_id, symbol, trade.market_type
                    )
                    if tp_order.get("status") == "closed":
                        exit_price = float(tp_order.get("average", 0) or trade.take_profit_price)
                        pnl = self._calc_pnl(trade, exit_price)
                        trade.status = "closed"
                        trade.exit_price = exit_price
                        trade.pnl = pnl
                        self.risk_manager.record_trade_closed(pnl, trade.market_type)
                        closed_trades.append({
                            "symbol": symbol,
                            "exit_type": "TAKE_PROFIT",
                            "exit_price": exit_price,
                            "pnl": pnl,
                        })
                        del self._active_trades[symbol]
                        logger.info(f"🎯 TP HIT | {symbol} | PnL: ${pnl:.2f}")
                        continue

            except Exception as e:
                logger.debug(f"Could not check orders for {symbol}: {e}")

        return closed_trades

    # ========================================
    # HELPERS
    # ========================================

    def _cancel_sl_tp(self, trade: ActiveTrade) -> None:
        """Cancel SL and TP orders for a trade."""
        if trade.stop_loss_order_id:
            try:
                self.client.cancel_order(
                    trade.stop_loss_order_id, trade.symbol, trade.market_type
                )
            except Exception:
                pass

        if trade.take_profit_order_id:
            try:
                self.client.cancel_order(
                    trade.take_profit_order_id, trade.symbol, trade.market_type
                )
            except Exception:
                pass

    def _calc_pnl(self, trade: ActiveTrade, exit_price: float) -> float:
        """Calculate PnL for a trade."""
        if trade.side == "buy":
            return (exit_price - trade.entry_price) * trade.amount
        else:
            return (trade.entry_price - exit_price) * trade.amount

    def get_active_trades(self) -> Dict[str, ActiveTrade]:
        """Get all currently active trades."""
        return self._active_trades.copy()

    def has_active_trade(self, symbol: str) -> bool:
        """Check if there's an active trade for a symbol."""
        return symbol in self._active_trades
