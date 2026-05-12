"""
Configuration Settings Module
Loads config from YAML and environment variables.
Provides type-safe access to all bot settings.
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# ========================================
# DATA CLASSES FOR TYPE-SAFE CONFIG
# ========================================

@dataclass
class ExchangeConfig:
    name: str = "binance"
    testnet: bool = True
    rate_limit: bool = True
    timeout: int = 30000
    api_key: str = ""
    api_secret: str = ""


@dataclass
class TradingConfig:
    pairs: List[str] = field(default_factory=lambda: ["SOL/USDT", "ETH/USDT"])
    timeframes: List[str] = field(default_factory=lambda: ["15m", "2h"])
    mode: str = "both"  # "spot", "futures", "both"
    long_only_above_ma: List[int] = field(default_factory=lambda: [30, 50, 200])


@dataclass
class RSIStrategyConfig:
    rsi_length: int = 14
    rsi_overbought: int = 70
    rsi_oversold: int = 30
    ma_length: int = 200
    enabled: bool = True


@dataclass
class BollingerStrategyConfig:
    bb_length: int = 20
    bb_mult: float = 2.0
    atr_length: int = 14
    sideways_atr_mult: float = 0.5
    enabled: bool = True


@dataclass
class ConfluenceConfig:
    require_both: bool = True
    sideways_mean_reversion: bool = True


@dataclass
class FuturesRiskConfig:
    risk_per_trade_pct: float = 3.0
    leverage: int = 10
    max_open_positions: int = 3
    max_daily_loss_pct: float = 10.0
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0


@dataclass
class SpotRiskConfig:
    risk_per_trade_pct: float = 25.0
    max_open_positions: int = 3
    max_daily_loss_pct: float = 15.0
    stop_loss_pct: float = 3.0
    take_profit_pct: float = 6.0


@dataclass
class RiskConfig:
    futures: FuturesRiskConfig = field(default_factory=FuturesRiskConfig)
    spot: SpotRiskConfig = field(default_factory=SpotRiskConfig)
    cooldown_seconds: int = 60
    warning_tightens_sl: bool = True


@dataclass
class TelegramConfig:
    enabled: bool = True
    bot_token: str = ""
    chat_id: str = ""
    send_entries: bool = True
    send_exits: bool = True
    send_warnings: bool = True
    send_daily_summary: bool = True


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/trading_bot.log"
    max_size_mb: int = 50
    backup_count: int = 5


@dataclass
class BotConfig:
    """Master configuration object for the entire bot."""
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    strategy_rsi_ma200: RSIStrategyConfig = field(default_factory=RSIStrategyConfig)
    strategy_bollinger: BollingerStrategyConfig = field(default_factory=BollingerStrategyConfig)
    confluence: ConfluenceConfig = field(default_factory=ConfluenceConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


# ========================================
# CONFIGURATION LOADER
# ========================================

def load_config(config_path: Optional[str] = None) -> BotConfig:
    """
    Load configuration from YAML file + environment variables.
    Environment variables override YAML values for sensitive data.
    """
    if config_path is None:
        # Default to config/config.yaml relative to project root
        project_root = Path(__file__).parent.parent
        config_path = str(project_root / "config" / "config.yaml")

    # Load YAML
    yaml_config = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            yaml_config = yaml.safe_load(f) or {}

    # Build config object
    config = BotConfig()

    # --- Exchange ---
    exc = yaml_config.get("exchange", {})
    config.exchange = ExchangeConfig(
        name=exc.get("name", "binance"),
        testnet=exc.get("testnet", True),
        rate_limit=exc.get("rate_limit", True),
        timeout=exc.get("timeout", 30000),
        api_key=os.getenv("BINANCE_API_KEY", ""),
        api_secret=os.getenv("BINANCE_API_SECRET", ""),
    )

    # --- Trading ---
    trd = yaml_config.get("trading", {})
    config.trading = TradingConfig(
        pairs=trd.get("pairs", ["SOL/USDT", "ETH/USDT"]),
        timeframes=trd.get("timeframes", ["15m", "2h"]),
        mode=trd.get("mode", "both"),
        long_only_above_ma=trd.get("long_only_above_ma", [30, 50, 200]),
    )

    # --- Strategy: RSI + MA200 ---
    rsi = yaml_config.get("strategy_rsi_ma200", {})
    config.strategy_rsi_ma200 = RSIStrategyConfig(
        rsi_length=rsi.get("rsi_length", 14),
        rsi_overbought=rsi.get("rsi_overbought", 70),
        rsi_oversold=rsi.get("rsi_oversold", 30),
        ma_length=rsi.get("ma_length", 200),
        enabled=rsi.get("enabled", True),
    )

    # --- Strategy: Bollinger Bands ---
    bb = yaml_config.get("strategy_bollinger", {})
    config.strategy_bollinger = BollingerStrategyConfig(
        bb_length=bb.get("bb_length", 20),
        bb_mult=bb.get("bb_mult", 2.0),
        atr_length=bb.get("atr_length", 14),
        sideways_atr_mult=bb.get("sideways_atr_mult", 0.5),
        enabled=bb.get("enabled", True),
    )

    # --- Confluence ---
    conf = yaml_config.get("confluence", {})
    config.confluence = ConfluenceConfig(
        require_both=conf.get("require_both", True),
        sideways_mean_reversion=conf.get("sideways_mean_reversion", True),
    )

    # --- Risk ---
    risk = yaml_config.get("risk", {})
    futures_risk = risk.get("futures", {})
    spot_risk = risk.get("spot", {})
    config.risk = RiskConfig(
        futures=FuturesRiskConfig(
            risk_per_trade_pct=futures_risk.get("risk_per_trade_pct", 3.0),
            leverage=futures_risk.get("leverage", 10),
            max_open_positions=futures_risk.get("max_open_positions", 3),
            max_daily_loss_pct=futures_risk.get("max_daily_loss_pct", 10.0),
            stop_loss_pct=futures_risk.get("stop_loss_pct", 2.0),
            take_profit_pct=futures_risk.get("take_profit_pct", 4.0),
        ),
        spot=SpotRiskConfig(
            risk_per_trade_pct=spot_risk.get("risk_per_trade_pct", 25.0),
            max_open_positions=spot_risk.get("max_open_positions", 3),
            max_daily_loss_pct=spot_risk.get("max_daily_loss_pct", 15.0),
            stop_loss_pct=spot_risk.get("stop_loss_pct", 3.0),
            take_profit_pct=spot_risk.get("take_profit_pct", 6.0),
        ),
        cooldown_seconds=risk.get("cooldown_seconds", 60),
        warning_tightens_sl=risk.get("warning_tightens_sl", True),
    )

    # --- Telegram ---
    notif = yaml_config.get("notifications", {}).get("telegram", {})
    config.telegram = TelegramConfig(
        enabled=notif.get("enabled", True),
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        send_entries=notif.get("send_entries", True),
        send_exits=notif.get("send_exits", True),
        send_warnings=notif.get("send_warnings", True),
        send_daily_summary=notif.get("send_daily_summary", True),
    )

    # --- Logging ---
    log = yaml_config.get("logging", {})
    config.logging = LoggingConfig(
        level=log.get("level", "INFO"),
        file=log.get("file", "logs/trading_bot.log"),
        max_size_mb=log.get("max_size_mb", 50),
        backup_count=log.get("backup_count", 5),
    )

    return config


def validate_config(config: BotConfig) -> List[str]:
    """
    Validate configuration and return list of errors.
    Returns empty list if config is valid.
    """
    errors = []

    # Check API keys
    if not config.exchange.api_key:
        errors.append("BINANCE_API_KEY not set in environment")
    if not config.exchange.api_secret:
        errors.append("BINANCE_API_SECRET not set in environment")

    # Check Telegram (warn but don't fail)
    if config.telegram.enabled:
        if not config.telegram.bot_token:
            errors.append("TELEGRAM_BOT_TOKEN not set but Telegram is enabled")
        if not config.telegram.chat_id:
            errors.append("TELEGRAM_CHAT_ID not set but Telegram is enabled")

    # Check trading pairs
    if not config.trading.pairs:
        errors.append("No trading pairs configured")

    # Check timeframes
    if not config.trading.timeframes:
        errors.append("No timeframes configured")

    # Validate risk percentages
    if config.risk.futures.risk_per_trade_pct <= 0 or config.risk.futures.risk_per_trade_pct > 100:
        errors.append("Futures risk_per_trade_pct must be between 0 and 100")
    if config.risk.spot.risk_per_trade_pct <= 0 or config.risk.spot.risk_per_trade_pct > 100:
        errors.append("Spot risk_per_trade_pct must be between 0 and 100")

    # Validate mode
    if config.trading.mode not in ("spot", "futures", "both"):
        errors.append(f"Invalid trading mode: {config.trading.mode}")

    return errors
