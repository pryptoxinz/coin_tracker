import asyncio
from typing import Dict, Any, Optional, List
from telegram import Bot
from telegram.error import TelegramError
from datetime import datetime

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_ids: Optional[List[str]] = None):
        self.bot = Bot(token=bot_token)
        self.chat_ids = chat_ids or []
        self._message_queue = asyncio.Queue()
        self._running = False
    
    async def start(self):
        self._running = True
        asyncio.create_task(self._process_messages())
    
    async def stop(self):
        self._running = False
    
    async def _process_messages(self):
        while self._running:
            try:
                if not self._message_queue.empty():
                    message = await self._message_queue.get()
                    await self._send_message(message)
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Error processing messages: {e}")
    
    async def _send_message(self, message: str):
        for chat_id in self.chat_ids:
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode='HTML'
                )
            except TelegramError as e:
                print(f"Failed to send Telegram message to {chat_id}: {e}")
    
    async def _send_message_to_user(self, user_id: str, message: str):
        """Send message to specific user"""
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode='HTML'
            )
        except TelegramError as e:
            print(f"Failed to send Telegram message to {user_id}: {e}")
    
    def format_price_alert(self, token_data: Dict[str, Any]) -> str:
        change_emoji = "📈" if token_data['change_percent'] > 0 else "📉"
        
        # Format market cap and liquidity
        market_cap = token_data.get('market_cap', 0)
        liquidity = token_data.get('liquidity', 0)
        volume_24h = token_data.get('volume_24h', 0)
        
        market_cap_str = f"${market_cap:,.0f}" if market_cap > 0 else "N/A"
        liquidity_str = f"${liquidity:,.0f}" if liquidity > 0 else "N/A"
        volume_str = f"${volume_24h:,.0f}" if volume_24h > 0 else "N/A"
        
        return (
            f"<b>🚨 {change_emoji} Price Alert!</b>\n\n"
            f"📊 <b>Token:</b> {token_data.get('token_name', 'Unknown')} ({token_data.get('token_symbol', 'UNK')})\n"
            f"🔗 <b>Address:</b> <code>{token_data['token_address'][:8]}...{token_data['token_address'][-8:]}</code>\n"
            f"⚡ <b>Price Change:</b> {token_data['change_percent']:+.2f}%\n"
            f"📉 <b>Old Price:</b> ${token_data['old_price']:.8f}\n"
            f"💰 <b>New Price:</b> ${token_data['new_price']:.8f}\n"
            f"📈 <b>Market Cap:</b> {market_cap_str}\n"
            f"💧 <b>Liquidity:</b> {liquidity_str}\n"
            f"📊 <b>24h Volume:</b> {volume_str}\n"
            f"🏪 <b>DEX:</b> {token_data.get('dex', 'unknown').title()}\n"
            f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
    
    def format_holder_alert(self, token_data: Dict[str, Any]) -> str:
        change = token_data['new_holders'] - token_data['old_holders']
        change_symbol = "+" if change > 0 else ""
        change_emoji = "📈" if change > 0 else "📉"
        
        return (
            f"<b>🚨 👥 Holder Count Alert!</b>\n\n"
            f"📊 <b>Token:</b> <code>{token_data['token_address']}</code>\n"
            f"⚡ <b>Change:</b> {change_emoji} {change_symbol}{change} holders\n"
            f"📉 <b>Old Count:</b> {token_data['old_holders']}\n"
            f"👥 <b>New Count:</b> {token_data['new_holders']}\n"
            f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
    
    async def send_price_alert(self, token_data: Dict[str, Any]):
        message = self.format_price_alert(token_data)
        await self._message_queue.put(message)
    
    async def send_holder_alert(self, token_data: Dict[str, Any]):
        message = self.format_holder_alert(token_data)
        await self._message_queue.put(message)
    
    async def send_custom_alert(self, message: str):
        await self._message_queue.put(message)
    
    async def send_message(self, message: str):
        """Public method to send messages directly"""
        await self._message_queue.put(message)
    
    async def send_error_alert(self, error_message: str):
        message = f"<b>🚨 ❌ Error Alert</b>\n\n{error_message}\n\n⏰ <i>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
        await self._message_queue.put(message)
    
    def update_chat_ids(self, chat_ids: List[str]):
        self.chat_ids = chat_ids
    
    async def send_message_to_user(self, user_id: str, message: str):
        """Public method to send message to specific user"""
        await self._send_message_to_user(user_id, message)
    
    async def send_price_alert_to_user(self, user_id: str, token_data: Dict[str, Any]):
        """Send price alert to specific user"""
        # Add entry price info if available
        entry_price = token_data.get('entry_price')
        
        change_emoji = "📈" if token_data['change_percent'] > 0 else "📉"
        
        # Format market cap and liquidity
        market_cap = token_data.get('market_cap', 0)
        liquidity = token_data.get('liquidity', 0)
        volume_24h = token_data.get('volume_24h', 0)
        
        market_cap_str = f"${market_cap:,.0f}" if market_cap > 0 else "N/A"
        liquidity_str = f"${liquidity:,.0f}" if liquidity > 0 else "N/A"
        volume_str = f"${volume_24h:,.0f}" if volume_24h > 0 else "N/A"
        
        message = (
            f"<b>🚨 {change_emoji} Price Alert!</b>\n\n"
            f"📊 <b>Token:</b> {token_data.get('token_name', 'Unknown')} ({token_data.get('token_symbol', 'UNK')})\n"
            f"🔗 <b>Address:</b> <code>{token_data['token_address'][:8]}...{token_data['token_address'][-8:]}</code>\n"
            f"⚡ <b>Price Change:</b> {token_data['change_percent']:+.2f}%\n"
            f"📉 <b>Old Price:</b> ${token_data['old_price']:.8f}\n"
            f"💰 <b>New Price:</b> ${token_data['new_price']:.8f}\n"
        )
        
        # Add entry price and total change if available
        if entry_price:
            total_change = ((token_data['new_price'] - entry_price) / entry_price) * 100
            message += f"🎯 <b>Entry Price:</b> ${entry_price:.8f}\n"
            message += f"📊 <b>Total Change:</b> {total_change:+.2f}%\n"
        
        message += (
            f"📈 <b>Market Cap:</b> {market_cap_str}\n"
            f"💧 <b>Liquidity:</b> {liquidity_str}\n"
            f"📊 <b>24h Volume:</b> {volume_str}\n"
            f"🏪 <b>DEX:</b> {token_data.get('dex', 'unknown').title()}\n"
            f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        
        await self._send_message_to_user(user_id, message)
    
    async def send_holder_alert_to_user(self, user_id: str, token_data: Dict[str, Any]):
        """Send holder alert to specific user"""
        change = token_data.get('change', token_data['new_holders'] - token_data['old_holders'])
        change_symbol = "+" if change > 0 else ""
        change_emoji = "📈" if change > 0 else "📉"
        
        message = (
            f"<b>🚨 👥 Holder Count Alert!</b>\n\n"
            f"📊 <b>Token:</b> {token_data.get('token_name', 'Unknown')} ({token_data.get('token_symbol', 'UNK')})\n"
            f"🔗 <b>Address:</b> <code>{token_data['token_address'][:8]}...{token_data['token_address'][-8:]}</code>\n"
            f"⚡ <b>Change:</b> {change_emoji} {change_symbol}{change} holders ({token_data.get('change_percent', 0):+.1f}%)\n"
            f"📉 <b>Old Count:</b> {token_data['old_holders']}\n"
            f"👥 <b>New Count:</b> {token_data['new_holders']}\n"
            f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        
        await self._send_message_to_user(user_id, message)