"""
Trading Bot - Main Entry Point
================================

Orchestrates the full trading loop:
1. Load config & initialize components
2. Every candle close: fetch data → compute indicators → evaluate strategy
3. If signal: validate risk → execute trade → notify
4. Monitor open trades (SL/TP checks)
5. Handle warnings (tighten SL)
6. Send daily summary

Usage:
    python -m src.main
    python src/main.py
"""

import sys
import time
import signal as os_signal
import traceback
from pathlib import Path
from typing import Dict, List
from datetime import datetime, timezone

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_config, validate_config, BotConfig
from src.utils.logger import setup_logger, get_logger
from src.exchange.client import BinanceClient
from src.data.market_data import MarketDataManager
from src.strategy.confluence import ConfluenceEngine, ConfluenceSignal
from src.strategy.rsi_ma200 import SignalType
from src.risk.risk_manager import RiskManager
from src.execution.executor import OrderExecutor
from src.notifier.telegram import TelegramNotifier
from src.utils.state import save_state, load_state


# ========================================
# TRADING BOT CLASS
# ========================================

class TradingBot:
    """
    Main trading bot orchestrator.
    Runs the strategy loop on configured intervals.
    """

    def __init__(self, config_path: str = None):
        # Load config
        self.config = load_config(config_path)

        # Setup logging
        self.logger = setup_logger(
            name="trading_bot",
            level=self.config.logging.level,
            log_file=self.config.logging.file,
            max_size_mb=self.config.logging.max_size_mb,
            backup_count=self.config.logging.backup_count,
        )

        # Validate config
        errors = validate_config(self.config)
        if errors:
            for err in errors:
                self.logger.warning(f"Config warning: {err}")

        # Initialize components
        self.client: BinanceClient = None
        self.market_data: MarketDataManager = None
        self.strategy: ConfluenceEngine = None
        self.risk_manager: RiskManager = None
        self.executor: OrderExecutor = None
        self.notifier: TelegramNotifier = None

        # Control
        self._running = False
        self._cycle_count = 0

    def initialize(self) -> bool:
        """Initialize all bot components. Returns True if successful."""
        try:
            self.logger.info("=" * 60)
            self.logger.info("TRADING BOT STARTING")
            self.logger.info("=" * 60)
            self.logger.info(f"Mode: {self.config.trading.mode}")
            self.logger.info(f"Pairs: {self.config.trading.pairs}")
            self.logger.info(f"Timeframes: {self.config.trading.timeframes}")
            self.logger.info(f"Testnet: {self.config.exchange.testnet}")

            # Exchange client
            self.client = BinanceClient(self.config)
            self.client.initialize()

            # Market data
            self.market_data = MarketDataManager(self.client, self.config)

            # Strategy engine
            self.strategy = ConfluenceEngine(self.config)

            # Risk manager
            self.risk_manager = RiskManager(self.config, self.client)

            # Executor
            self.executor = OrderExecutor(self.config, self.client, self.risk_manager)

            # Telegram notifier
            self.notifier = TelegramNotifier(self.config.telegram)

            # Notify startup
            self.notifier.send_bot_status(
                "STARTED",
                f"Pairs: {len(self.config.trading.pairs)} | "
                f"Mode: {self.config.trading.mode} | "
                f"Testnet: {self.config.exchange.testnet}"
            )

            self.logger.info("All components initialized successfully")
            return True

        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            self.logger.error(traceback.format_exc())
            return False

    # ========================================
    # MAIN LOOP
    # ========================================

    def run(self) -> None:
        """
        Main bot loop. Runs continuously until stopped.
        """
        if not self.initialize():
            self.logger.error("Failed to initialize. Exiting.")
            return

        # Register signal handlers for graceful shutdown
        os_signal.signal(os_signal.SIGINT, self._shutdown_handler)
        os_signal.signal(os_signal.SIGTERM, self._shutdown_handler)

        self._running = True
        self.logger.info("Bot is now LIVE. Starting main loop...")

        # Determine loop interval based on smallest timeframe
        loop_interval = self._get_loop_interval()
        self.logger.info(f"Loop interval: {loop_interval} seconds")

        last_daily_summary_hour = -1

        while self._running:
            try:
                cycle_start = time.time()
                self._cycle_count += 1

                self.logger.info(f"--- Cycle #{self._cycle_count} ---")

                # 1. Check active trades (SL/TP hits)
                self._check_active_trades()

                # 2. Refresh positions from exchange
                self._refresh_positions()

                # 3. Run strategy for each pair/timeframe/market_type
                self._run_strategy_cycle()

                # 4. Daily summary check (send at 00:00 UTC)
                current_hour = datetime.now(timezone.utc).hour
                if current_hour == 0 and last_daily_summary_hour != 0:
                    self._send_daily_summary()
                    last_daily_summary_hour = 0
                elif current_hour != 0:
                    last_daily_summary_hour = current_hour

                # 5. Save state
                self._save_bot_state()

                # Wait for next cycle
                elapsed = time.time() - cycle_start
                sleep_time = max(1, loop_interval - elapsed)
                self.logger.debug(f"Cycle took {elapsed:.1f}s. Sleeping {sleep_time:.0f}s...")
                
                # Sleep in small intervals to allow graceful shutdown
                self._interruptible_sleep(sleep_time)

            except KeyboardInterrupt:
                self.logger.info("KeyboardInterrupt received. Shutting down...")
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                self.logger.error(traceback.format_exc())
                self.notifier.send_error(str(e))
                # Don't crash — sleep and retry
                self._interruptible_sleep(30)

        self._shutdown()

    # ========================================
    # STRATEGY CYCLE
    # ========================================

    def _run_strategy_cycle(self) -> None:
        """
        Run the full strategy evaluation cycle for all pairs and timeframes.
        """
        market_types = self._get_market_types()

        for timeframe in self.config.trading.timeframes:
            for market_type in market_types:
                # Fetch data for all pairs at once
                all_indicators = self.market_data.fetch_all_pairs(timeframe, market_type)

                for symbol, indicators in all_indicators.items():
                    try:
                        self._process_symbol(symbol, timeframe, market_type, indicators)
                    except Exception as e:
                        self.logger.error(
                            f"Error processing {symbol} {timeframe} {market_type}: {e}"
                        )

    def _process_symbol(self, symbol, timeframe, market_type, indicators) -> None:
        """Process a single symbol: strategy → risk → execute."""
        
        # Skip if already have an active trade for this symbol
        if self.executor.has_active_trade(symbol):
            self.logger.debug(f"Skipping {symbol}: active trade exists")
            return

        # Evaluate confluence strategy
        signal = self.strategy.evaluate(indicators, symbol, timeframe)

        # Handle WARNING signals
        if signal.is_warning:
            self._handle_warning(signal, market_type)
            return

        # Handle actionable signals (BUY/SELL)
        if signal.is_actionable:
            self.logger.info(
                f"📡 SIGNAL: {signal.signal_type.value} {symbol} {timeframe} | "
                f"Strength: {signal.strength:.0%} | Regime: {signal.market_regime.value}"
            )

            # Validate through risk manager
            trade_order = self.risk_manager.validate_trade(signal, market_type)

            if trade_order is not None:
                # Execute the trade
                active_trade = self.executor.execute_trade(trade_order)

                if active_trade:
                    # Send Telegram notification
                    self.notifier.send_entry_signal(
                        symbol=symbol,
                        side=trade_order.side,
                        price=active_trade.entry_price,
                        amount=trade_order.amount,
                        sl_price=trade_order.stop_loss_price,
                        tp_price=trade_order.take_profit_price,
                        market_type=market_type,
                        reason=signal.reason,
                        strength=signal.strength,
                    )

    # ========================================
    # WARNING HANDLER
    # ========================================

    def _handle_warning(self, signal: ConfluenceSignal, market_type: str) -> None:
        """Handle a WARNING signal — tighten SL if configured."""
        self.logger.warning(f"⚠️ WARNING | {signal.symbol} | {signal.reason}")

        new_sl = self.risk_manager.handle_warning(signal, market_type)
        action_taken = "None"

        if new_sl is not None:
            success = self.executor.update_stop_loss(signal.symbol, new_sl, market_type)
            if success:
                action_taken = f"SL tightened to {new_sl:.4f}"

        # Notify via Telegram
        self.notifier.send_warning(
            symbol=signal.symbol,
            reason=signal.reason,
            rsi_value=signal.rsi_signal.rsi_value if signal.rsi_signal else 0,
            action_taken=action_taken,
        )

    # ========================================
    # TRADE MONITORING
    # ========================================

    def _check_active_trades(self) -> None:
        """Check if any active trades hit SL/TP."""
        closed_trades = self.executor.check_active_trades()

        for trade_info in closed_trades:
            self.notifier.send_exit_signal(
                symbol=trade_info["symbol"],
                side="long" if trade_info.get("pnl", 0) else "short",
                entry_price=0,  # Already logged by executor
                exit_price=trade_info["exit_price"],
                pnl=trade_info["pnl"],
                exit_type=trade_info["exit_type"],
                market_type="futures",
            )

    def _refresh_positions(self) -> None:
        """Refresh positions from exchange."""
        try:
            for market_type in self._get_market_types():
                self.risk_manager.refresh_positions(market_type)
        except Exception as e:
            self.logger.debug(f"Position refresh failed: {e}")

    # ========================================
    # DAILY SUMMARY
    # ========================================

    def _send_daily_summary(self) -> None:
        """Send daily trading summary via Telegram."""
        summary = self.risk_manager.get_daily_summary()
        self.notifier.send_daily_summary(summary)
        self.logger.info(
            f"📊 Daily Summary | PnL: ${summary['pnl']:.2f} | "
            f"Trades: {summary['trades']} | Win Rate: {summary['win_rate']:.1f}%"
        )

    # ========================================
    # STATE PERSISTENCE
    # ========================================

    def _save_bot_state(self) -> None:
        """Save current bot state for crash recovery."""
        active_trades = {}
        for symbol, trade in self.executor.get_active_trades().items():
            active_trades[symbol] = {
                "symbol": trade.symbol,
                "side": trade.side,
                "market_type": trade.market_type,
                "entry_price": trade.entry_price,
                "amount": trade.amount,
                "stop_loss_price": trade.stop_loss_price,
                "take_profit_price": trade.take_profit_price,
                "entry_order_id": trade.entry_order_id,
                "stop_loss_order_id": trade.stop_loss_order_id,
                "take_profit_order_id": trade.take_profit_order_id,
                "timestamp": trade.timestamp,
            }

        state = {
            "active_trades": active_trades,
            "cycle_count": self._cycle_count,
            "last_save": datetime.now(timezone.utc).isoformat(),
            "daily_summary": self.risk_manager.get_daily_summary(),
        }
        save_state(state)

    # ========================================
    # UTILITIES
    # ========================================

    def _get_loop_interval(self) -> int:
        """
        Calculate loop interval based on smallest configured timeframe.
        We check more frequently than the candle close to not miss signals.
        """
        timeframe_seconds = {
            "1m": 60, "3m": 180, "5m": 300, "10m": 600,
            "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
            "4h": 14400, "1d": 86400,
        }

        min_interval = float("inf")
        for tf in self.config.trading.timeframes:
            seconds = timeframe_seconds.get(tf, 900)
            min_interval = min(min_interval, seconds)

        # Check at ~1/3 of the candle interval (minimum 30s, max 5min)
        check_interval = max(30, min(300, int(min_interval / 3)))
        return check_interval

    def _get_market_types(self) -> List[str]:
        """Get configured market types."""
        mode = self.config.trading.mode
        if mode == "both":
            return ["spot", "futures"]
        return [mode]

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in 1-second intervals to allow graceful shutdown."""
        for _ in range(int(seconds)):
            if not self._running:
                break
            time.sleep(1)

    def _shutdown_handler(self, signum, frame) -> None:
        """Handle shutdown signals."""
        self.logger.info(f"Shutdown signal received ({signum})")
        self._running = False

    def _shutdown(self) -> None:
        """Graceful shutdown."""
        self.logger.info("Shutting down...")
        self._save_bot_state()

        if self.notifier:
            self.notifier.send_bot_status("STOPPED", "Graceful shutdown")

        if self.client:
            self.client.close()

        self.logger.info("Bot shut down successfully")
        self.logger.info("=" * 60)


# ========================================
# ENTRY POINT
# ========================================

def main():
    """Main entry point."""
    print("""
    ╔══════════════════════════════════════════════════╗
    ║         CONFLUENCE TRADING BOT v1.0             ║
    ║   RSI + MA200 × Bollinger Bands Strategy        ║
    ║          Binance Spot & Futures                  ║
    ╚══════════════════════════════════════════════════╝
    """)

    # Check for custom config path
    config_path = None
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
        print(f"  Using config: {config_path}")

    bot = TradingBot(config_path)
    bot.run()


if __name__ == "__main__":
    main()
