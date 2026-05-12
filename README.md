# Confluence Trading Bot v1.0

**RSI + MA200 × Bollinger Bands | Binance Spot & Futures | Testnet**

A professional-grade Python trading bot that combines two strategies (RSI + MA200 trend filter and Bollinger Bands trend detection) using confluence logic. Only enters trades when both strategies agree.

---

## Features

- **Dual Strategy Confluence**: RSI + MA200 and Bollinger Bands must agree for entry
- **Trend & Sideways Detection**: Breakout mode in trends, mean-reversion in sideways
- **MA Filter**: Longs only when price > MA30, MA50, MA200
- **Binance Spot & Futures**: Supports both markets with independent risk profiles
- **Risk Management**: Position sizing, SL/TP, max daily loss, cooldowns
- **Warning System**: RSI overbought warnings tighten stop-losses
- **Telegram Alerts**: Real-time notifications for entries, exits, and warnings
- **State Persistence**: Survives restarts without losing track of positions
- **Testnet First**: Designed for demo trading before going live

---

## Strategy Overview

### Strategy 1: RSI + MA200
- **BUY**: Price > MA200 (uptrend) AND RSI crosses up through 30 (oversold recovery)
- **SELL**: Price ≤ MA200 (downtrend) AND RSI crosses down through 70 (overbought rejection)
- **WARNING**: RSI starts falling from above 70 (potential reversal)

### Strategy 2: Bollinger Bands
- **Trending Market (Breakout Mode)**:
  - BUY: Close breaks above previous bar's upper band
  - SELL: Close breaks below previous bar's lower band
- **Sideways Market (Mean-Reversion Mode)**:
  - BUY: Price crosses up through lower band
  - SELL: Price crosses down through upper band
- **Sideways Detection**: Band width ≤ 0.5 × ATR(14)

### Confluence Rule
- Both strategies must signal the same direction
- MA30/50/200 filter must pass for longs
- In sideways markets: BB signals alone with RSI confirmation

---

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your API keys:
# - BINANCE_API_KEY
# - BINANCE_API_SECRET
# - TELEGRAM_BOT_TOKEN
# - TELEGRAM_CHAT_ID
```

### 3. Configure Strategy
Edit `config/config.yaml` to adjust:
- Trading pairs
- Timeframes
- Risk percentages
- Strategy parameters

### 4. Run the Bot
```bash
python -m src.main
# or
python src/main.py
# or with custom config:
python src/main.py /path/to/config.yaml
```

---

## Project Structure

```
├── config/
│   ├── config.yaml          # All bot settings (strategy, risk, pairs)
│   └── settings.py          # Type-safe config loader
├── src/
│   ├── main.py              # Entry point & main loop
│   ├── exchange/
│   │   └── client.py        # Binance API wrapper (ccxt) with retries
│   ├── data/
│   │   └── market_data.py   # Candle fetching & indicator computation
│   ├── strategy/
│   │   ├── rsi_ma200.py     # Strategy 1: RSI + MA200
│   │   ├── bollinger_bands.py  # Strategy 2: Bollinger Bands
│   │   └── confluence.py    # Combined confluence engine
│   ├── risk/
│   │   └── risk_manager.py  # Position sizing, SL/TP, daily limits
│   ├── execution/
│   │   └── executor.py      # Order placement & fill tracking
│   ├── notifier/
│   │   └── telegram.py      # Telegram alert notifications
│   └── utils/
│       ├── logger.py        # Structured logging with rotation
│       └── state.py         # State persistence (JSON)
├── .env.example             # Environment variable template
├── requirements.txt         # Python dependencies
└── README.md
```

---

## Risk Settings

| Setting | Futures | Spot |
|---------|---------|------|
| Risk per trade | 3% | 25% |
| Stop Loss | 2% | 3% |
| Take Profit | 4% | 6% |
| Max positions | 3 | 3 |
| Max daily loss | 10% | 15% |
| Leverage | 10x | N/A |

---

## Configuration

All settings are in `config/config.yaml`. Key sections:

```yaml
trading:
  pairs: [SOL/USDT, ETH/USDT, BTC/USDT, ...]
  timeframes: ["15m", "2h"]
  mode: both  # spot, futures, or both

strategy_rsi_ma200:
  rsi_length: 14
  rsi_overbought: 70
  rsi_oversold: 30
  ma_length: 200

strategy_bollinger:
  bb_length: 20
  bb_mult: 2.0
  sideways_atr_mult: 0.5

confluence:
  require_both: true
  sideways_mean_reversion: true
```

---

## Telegram Setup

1. Create a bot via [@BotFather](https://t.me/BotFather)
2. Get your chat ID via [@userinfobot](https://t.me/userinfobot)
3. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   TELEGRAM_CHAT_ID=your_chat_id
   ```

---

## Important Notes

- **Always start on TESTNET** — set `BINANCE_TESTNET=true` in `.env`
- **Monitor the bot** — check logs in `logs/trading_bot.log`
- **Paper trade first** — validate signals match your manual analysis
- **Never risk more than you can afford to lose**

---

## License

Private — for personal use only.
