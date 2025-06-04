import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from ..api import DexScreenerAPI, SolanaTracker, APIError
from ..storage import CSVStorage
from ..storage.user_manager import UserManager
from ..bot import TelegramNotifier
from ..utils import config

logger = logging.getLogger(__name__)

class TokenTracker:
    def __init__(self, 
                 user_manager: UserManager,
                 storage: CSVStorage,
                 notifier: TelegramNotifier,
                 check_interval: int = 60):
        self.user_manager = user_manager
        self.storage = storage
        self.notifier = notifier
        self.check_interval = check_interval
        self.dexscreener_api = DexScreenerAPI()
        self.solana_tracker = SolanaTracker(config.solana_rpc_url)
        self._running = False
        self._price_cache: Dict[str, float] = {}
        self._holder_cache: Dict[str, int] = {}
        self._user_price_cache: Dict[str, Dict[str, float]] = {}  # Per-user price tracking
    
    async def start(self):
        self._running = True
        await self.notifier.start()
        
        await self._initialize_cache()
        await self._backfill_missing_entry_prices()
        
        tasks = [
            asyncio.create_task(self._track_prices()),
            asyncio.create_task(self._track_holders())
        ]
        
        await asyncio.gather(*tasks)
    
    async def stop(self):
        self._running = False
        await self.notifier.stop()
        await self.dexscreener_api.__aexit__(None, None, None)
        await self.solana_tracker.__aexit__(None, None, None)
    
    async def _initialize_cache(self):
        # Initialize global price cache for all tracked tokens
        all_tokens = self.user_manager.get_all_tracked_tokens()
        for token in all_tokens:
            latest_price = await self.storage.get_latest_price(token)
            if latest_price:
                self._price_cache[token] = latest_price['price']
        
        # Initialize per-user price cache with entry prices
        for user_id in self.user_manager.get_active_users():
            self._user_price_cache[user_id] = {}
            user_tokens = self.user_manager.get_user_tokens(user_id)
            for token in user_tokens:
                entry_price = self.user_manager.get_entry_price(user_id, token)
                if entry_price:
                    self._user_price_cache[user_id][token] = entry_price
                elif token in self._price_cache:
                    self._user_price_cache[user_id][token] = self._price_cache[token]
    
    async def _backfill_missing_entry_prices(self):
        """Backfill missing entry prices for tokens that don't have them"""
        logger.info("🔧 Starting entry price backfill for tracked tokens...")
        backfilled_count = 0
        
        for user_id in self.user_manager.get_active_users():
            user_tokens = self.user_manager.get_user_tokens(user_id)
            for token_address in user_tokens:
                entry_price = self.user_manager.get_entry_price(user_id, token_address)
                
                if entry_price is None:
                    # Missing entry price, try to get current price and set it
                    try:
                        price_data = await self.dexscreener_api.get_token_price(token_address)
                        current_price = price_data['price']
                        
                        # Set current price as entry price for backfill
                        self.user_manager.set_entry_price(user_id, token_address, current_price)
                        backfilled_count += 1
                        
                        logger.info(f"✅ Backfilled entry price for user {user_id}, token {price_data.get('symbol', token_address[:8])}: ${current_price:.8f}")
                        
                    except Exception as e:
                        logger.warning(f"❌ Could not backfill entry price for user {user_id}, token {token_address}: {e}")
        
        if backfilled_count > 0:
            logger.info(f"🎯 Entry price backfill complete: {backfilled_count} tokens updated")
        else:
            logger.info("✅ All tracked tokens already have entry prices")
    
    async def _track_prices(self):
        async with self.dexscreener_api:
            while self._running:
                try:
                    # Get all unique tokens being tracked by any user
                    all_tokens = self.user_manager.get_all_tracked_tokens()
                    
                    for token in all_tokens:
                        await self._check_price(token)
                    
                    await asyncio.sleep(self.check_interval)
                except Exception as e:
                    await self.notifier.send_error_alert(f"Price tracking error: {str(e)}")
                    await asyncio.sleep(30)
    
    async def _track_holders(self):
        async with self.solana_tracker:
            while self._running:
                try:
                    # Get all unique tokens being tracked by any user
                    all_tokens = self.user_manager.get_all_tracked_tokens()
                    
                    for token in all_tokens:
                        await self._check_holders(token)
                    
                    await asyncio.sleep(self.check_interval * 5)
                except Exception as e:
                    await self.notifier.send_error_alert(f"Holder tracking error: {str(e)}")
                    await asyncio.sleep(60)
    
    async def _check_price(self, token_address: str):
        try:
            logger.info(f"Checking price for token {token_address}")
            price_data = await self.dexscreener_api.get_token_price(token_address)
            current_price = price_data['price']
            
            # Log detailed token information
            logger.info(f"Token data: {price_data['name']} ({price_data['symbol']}) - Price: ${current_price:.8f}, Market Cap: ${price_data.get('market_cap', 0):,.2f}, Liquidity: ${price_data.get('liquidity', 0):,.2f}")
            
            await self.storage.save_price_data(token_address, price_data)
            
            # Check price changes for each user tracking this token
            users_tracking = self.user_manager.get_users_tracking_token(token_address)
            
            for user_id in users_tracking:
                # Get user's reference price (entry price or last alert price)
                user_ref_price = self._user_price_cache.get(user_id, {}).get(token_address)
                
                if user_ref_price and user_ref_price > 0:
                    change_percent = ((current_price - user_ref_price) / user_ref_price) * 100
                    
                    # Get user-specific threshold
                    threshold_config = self.user_manager.get_user_threshold(user_id, token_address)
                    token_threshold = threshold_config['value']
                    token_direction = threshold_config['direction']
                    
                    # Check if the change meets the directional criteria
                    meets_threshold = False
                    if token_direction == 'both':
                        meets_threshold = abs(change_percent) >= token_threshold
                    elif token_direction == 'positive':
                        meets_threshold = change_percent >= token_threshold
                    elif token_direction == 'negative':
                        meets_threshold = change_percent <= -token_threshold
                    
                    if meets_threshold:
                        logger.warning(f"PRICE ALERT for user {user_id}: {price_data['name']} ({price_data['symbol']}) changed {change_percent:+.2f}%")
                        
                        alert_data = {
                            'token_address': token_address,
                            'token_name': price_data['name'],
                            'token_symbol': price_data['symbol'],
                            'old_price': user_ref_price,
                            'new_price': current_price,
                            'change_percent': change_percent,
                            'market_cap': price_data.get('market_cap', 0),
                            'liquidity': price_data.get('liquidity', 0),
                            'volume_24h': price_data.get('volume_24h', 0),
                            'dex': price_data.get('dex', 'unknown'),
                            'user_id': user_id,
                            'entry_price': self.user_manager.get_entry_price(user_id, token_address)
                        }
                        
                        await self.notifier.send_price_alert_to_user(user_id, alert_data)
                        
                        await self.storage.save_alert_log({
                            'token_address': token_address,
                            'alert_type': 'price',
                            'old_value': user_ref_price,
                            'new_value': current_price,
                            'change_percent': change_percent,
                            'user_id': user_id
                        })
                    else:
                        direction_str = f"({token_direction})" if token_direction != 'both' else ""
                        logger.debug(f"Price change for {price_data['symbol']} user {user_id} ({change_percent:+.2f}%) below threshold ({token_threshold}% {direction_str})")
                else:
                    # First time tracking for this user
                    if user_id not in self._user_price_cache:
                        self._user_price_cache[user_id] = {}
                    self._user_price_cache[user_id][token_address] = current_price
                    logger.info(f"Initialized price tracking for user {user_id}: {price_data['name']} ({price_data['symbol']}) at ${current_price:.8f}")
            
            self._price_cache[token_address] = current_price
            
        except Exception as e:
            logger.error(f"Error checking price for {token_address}: {e}")
            console_msg = f"❌ Error checking price for {token_address}: {e}"
            print(console_msg)
    
    async def _check_holders(self, token_address: str):
        try:
            logger.info(f"Checking holder count for token {token_address}")
            holder_count = await self.solana_tracker.get_token_holders_count(token_address)
            
            logger.info(f"Token {token_address} has {holder_count} holders")
            
            await self.storage.save_holder_data(token_address, holder_count)
            
            if token_address in self._holder_cache:
                old_count = self._holder_cache[token_address]
                
                if old_count != holder_count:
                    change = holder_count - old_count
                    change_percent = (change / old_count * 100) if old_count > 0 else 0
                    logger.info(f"Holder count change for {token_address}: {change:+d} ({change_percent:+.1f}%)")
                    
                    if abs(change) >= 10 or abs(change_percent) >= 10:
                        logger.warning(f"HOLDER ALERT: Token {token_address} holder count changed by {change:+d} ({change_percent:+.1f}%)")
                        
                        # Get users tracking this token to send alerts only to them
                        users_tracking = self.user_manager.get_users_tracking_token(token_address)
                        
                        # Get token info for better alert message
                        token_info = {'name': 'Unknown', 'symbol': 'UNK'}
                        try:
                            price_data = await self.dexscreener_api.get_token_price(token_address)
                            token_info = {'name': price_data.get('name', 'Unknown'), 'symbol': price_data.get('symbol', 'UNK')}
                        except Exception as e:
                            logger.debug(f"Could not get token info for holder alert: {e}")
                            pass
                        
                        alert_data = {
                            'token_address': token_address,
                            'token_name': token_info['name'],
                            'token_symbol': token_info['symbol'],
                            'old_holders': old_count,
                            'new_holders': holder_count,
                            'change': change,
                            'change_percent': change_percent
                        }
                        
                        # Send alert to each user tracking this token
                        for user_id in users_tracking:
                            await self.notifier.send_holder_alert_to_user(user_id, alert_data)
                        
                        # Save alert log for each user
                        for user_id in users_tracking:
                            await self.storage.save_alert_log({
                                'token_address': token_address,
                                'alert_type': 'holders',
                                'old_value': old_count,
                                'new_value': holder_count,
                                'change_percent': change_percent,
                                'user_id': user_id
                            })
                    else:
                        logger.debug(f"Holder count change for {token_address} ({change:+d}) below alert threshold")
            else:
                logger.info(f"New token holder tracking initialized: {token_address} with {holder_count} holders")
            
            self._holder_cache[token_address] = holder_count
            
        except Exception as e:
            logger.error(f"Error checking holders for {token_address}: {e}")
            console_msg = f"❌ Error checking holders for {token_address}: {e}"
            print(console_msg)
    
    async def add_token(self, user_id: str, token_address: str):
        """Add token to user's tracking list"""
        # Check if user is registered
        if not self.user_manager.is_user_active(user_id):
            logger.warning(f"User {user_id} is not registered")
            return False
        
        # Check if user is already tracking this token
        user_tokens = self.user_manager.get_user_tokens(user_id)
        if token_address in user_tokens:
            logger.warning(f"User {user_id} is already tracking token {token_address}")
            console_msg = f"⚠️ User {user_id} is already tracking token {token_address}"
            print(console_msg)
            return False
        
        # Get current price as entry price
        entry_price = None
        try:
            price_data = await self.dexscreener_api.get_token_price(token_address)
            entry_price = price_data['price']
        except Exception as e:
            logger.error(f"Error getting entry price for {token_address}: {e}")
        
        # Add token to user's list
        success = self.user_manager.add_token_to_user(user_id, token_address, entry_price)
        
        if success:
            logger.info(f"✅ Token {token_address} added to tracking for user {user_id}")
            console_msg = f"✅ Token {token_address} added to tracking for user {user_id}"
            print(console_msg)
            
            # Initialize user price cache if needed
            if user_id not in self._user_price_cache:
                self._user_price_cache[user_id] = {}
            if entry_price:
                self._user_price_cache[user_id][token_address] = entry_price
            
            # Send Telegram confirmation with token details to specific user
            await self._send_token_added_confirmation(user_id, token_address)
            return True
        
        return False
    
    async def remove_token(self, user_id: str, token_address: str):
        """Remove token from user's tracking list"""
        # Check if user is registered
        if not self.user_manager.is_user_active(user_id):
            logger.warning(f"User {user_id} is not registered")
            return False
        
        # Remove token from user's list
        success = self.user_manager.remove_token_from_user(user_id, token_address)
        
        if success:
            # Remove from user's price cache
            if user_id in self._user_price_cache and token_address in self._user_price_cache[user_id]:
                del self._user_price_cache[user_id][token_address]
            
            logger.info(f"❌ Token {token_address} removed from tracking for user {user_id}")
            console_msg = f"❌ Token {token_address} removed from tracking for user {user_id}"
            print(console_msg)
            
            # Check if any other users are still tracking this token
            users_still_tracking = self.user_manager.get_users_tracking_token(token_address)
            if not users_still_tracking:
                # No users tracking this token anymore, remove from global cache
                self._price_cache.pop(token_address, None)
                self._holder_cache.pop(token_address, None)
                logger.info(f"No users tracking {token_address} anymore, removed from global cache")
            
            return True
        else:
            logger.warning(f"User {user_id} was not tracking token {token_address}")
            console_msg = f"⚠️ User {user_id} was not tracking token {token_address}"
            print(console_msg)
            return False
    
    def update_threshold(self, user_id: str, new_threshold: float):
        """Update user's global threshold"""
        success = self.user_manager.set_user_global_threshold(user_id, new_threshold)
        if success:
            logger.info(f"Updated global threshold for user {user_id} to {new_threshold}%")
        return success
    
    async def set_token_threshold(self, user_id: str, token_address: str, threshold: float, direction: str = 'both'):
        """Set a specific threshold and direction for a token for a user"""
        success = self.user_manager.set_user_token_threshold(user_id, token_address, threshold, direction)
        if success:
            logger.info(f"Set token threshold for user {user_id}, token {token_address}: {threshold}% ({direction})")
        return success
    
    async def reset_price_reference(self, user_id: str, token_address: str):
        """Reset the price reference for a token to current price for a specific user"""
        # Check if user is tracking this token
        user_tokens = self.user_manager.get_user_tokens(user_id)
        if token_address not in user_tokens:
            raise ValueError(f"User {user_id} is not tracking token {token_address}")
        
        try:
            # Get current price
            price_data = await self.dexscreener_api.get_token_price(token_address)
            current_price = price_data['price']
            
            # Update user's price cache with new reference price
            if user_id not in self._user_price_cache:
                self._user_price_cache[user_id] = {}
            self._user_price_cache[user_id][token_address] = current_price
            
            # Update global price cache
            self._price_cache[token_address] = current_price
            
            # Save the new reference price to storage
            await self.storage.save_price_data(token_address, price_data)
            
            logger.info(f"Price reference reset for user {user_id}, token {price_data['symbol']} to ${current_price:.8f}")
            
            # Get user's threshold for this token
            threshold_config = self.user_manager.get_user_threshold(user_id, token_address)
            
            # Send confirmation message to specific user
            message = f"🔄 **Price Reference Reset**\n\n"
            message += f"📊 **Token:** {price_data['name']} ({price_data['symbol']})\n"
            message += f"💰 **New Reference Price:** ${current_price:.8f}\n"
            message += f"📈 **Market Cap:** ${price_data.get('market_cap', 0):,.2f}\n"
            message += f"💧 **Liquidity:** ${price_data.get('liquidity', 0):,.2f}\n"
            message += f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
            message += f"🎯 **Your Threshold:** {threshold_config['value']}% ({threshold_config['direction']})\n"
            message += f"✅ Future alerts will use this as the new baseline price."
            
            await self.notifier.send_message_to_user(user_id, message)
            
            return current_price
            
        except Exception as e:
            logger.error(f"Error resetting price reference for user {user_id}, token {token_address}: {e}")
            raise
    
    def get_token_threshold(self, user_id: str, token_address: str) -> float:
        """Get the threshold value for a specific token for a user"""
        threshold_config = self.user_manager.get_user_threshold(user_id, token_address)
        return threshold_config['value']
    
    def get_token_direction(self, user_id: str, token_address: str) -> str:
        """Get the direction for a specific token for a user"""
        threshold_config = self.user_manager.get_user_threshold(user_id, token_address)
        return threshold_config['direction']
    
    def get_token_by_name_or_symbol(self, query: str) -> Optional[str]:
        """Find token address by name or symbol"""
        query_lower = query.lower()
        # Simple lookup from cached token data
        all_tokens = self.user_manager.get_all_tracked_tokens()
        for token_address in all_tokens:
            # We would need to store token metadata somewhere accessible
            # For now, return None - this needs the storage system
            pass
        return None
    
    async def get_token_info_with_timestamp(self, token_identifier: str) -> Dict[str, Any]:
        """Get current token information with timestamp"""
        try:
            # Check if identifier is an address or name/symbol
            token_address = token_identifier
            if not token_identifier.startswith(('1', '2', '3', '4', '5', '6', '7', '8', '9', 'A', 'B', 'C', 'D', 'E', 'F')):
                # Looks like name/symbol, try to find address
                found_address = self.get_token_by_name_or_symbol(token_identifier)
                if found_address:
                    token_address = found_address
                else:
                    # Search through tracked tokens for matching name/symbol
                    all_tokens = self.user_manager.get_all_tracked_tokens()
                    for tracked_address in all_tokens:
                        try:
                            temp_data = await self.dexscreener_api.get_token_price(tracked_address)
                            if (temp_data['name'].lower() == token_identifier.lower() or 
                                temp_data['symbol'].lower() == token_identifier.lower()):
                                token_address = tracked_address
                                break
                        except Exception as e:
                            logger.debug(f"Could not get token info for {tracked_address}: {e}")
                            continue
                    else:
                        raise APIError(f"Token '{token_identifier}' not found in tracked tokens")
            
            # Check if token is being tracked by any user
            all_tokens = self.user_manager.get_all_tracked_tokens()
            if token_address not in all_tokens:
                raise APIError(f"Token '{token_identifier}' is not being tracked by any user")
            
            # Get current data
            token_data = await self.dexscreener_api.get_token_price(token_address)
            
            # Try to get holder count
            try:
                holder_count = await self.solana_tracker.get_token_holders_count(token_address)
                token_data['holder_count'] = holder_count
            except Exception as e:
                logger.warning(f"Could not get holder count for {token_address}: {e}")
                token_data['holder_count'] = 0
            
            # Add timestamp
            token_data['fetched_at'] = datetime.now().isoformat()
            token_data['fetched_timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
            
            return token_data
            
        except Exception as e:
            logger.error(f"Error getting token info for {token_identifier}: {e}")
            raise APIError(f"Error getting token info: {str(e)}")
    
    async def _send_token_added_confirmation(self, user_id: str, token_address: str):
        """Send Telegram confirmation with detailed token information when a new token is added"""
        try:
            # Get detailed token data from DexScreener
            token_data = await self.dexscreener_api.get_token_price(token_address)
            
            # Try to get holder count
            try:
                holder_count = await self.solana_tracker.get_token_holders_count(token_address)
                token_data['holder_count'] = holder_count
            except Exception as e:
                logger.warning(f"Could not get holder count for {token_address}: {e}")
                token_data['holder_count'] = 0
            
            # Get user's threshold for this token
            threshold_config = self.user_manager.get_user_threshold(user_id, token_address)
            
            # Get entry price
            entry_price = self.user_manager.get_entry_price(user_id, token_address)
            
            # Format confirmation message with only requested variables
            message = f"🎯 **Token Successfully Added to Tracking!**\n\n"
            message += f"🏷️ **Name:** {token_data['name']}\n"
            message += f"🔤 **Symbol:** {token_data['symbol']}\n"
            message += f"🔗 **Address:** `{token_address}`\n"
            if entry_price:
                message += f"💰 **Entry Price:** ${entry_price:.8f}\n"
            message += f"📈 **Market Cap:** ${token_data.get('market_cap', 0):,.2f}\n"
            message += f"💧 **Liquidity:** ${token_data.get('liquidity', 0):,.2f}\n"
            message += f"📊 **24h Volume:** ${token_data.get('volume_24h', 0):,.2f}\n"
            
            # Volume 1h and 6h if available
            if token_data.get('volume_1h', 0) > 0:
                message += f"📊 **1h Volume:** ${token_data['volume_1h']:,.2f}\n"
            if token_data.get('volume_6h', 0) > 0:
                message += f"📊 **6h Volume:** ${token_data['volume_6h']:,.2f}\n"
            
            # Price changes
            if token_data.get('price_change_24h') is not None:
                change_24h = token_data['price_change_24h']
                emoji = "📈" if change_24h > 0 else "📉"
                message += f"📊 **24h Change:** {emoji} {change_24h:+.2f}%\n"
            
            if token_data.get('price_change_1h') is not None:
                change_1h = token_data['price_change_1h']
                emoji = "📈" if change_1h > 0 else "📉"
                message += f"⏰ **1h Change:** {emoji} {change_1h:+.2f}%\n"
            
            if token_data.get('price_change_6h') is not None:
                change_6h = token_data['price_change_6h']
                emoji = "📈" if change_6h > 0 else "📉"
                message += f"⏰ **6h Change:** {emoji} {change_6h:+.2f}%\n"
            
            # Trading activity
            buys_24h = token_data.get('txns_24h_buys', 0)
            sells_24h = token_data.get('txns_24h_sells', 0)
            if buys_24h > 0 or sells_24h > 0:
                message += f"🔄 **24h Transactions:** {buys_24h} buys / {sells_24h} sells\n"
            
            # Websites
            websites = token_data.get('websites', [])
            if websites:
                website_links = []
                for website in websites:
                    url = website.get('url', '')
                    label = website.get('label', 'Website')
                    if url:
                        website_links.append(f"[{label}]({url})")
                if website_links:
                    message += f"🌐 **Websites:** {' | '.join(website_links)}\n"
            
            # Social links
            socials = token_data.get('socials', [])
            if socials:
                social_links = []
                for social in socials:
                    social_type = social.get('type', '').lower()
                    social_url = social.get('url', '')
                    if social_url:
                        if social_type == 'twitter':
                            social_links.append(f"[Twitter]({social_url})")
                        elif social_type == 'telegram':
                            social_links.append(f"[Telegram]({social_url})")
                        elif social_type == 'discord':
                            social_links.append(f"[Discord]({social_url})")
                        elif social_type == 'website':
                            social_links.append(f"[Website]({social_url})")
                        else:
                            social_links.append(f"[{social_type.capitalize()}]({social_url})")
                if social_links:
                    message += f"🌐 **Socials:** {' | '.join(social_links)}\n"
            
            # Image URL if available
            if token_data.get('image_url'):
                message += f"🖼️ **Image:** [View]({token_data['image_url']})\n"
            
            message += f"\n🎯 **Your Alert Settings:**\n"
            message += f"📊 **Threshold:** {threshold_config['value']}%\n"
            message += f"🔄 **Direction:** {threshold_config['direction']}\n"
            
            await self.notifier.send_message_to_user(user_id, message)
            
        except Exception as e:
            logger.error(f"Error sending token added confirmation: {e}")
            # Send basic confirmation if detailed data fails
            threshold_config = self.user_manager.get_user_threshold(user_id, token_address)
            basic_message = f"✅ **Token Added to Tracking**\n\nAddress: `{token_address}`\nNow monitoring for price changes >= {threshold_config['value']}% ({threshold_config['direction']})"
            await self.notifier.send_message_to_user(user_id, basic_message)