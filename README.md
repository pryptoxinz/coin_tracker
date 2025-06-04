# Crypto Trading Bot - Token Tracker

A modular and scalable cryptocurrency trading bot focused on Solana tokens and memecoins. This bot tracks token prices and holder counts, sending alerts via Telegram when significant changes occur.

## 🆓 100% FREE APIs

This bot uses **ONLY FREE APIs** - no paid subscriptions required:

- **Jupiter Price API**: Free, no API key needed
- **Solana Public RPC**: Multiple free endpoints available
- **Telegram Bot API**: Always free

## Features

- **Real-time Price Tracking**: Monitor token prices with customizable alert thresholds
- **Holder Count Tracking**: Track changes in token holder counts
- **Telegram Notifications**: Receive instant alerts for price changes and holder updates
- **Auto Chat ID Detection**: No need to find your chat ID manually!
- **CSV Data Storage**: All price and holder data is stored locally for backtesting
- **Modular Architecture**: Easy to extend with new strategies and features
- **Async/Concurrent**: Efficient handling of multiple tokens simultaneously

## Project Structure

```
crypto_bot/
├── src/
│   ├── api/           # API integrations (Jupiter, Solana)
│   ├── bot/           # Telegram bot functionality
│   ├── tracker/       # Token tracking logic
│   ├── storage/       # Data storage (CSV)
│   └── utils/         # Configuration and utilities
├── data/              # CSV data files (auto-created)
├── config/            # Configuration files
├── strategies/        # Trading strategies (future)
├── tests/             # Test files
└── main.py           # Main entry point
```

## Setup

### 1. Create a Telegram Bot
1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow the instructions
3. Save the bot token you receive

### 2. Install Dependencies
```bash
cd crypto_bot
pip install -r requirements.txt
```

### 3. Configure Environment
```bash
cp .env.example .env
```

Edit `.env` and add your bot token:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
# That's it! No need for chat ID
```

### 4. Run the Bot
```bash
python main.py
```

### 5. Start Using the Bot
1. Open your bot in Telegram (link will be shown when you run the bot)
2. Send `/start` to register yourself
3. The bot will automatically save your chat ID
4. You're ready to receive alerts!

## Bot Commands

- `/start` - Register to receive alerts
- `/status` - Check bot status
- `/tokens` - List tracked tokens
- `/threshold <value>` - Update price alert threshold
- `/add <token_address>` - Add a token to track
- `/remove <token_address>` - Remove a token
- `/stop` - Stop receiving alerts

## Adding Tokens to Track

Edit the `DEFAULT_TOKENS` list in `main.py`:
```python
DEFAULT_TOKENS = [
    "So11111111111111111111111111111111111111112",  # Wrapped SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "YourTokenAddressHere",  # Add your token
]
```

## Data Storage

All data is stored in CSV files in the `data/` directory:
- `{token_address}_prices.csv`: Price history
- `{token_address}_holders.csv`: Holder count history
- `alerts_log.csv`: All triggered alerts

## Extending the Bot

The modular architecture makes it easy to add features:

1. **New API Sources**: Extend `BaseAPI` in `src/api/base.py`
2. **New Storage Methods**: Implement new storage backends in `src/storage/`
3. **Trading Strategies**: Add strategy modules in `strategies/`
4. **Custom Alerts**: Extend `TelegramNotifier` in `src/bot/`

## Future Features

- Buy/Sell functionality
- Advanced trading strategies
- Backtesting framework
- Web dashboard
- Multiple exchange support
- Advanced technical indicators

## Free API Endpoints

### Jupiter Price API (Default)
- **URL**: https://price.jup.ag/v4/
- **Rate Limit**: Very generous, perfect for tracking
- **No API Key Required**

### Solana RPC Endpoints (All Free)
1. **Solana Public** (Default)
   - https://api.mainnet-beta.solana.com
   
2. **Alternative Free RPCs** (if rate limited):
   - https://solana-api.projectserum.com
   - https://rpc.ankr.com/solana
   - https://solana.public-rpc.com

To change RPC endpoint, update `.env`:
```env
SOLANA_RPC_URL=https://rpc.ankr.com/solana
```

## Important Notes

- All APIs used are 100% free
- Jupiter API is very reliable for Solana token prices
- Public RPC endpoints may have rate limits (switch if needed)
- Chat IDs are stored locally in `config/chat_ids.json`
- All times are in UTC