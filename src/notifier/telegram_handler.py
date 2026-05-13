"""
Telegram Command Handler
=========================

Handles incoming messages/commands from Telegram.
Responds to user commands like /status, /balance, /help, etc.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telegram_handler")


class TelegramCommandHandler:
    """
    Handles incoming Telegram commands and messages.
    """

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.app = None
        self._running = False

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        await update.message.reply_text(
            "🤖 *Trading Bot Active!*\n\n"
            "Gue adalah bot trading lo yang bakal:\n"
            "• Monitor market 24/7\n"
            "• Kirim signal BUY/SELL\n"
            "• Auto execute trade\n\n"
            "*Commands yang tersedia:*\n"
            "/status - Cek status bot\n"
            "/help - Bantuan\n"
            "/ping - Test koneksi\n",
            parse_mode="Markdown"
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        await update.message.reply_text(
            "📚 *BANTUAN*\n\n"
            "*Commands:*\n"
            "• /start - Mulai bot\n"
            "• /status - Cek status bot\n"
            "• /ping - Test koneksi\n"
            "• /help - Tampilkan bantuan ini\n\n"
            "*Info:*\n"
            "Bot ini menggunakan strategi:\n"
            "1️⃣ RSI + MA200 Trend Filter\n"
            "2️⃣ Bollinger Bands Breakout\n\n"
            "Kedua strategi harus SETUJU baru masuk posisi (confluence).",
            parse_mode="Markdown"
        )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        await update.message.reply_text(
            "📊 *BOT STATUS*\n\n"
            "🟢 Status: *ONLINE*\n"
            "📡 Telegram: *Connected*\n"
            "🏦 Exchange: *Binance Testnet*\n"
            "⏰ Mode: *Monitoring*\n\n"
            "_Bot siap terima signal trading_",
            parse_mode="Markdown"
        )

    async def ping_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ping command"""
        await update.message.reply_text("🏓 PONG! Bot aktif bro!")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular messages"""
        text = update.message.text.lower()
        
        if "halo" in text or "hai" in text or "hi" in text:
            await update.message.reply_text("Halo bro! 👋 Ketik /help buat liat command yang tersedia.")
        elif "status" in text:
            await self.status_command(update, context)
        else:
            await update.message.reply_text(
                "🤖 Gue ngerti command doang bro.\n\n"
                "Ketik /help buat liat daftar command."
            )

    def run(self):
        """Start the Telegram bot handler"""
        logger.info("Starting Telegram command handler...")
        
        # Create application
        self.app = Application.builder().token(self.bot_token).build()
        
        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("ping", self.ping_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Run the bot
        self._running = True
        logger.info("Telegram handler is now listening for commands...")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


async def run_telegram_bot(bot_token: str, chat_id: str):
    """Run telegram bot in async mode"""
    handler = TelegramCommandHandler(bot_token, chat_id)
    
    app = Application.builder().token(bot_token).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", handler.start_command))
    app.add_handler(CommandHandler("help", handler.help_command))
    app.add_handler(CommandHandler("status", handler.status_command))
    app.add_handler(CommandHandler("ping", handler.ping_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler.handle_message))
    
    # Start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    return app


# Quick test script
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if token and chat_id:
        handler = TelegramCommandHandler(token, chat_id)
        handler.run()
    else:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env")
