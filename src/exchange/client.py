"""
Exchange Client Module
Wraps ccxt for Binance (spot + futures) with retry logic,
rate limiting, and graceful error handling.
"""

import time
import ccxt
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent.parent))

from config.settings import ExchangeConfig, BotConfig
from src.utils.logger import get_logger

logger = get_logger("exchange")


# ========================================
# CUSTOM EXCEPTIONS
# ========================================

class ExchangeError(Exception):
    """Base exchange error."""
    pass


class InsufficientBalanceError(ExchangeError):
    """Not enough balance to place order."""
    pass


class OrderFailedError(ExchangeError):
    """Order placement failed."""
    pass


class ConnectionError(ExchangeError):
    """Exchange connection error."""
    pass


# ========================================
# RETRY DECORATOR
# ========================================

def retry_on_failure(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    Decorator that retries a function on ccxt exceptions.
    Uses exponential backoff.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay

            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (
                    ccxt.NetworkError,
                    ccxt.RequestTimeout,
                    ccxt.ExchangeNotAvailable,
                    ccxt.DDoSProtection,
                ) as e:
                    last_exception = e
                    logger.warning(
                        f"Attempt {attempt}/{max_retries} failed for {func.__name__}: {e}"
                    )
                    if attempt < max_retries:
                        time.sleep(current_delay)
                        current_delay *= backoff
                except ccxt.InsufficientFunds as e:
                    raise InsufficientBalanceError(str(e)) from e
                except ccxt.InvalidOrder as e:
                    raise OrderFailedError(str(e)) from e
                except ccxt.AuthenticationError as e:
                    raise ExchangeError(f"Authentication failed: {e}") from e
                except ccxt.BaseError as e:
                    raise ExchangeError(f"Exchange error: {e}") from e

            raise ConnectionError(
                f"Failed after {max_retries} retries: {last_exception}"
            ) from last_exception

        return wrapper
    return decorator


# ========================================
# EXCHANGE CLIENT
# ========================================

@dataclass
class Position:
    """Represents an open position."""
    symbol: str
    side: str  # "long" or "short"
    size: float
    entry_price: float
    unrealized_pnl: float = 0.0
    leverage: int = 1
    market_type: str = "futures"  # "spot" or "futures"


class BinanceClient:
    """
    Unified Binance client for both spot and futures.
    Handles testnet/live switching, order management, and position tracking.
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self._spot: Optional[ccxt.binance] = None
        self._futures: Optional[ccxt.binance] = None
        self._initialized = False

    def initialize(self) -> None:
        """Initialize exchange connections."""
        exc_config = self.config.exchange

        # Common options
        common_opts = {
            "apiKey": exc_config.api_key,
            "secret": exc_config.api_secret,
            "enableRateLimit": exc_config.rate_limit,
            "timeout": exc_config.timeout,
        }

        # --- SPOT ---
        if self.config.trading.mode in ("spot", "both"):
            spot_opts = {**common_opts}
            if exc_config.testnet:
                spot_opts["options"] = {"defaultType": "spot"}
                spot_opts["urls"] = {
                    "api": {
                        "public": "https://testnet.binance.vision/api/v3",
                        "private": "https://testnet.binance.vision/api/v3",
                    }
                }
            self._spot = ccxt.binance(spot_opts)
            if exc_config.testnet:
                self._spot.set_sandbox_mode(True)
            logger.info("Spot client initialized (testnet=%s)", exc_config.testnet)

        # --- FUTURES ---
        if self.config.trading.mode in ("futures", "both"):
            futures_opts = {**common_opts}
            futures_opts["options"] = {"defaultType": "future"}
            if exc_config.testnet:
                futures_opts["options"]["sandboxMode"] = True
            self._futures = ccxt.binance(futures_opts)
            if exc_config.testnet:
                self._futures.set_sandbox_mode(True)
            logger.info("Futures client initialized (testnet=%s)", exc_config.testnet)

        self._initialized = True

    @property
    def spot(self) -> ccxt.binance:
        """Get spot exchange instance."""
        if self._spot is None:
            raise ExchangeError("Spot client not initialized. Check trading mode.")
        return self._spot

    @property
    def futures(self) -> ccxt.binance:
        """Get futures exchange instance."""
        if self._futures is None:
            raise ExchangeError("Futures client not initialized. Check trading mode.")
        return self._futures

    def get_client(self, market_type: str) -> ccxt.binance:
        """Get the appropriate client based on market type."""
        if market_type == "spot":
            return self.spot
        elif market_type == "futures":
            return self.futures
        else:
            raise ExchangeError(f"Invalid market type: {market_type}")

    # ========================================
    # MARKET DATA
    # ========================================

    @retry_on_failure(max_retries=3, delay=1.0)
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        market_type: str = "futures",
    ) -> List[List]:
        """
        Fetch OHLCV candles.
        Returns: [[timestamp, open, high, low, close, volume], ...]
        """
        client = self.get_client(market_type)
        candles = client.fetch_ohlcv(symbol, timeframe, limit=limit)
        logger.debug(f"Fetched {len(candles)} candles for {symbol} {timeframe}")
        return candles

    @retry_on_failure(max_retries=3, delay=1.0)
    def fetch_ticker(self, symbol: str, market_type: str = "futures") -> Dict[str, Any]:
        """Fetch current ticker data."""
        client = self.get_client(market_type)
        return client.fetch_ticker(symbol)

    @retry_on_failure(max_retries=3, delay=1.0)
    def fetch_order_book(
        self, symbol: str, limit: int = 10, market_type: str = "futures"
    ) -> Dict[str, Any]:
        """Fetch order book."""
        client = self.get_client(market_type)
        return client.fetch_order_book(symbol, limit=limit)

    # ========================================
    # BALANCE & POSITIONS
    # ========================================

    @retry_on_failure(max_retries=3, delay=1.0)
    def fetch_balance(self, market_type: str = "futures") -> Dict[str, Any]:
        """Fetch account balance."""
        client = self.get_client(market_type)
        balance = client.fetch_balance()
        return balance

    def get_free_balance(self, currency: str = "USDT", market_type: str = "futures") -> float:
        """Get available (free) balance for a currency."""
        balance = self.fetch_balance(market_type)
        free = balance.get("free", {}).get(currency, 0.0)
        return float(free)

    @retry_on_failure(max_retries=3, delay=1.0)
    def fetch_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """
        Fetch open futures positions.
        Returns list of Position objects.
        """
        if self._futures is None:
            return []

        positions = self._futures.fetch_positions([symbol] if symbol else None)
        result = []

        for pos in positions:
            size = float(pos.get("contracts", 0) or 0)
            if size == 0:
                continue

            result.append(Position(
                symbol=pos["symbol"],
                side=pos["side"],
                size=abs(size),
                entry_price=float(pos.get("entryPrice", 0) or 0),
                unrealized_pnl=float(pos.get("unrealizedPnl", 0) or 0),
                leverage=int(pos.get("leverage", 1) or 1),
                market_type="futures",
            ))

        return result

    # ========================================
    # ORDER MANAGEMENT
    # ========================================

    @retry_on_failure(max_retries=3, delay=1.0)
    def place_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        market_type: str = "futures",
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Place a market order.
        
        Args:
            symbol: Trading pair (e.g., "SOL/USDT")
            side: "buy" or "sell"
            amount: Order quantity
            market_type: "spot" or "futures"
            params: Additional exchange-specific params
            
        Returns:
            Order response dict
        """
        client = self.get_client(market_type)
        order = client.create_market_order(
            symbol=symbol,
            side=side,
            amount=amount,
            params=params or {},
        )
        logger.info(
            f"MARKET {side.upper()} {amount} {symbol} @ market | "
            f"ID: {order['id']} | Status: {order['status']}"
        )
        return order

    @retry_on_failure(max_retries=3, delay=1.0)
    def place_limit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        market_type: str = "futures",
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Place a limit order."""
        client = self.get_client(market_type)
        order = client.create_limit_order(
            symbol=symbol,
            side=side,
            amount=amount,
            price=price,
            params=params or {},
        )
        logger.info(
            f"LIMIT {side.upper()} {amount} {symbol} @ {price} | "
            f"ID: {order['id']} | Status: {order['status']}"
        )
        return order

    @retry_on_failure(max_retries=3, delay=1.0)
    def place_stop_loss(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
        market_type: str = "futures",
    ) -> Dict[str, Any]:
        """Place a stop-loss order (stop market)."""
        client = self.get_client(market_type)
        params = {"stopPrice": stop_price, "type": "STOP_MARKET"}
        if market_type == "spot":
            params = {"stopPrice": stop_price, "type": "STOP_LOSS"}

        order = client.create_order(
            symbol=symbol,
            type="STOP_MARKET" if market_type == "futures" else "STOP_LOSS",
            side=side,
            amount=amount,
            price=None,
            params=params,
        )
        logger.info(
            f"STOP LOSS {side.upper()} {amount} {symbol} @ {stop_price} | "
            f"ID: {order['id']}"
        )
        return order

    @retry_on_failure(max_retries=3, delay=1.0)
    def place_take_profit(
        self,
        symbol: str,
        side: str,
        amount: float,
        tp_price: float,
        market_type: str = "futures",
    ) -> Dict[str, Any]:
        """Place a take-profit order (take profit market)."""
        client = self.get_client(market_type)
        params = {"stopPrice": tp_price, "type": "TAKE_PROFIT_MARKET"}
        if market_type == "spot":
            params = {"stopPrice": tp_price, "type": "TAKE_PROFIT"}

        order = client.create_order(
            symbol=symbol,
            type="TAKE_PROFIT_MARKET" if market_type == "futures" else "TAKE_PROFIT",
            side=side,
            amount=amount,
            price=None,
            params=params,
        )
        logger.info(
            f"TAKE PROFIT {side.upper()} {amount} {symbol} @ {tp_price} | "
            f"ID: {order['id']}"
        )
        return order

    @retry_on_failure(max_retries=3, delay=1.0)
    def cancel_order(
        self, order_id: str, symbol: str, market_type: str = "futures"
    ) -> Dict[str, Any]:
        """Cancel an open order."""
        client = self.get_client(market_type)
        result = client.cancel_order(order_id, symbol)
        logger.info(f"Cancelled order {order_id} for {symbol}")
        return result

    @retry_on_failure(max_retries=3, delay=1.0)
    def cancel_all_orders(self, symbol: str, market_type: str = "futures") -> None:
        """Cancel all open orders for a symbol."""
        client = self.get_client(market_type)
        client.cancel_all_orders(symbol)
        logger.info(f"Cancelled all orders for {symbol}")

    @retry_on_failure(max_retries=3, delay=1.0)
    def fetch_order(
        self, order_id: str, symbol: str, market_type: str = "futures"
    ) -> Dict[str, Any]:
        """Fetch order status."""
        client = self.get_client(market_type)
        return client.fetch_order(order_id, symbol)

    @retry_on_failure(max_retries=3, delay=1.0)
    def fetch_open_orders(
        self, symbol: Optional[str] = None, market_type: str = "futures"
    ) -> List[Dict[str, Any]]:
        """Fetch all open orders."""
        client = self.get_client(market_type)
        return client.fetch_open_orders(symbol)

    # ========================================
    # FUTURES-SPECIFIC
    # ========================================

    @retry_on_failure(max_retries=3, delay=1.0)
    def set_leverage(self, symbol: str, leverage: int) -> None:
        """Set leverage for a futures symbol."""
        if self._futures is None:
            return
        self._futures.set_leverage(leverage, symbol)
        logger.info(f"Set leverage to {leverage}x for {symbol}")

    @retry_on_failure(max_retries=3, delay=1.0)
    def set_margin_mode(self, symbol: str, mode: str = "isolated") -> None:
        """Set margin mode (isolated/cross) for a futures symbol."""
        if self._futures is None:
            return
        try:
            self._futures.set_margin_mode(mode, symbol)
            logger.info(f"Set margin mode to {mode} for {symbol}")
        except ccxt.BaseError as e:
            # Already set to this mode — ignore
            if "No need to change" in str(e) or "already" in str(e).lower():
                pass
            else:
                raise

    # ========================================
    # UTILITY
    # ========================================

    @retry_on_failure(max_retries=3, delay=1.0)
    def get_market_info(self, symbol: str, market_type: str = "futures") -> Dict[str, Any]:
        """Get market/symbol information (min qty, price precision, etc.)."""
        client = self.get_client(market_type)
        client.load_markets()
        if symbol in client.markets:
            return client.markets[symbol]
        raise ExchangeError(f"Symbol {symbol} not found on {market_type}")

    def get_min_order_amount(self, symbol: str, market_type: str = "futures") -> float:
        """Get minimum order amount for a symbol."""
        market = self.get_market_info(symbol, market_type)
        limits = market.get("limits", {}).get("amount", {})
        return float(limits.get("min", 0.001))

    def get_price_precision(self, symbol: str, market_type: str = "futures") -> int:
        """Get price precision (decimal places) for a symbol."""
        market = self.get_market_info(symbol, market_type)
        return market.get("precision", {}).get("price", 2)

    def get_amount_precision(self, symbol: str, market_type: str = "futures") -> int:
        """Get amount precision (decimal places) for a symbol."""
        market = self.get_market_info(symbol, market_type)
        return market.get("precision", {}).get("amount", 3)

    def close(self) -> None:
        """Close all exchange connections."""
        if self._spot:
            self._spot.close()
        if self._futures:
            self._futures.close()
        logger.info("Exchange connections closed")
