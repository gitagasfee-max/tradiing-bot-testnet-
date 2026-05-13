"""
Telegram Notifier Module
=========================

Sends trade alerts, warnings, and daily summaries to Telegram.
Uses python-telegram-bot library (async-compatible).
"""

import asyncio
import time
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from config.settings import TelegramConfig
from src.utils.logger import get_logger

logger = get_logger("notifier.telegram")


class TelegramNotifier:
    """
    Sends formatted messages to a Telegram chat.
    All sends are non-blocking (fire-and-forget with error logging).
    """

    def __init__(self, config: TelegramConfig):
        self.config = config
        self.enabled = config.enabled and bool(config.bot_token) and bool(config.chat_id)
        self._bot = None

        if self.enabled:
            try:
                from telegram import Bot
                self._bot = Bot(token=config.bot_token)
                logger.info("Telegram notifier initialized")
            except ImportError:
                logger.warning("python-telegram-bot not installed. Telegram disabled.")
                self.enabled = False
            except Exception as e:
                logger.error(f"Failed to initialize Telegram bot: {e}")
                self.enabled = False
        else:
            logger.info("Telegram notifier disabled (missing token/chat_id)")

    # ========================================
    # SEND METHODS
    # ========================================

    def send_entry_signal(
        self,
        symbol: str,
        side: str,
        price: float,
        amount: float,
        sl_price: float,
        tp_price: float,
        market_type: str,
        reason: str,
        strength: float = 0.0,
    ) -> None:
        """Send a trade entry notification."""
        if not self.enabled or not self.config.send_entries:
            return

        emoji = "🟢" if side == "buy" else "🔴"
        direction = "LONG" if side == "buy" else "SHORT"

        message = (
            f"{emoji} *{direction} ENTRY* | `{symbol}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Entry Price: `{price:.4f}`\n"
            f"📊 Amount: `{amount:.6f}`\n"
            f"🛡️ Stop Loss: `{sl_price:.4f}`\n"
            f"🎯 Take Profit: `{tp_price:.4f}`\n"
            f"📈 Market: `{market_type.upper()}`\n"
            f"💪 Strength: `{strength:.0%}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📝 _{reason[:200]}_\n"
            f"⏰ {self._timestamp()}"
        )

        self._send(message)

    def send_exit_signal(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        pnl: float,
        exit_type: str,
        market_type: str,
    ) -> None:
        """Send a trade exit notification."""
        if not self.enabled or not self.config.send_exits:
            return

        emoji = "✅" if pnl >= 0 else "❌"
        pnl_emoji = "📈" if pnl >= 0 else "📉"

        message = (
            f"{emoji} *POSITION CLOSED* | `{symbol}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Direction: `{side.upper()}`\n"
            f"💰 Entry: `{entry_price:.4f}`\n"
            f"💰 Exit: `{exit_price:.4f}`\n"
            f"{pnl_emoji} PnL: `${pnl:.2f}`\n"
            f"🏷️ Exit Type: `{exit_type}`\n"
            f"📈 Market: `{market_type.upper()}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {self._timestamp()}"
        )

        self._send(message)

    def send_warning(
        self,
        symbol: str,
        reason: str,
        rsi_value: float = 0.0,
        action_taken: str = "None",
    ) -> None:
        """Send a warning notification."""
        if not self.enabled or not self.config.send_warnings:
            return

        message = (
            f"⚠️ *WARNING* | `{symbol}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 RSI: `{rsi_value:.1f}`\n"
            f"📝 _{reason}_\n"
            f"🔧 Action: `{action_taken}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {self._timestamp()}"
        )

        self._send(message)

    def send_daily_summary(self, summary: Dict[str, Any]) -> None:
        """Send end-of-day summary."""
        if not self.enabled or not self.config.send_daily_summary:
            return

        pnl = summary.get("pnl", 0)
        emoji = "📈" if pnl >= 0 else "📉"
        trades = summary.get("trades", 0)
        wins = summary.get("wins", 0)
        losses = summary.get("losses", 0)
        win_rate = summary.get("win_rate", 0)

        message = (
            f"📊 *DAILY SUMMARY* | {summary.get('date', 'N/A')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} Total PnL: `${pnl:.2f}`\n"
            f"📋 Trades: `{trades}`\n"
            f"✅ Wins: `{wins}` | ❌ Losses: `{losses}`\n"
            f"🎯 Win Rate: `{win_rate:.1f}%`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {self._timestamp()}"
        )

        self._send(message)

    def send_bot_status(self, status: str, details: str = "") -> None:
        """Send bot status update (startup, shutdown, errors)."""
        if not self.enabled:
            return

        message = (
            f"🤖 *BOT STATUS*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Status: `{status}`\n"
        )
        if details:
            message += f"Details: _{details}_\n"
        message += f"⏰ {self._timestamp()}"

        self._send(message)

    def send_error(self, error_msg: str, symbol: str = "") -> None:
        """Send error notification."""
        if not self.enabled:
            return

        message = (
            f"🚨 *ERROR*"
        )
        if symbol:
            message += f" | `{symbol}`"
        message += (
            f"\n━━━━━━━━━━━━━━━━━━━━\n"
            f"❗ {error_msg[:500]}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {self._timestamp()}"
        )

        self._send(message)

    # ========================================
    # INTERNAL
    # ========================================

    def _send(self, message: str) -> None:
        """
        Send a message to Telegram (non-blocking).
        Uses sync method with timeout to avoid blocking the main loop.
        """
        if not self.enabled or not self._bot:
            return

        try:
            # Try to get running event loop
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context — schedule it
                loop.create_task(self._async_send(message))
            except RuntimeError:
                # No event loop running — create one
                asyncio.run(self._async_send(message))
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    async def _async_send(self, message: str) -> None:
        """Async send with timeout."""
        try:
            await self._bot.send_message(
                chat_id=self.config.chat_id,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    def _timestamp(self) -> str:
        """Get formatted UTC timestamp."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
