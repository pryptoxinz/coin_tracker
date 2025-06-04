import asyncio
import sys
import os
import signal
import atexit
import logging
from datetime import datetime
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.tracker import TokenTracker
from src.storage import CSVStorage
from src.bot import TelegramNotifier, TelegramHandler
from src.utils import config

def setup_logging():
    # Create logs directory if it doesn't exist
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    # Setup logging with both file and console handlers
    log_filename = log_dir / f"crypto_bot_{datetime.now().strftime('%Y%m%d')}.log"
    
    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set specific log levels for external libraries
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)
    
    return logging.getLogger(__name__)

DEFAULT_TOKENS = []

LOCK_FILE = Path(__file__).parent / "bot.lock"

def create_lock_file():
    if LOCK_FILE.exists():
        try:
            with open(LOCK_FILE, 'r') as f:
                old_pid = int(f.read().strip())
            try:
                os.kill(old_pid, 0)
                print(f"Error: Another instance is already running (PID: {old_pid})")
                print("If you're sure no other instance is running, delete the lock file:")
                print(f"rm {LOCK_FILE}")
                sys.exit(1)
            except OSError:
                print(f"Removing stale lock file from PID {old_pid}")
                LOCK_FILE.unlink()
        except (ValueError, FileNotFoundError):
            LOCK_FILE.unlink()
    
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))
    
    def cleanup_lock():
        try:
            LOCK_FILE.unlink()
        except FileNotFoundError:
            pass
    
    atexit.register(cleanup_lock)
    signal.signal(signal.SIGTERM, lambda sig, frame: (cleanup_lock(), sys.exit(0)))
    signal.signal(signal.SIGINT, lambda sig, frame: (cleanup_lock(), sys.exit(0)))

async def main():
    logger = setup_logging()
    create_lock_file()
    
    logger.info("🚀 Starting Crypto Trading Bot...")
    
    try:
        config.validate()
        logger.info("✅ Configuration validated successfully")
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
        print(f"Configuration error: {e}")
        print("Please copy .env.example to .env and fill in your Telegram bot token")
        return
    
    storage = CSVStorage(config.data_dir)
    
    # Load previously tracked tokens from storage
    tokens_to_track, token_thresholds = await storage.load_tracked_tokens()
    if not tokens_to_track:
        tokens_to_track = DEFAULT_TOKENS
        token_thresholds = {}
    
    active_chat_ids = config.get_active_chat_ids()
    
    telegram_handler = TelegramHandler()
    
    notifier = TelegramNotifier(
        bot_token=config.telegram_bot_token,
        chat_ids=telegram_handler.registered_users
    )
    
    tracker = TokenTracker(
        tokens=tokens_to_track,
        price_threshold=config.price_change_threshold,
        storage=storage,
        notifier=notifier,
        check_interval=config.check_interval,
        token_thresholds=token_thresholds
    )
    
    telegram_handler.set_tracker(tracker)
    
    async def update_notifier_chat_ids():
        while True:
            notifier.update_chat_ids(list(telegram_handler.registered_users))
            await asyncio.sleep(5)
    
    bot_info = await notifier.bot.get_me()
    logger.info(f"🤖 Bot initialized: @{bot_info.username}")
    logger.info(f"📊 Using DexScreener API for price data")
    
    print(f"Starting Crypto Trading Bot...")
    print(f"Bot Token: {config.telegram_bot_token[:10]}...")
    print(f"\n{'='*50}")
    print(f"IMPORTANT: Send /start to your bot to register!")
    print(f"Bot URL: https://t.me/{bot_info.username}")
    print(f"{'='*50}\n")
    
    if active_chat_ids:
        logger.info(f"👥 Found {len(active_chat_ids)} registered users")
        print(f"Found {len(active_chat_ids)} registered users")
    else:
        logger.warning("👥 No registered users yet")
        print("No registered users yet. Send /start to the bot!")
    
    if tokens_to_track:
        logger.info(f"📈 Tracking {len(tokens_to_track)} tokens: {', '.join(tokens_to_track[:3])}{'...' if len(tokens_to_track) > 3 else ''}")
        print(f"\nTracking {len(tokens_to_track)} tokens")
    else:
        logger.info("📈 No tokens configured for tracking yet")
        print(f"\nNo tokens configured for tracking yet")
    
    logger.info(f"⚙️ Price change threshold: {config.price_change_threshold}%")
    logger.info(f"⏱️ Check interval: {config.check_interval} seconds")
    print(f"Price change threshold: {config.price_change_threshold}%")
    print(f"Check interval: {config.check_interval} seconds")
    print("\nPress Ctrl+C to stop\n")
    
    try:
        logger.info("🔧 Initializing Telegram handler...")
        await telegram_handler.initialize()
        
        logger.info("🚀 Starting tracking services...")
        await asyncio.gather(
            tracker.start(),
            update_notifier_chat_ids()
        )
    except KeyboardInterrupt:
        logger.info("🛑 Received shutdown signal...")
        print("\nStopping bot...")
        await tracker.stop()
        await telegram_handler.shutdown()
        logger.info("✅ Bot stopped successfully")
        print("Bot stopped.")

if __name__ == "__main__":
    asyncio.run(main())