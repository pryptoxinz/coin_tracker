import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from ..api import DexScreenerAPI, SolanaTracker, APIError
from ..storage import CSVStorage
from ..bot import TelegramNotifier
from ..utils import config

logger = logging.getLogger(__name__)

class TokenTracker:
    def __init__(self, 
                 tokens: List[str],
                 price_threshold: float,
                 storage: CSVStorage,
                 notifier: TelegramNotifier,
                 check_interval: int = 60,
                 token_thresholds: Dict[str, Dict] = None):
        self.tokens = tokens
        self.price_threshold = price_threshold
        self.token_thresholds = token_thresholds or {}
        self.storage = storage
        self.notifier = notifier
        self.check_interval = check_interval
        self.dexscreener_api = DexScreenerAPI()
        self.solana_tracker = SolanaTracker(config.solana_rpc_url)
        self._running = False
        self._price_cache: Dict[str, float] = {}
        self._holder_cache: Dict[str, int] = {}
    
    async def start(self):
        self._running = True
        await self.notifier.start()
        
        await self._initialize_cache()
        
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
        for token in self.tokens:
            latest_price = await self.storage.get_latest_price(token)
            if latest_price:
                self._price_cache[token] = latest_price['price']
    
    async def _track_prices(self):
        async with self.dexscreener_api:
            while self._running:
                try:
                    for token in self.tokens:
                        await self._check_price(token)
                    
                    await asyncio.sleep(self.check_interval)
                except Exception as e:
                    await self.notifier.send_error_alert(f"Price tracking error: {str(e)}")
                    await asyncio.sleep(30)
    
    async def _track_holders(self):
        async with self.solana_tracker:
            while self._running:
                try:
                    for token in self.tokens:
                        await self._check_holders(token)
                    
                    await asyncio.sleep(self.check_interval * 5)
                except Exception as e:
                    await self.notifier.send_error_alert(f"Holder tracking error: {str(e)}")
                    await asyncio.sleep(60)
    
    async def _check_price(self, token_address: str):
        try:
            logger.info(f"Checking price for token {token_address}")
            async with self.dexscreener_api:
                price_data = await self.dexscreener_api.get_token_price(token_address)
            current_price = price_data['price']
            
            # Log detailed token information
            logger.info(f"Token data: {price_data['name']} ({price_data['symbol']}) - Price: ${current_price:.8f}, Market Cap: ${price_data.get('market_cap', 0):,.2f}, Liquidity: ${price_data.get('liquidity', 0):,.2f}")
            
            await self.storage.save_price_data(token_address, price_data)
            
            if token_address in self._price_cache:
                old_price = self._price_cache[token_address]
                if old_price > 0:
                    change_percent = ((current_price - old_price) / old_price) * 100
                    logger.info(f"Price change for {price_data['symbol']}: {change_percent:+.2f}%")
                    
                    # Use token-specific threshold if available, otherwise use global threshold
                    token_config = self.token_thresholds.get(token_address, {'value': self.price_threshold, 'direction': 'both'})
                    token_threshold = token_config.get('value', self.price_threshold)
                    token_direction = token_config.get('direction', 'both')
                    
                    # Check if the change meets the directional criteria
                    meets_threshold = False
                    if token_direction == 'both':
                        meets_threshold = abs(change_percent) >= token_threshold
                    elif token_direction == 'positive':
                        meets_threshold = change_percent >= token_threshold
                    elif token_direction == 'negative':
                        meets_threshold = change_percent <= -token_threshold
                    
                    if meets_threshold:
                        logger.warning(f"PRICE ALERT: {price_data['name']} ({price_data['symbol']}) changed {change_percent:+.2f}%")
                        
                        alert_data = {
                            'token_address': token_address,
                            'token_name': price_data['name'],
                            'token_symbol': price_data['symbol'],
                            'old_price': old_price,
                            'new_price': current_price,
                            'change_percent': change_percent,
                            'market_cap': price_data.get('market_cap', 0),
                            'liquidity': price_data.get('liquidity', 0),
                            'volume_24h': price_data.get('volume_24h', 0),
                            'dex': price_data.get('dex', 'unknown')
                        }
                        
                        await self.notifier.send_price_alert(alert_data)
                        
                        await self.storage.save_alert_log({
                            'token_address': token_address,
                            'alert_type': 'price',
                            'old_value': old_price,
                            'new_value': current_price,
                            'change_percent': change_percent
                        })
                    else:
                        direction_str = f"({token_direction})" if token_direction != 'both' else ""
                        logger.debug(f"Price change for {price_data['symbol']} ({change_percent:+.2f}%) below threshold ({token_threshold}% {direction_str})")
            else:
                logger.info(f"New token added to tracking: {price_data['name']} ({price_data['symbol']}) at ${current_price:.8f}")
            
            self._price_cache[token_address] = current_price
            
        except Exception as e:
            logger.error(f"Error checking price for {token_address}: {e}")
            console_msg = f"❌ Error checking price for {token_address}: {e}"
            print(console_msg)
    
    async def _check_holders(self, token_address: str):
        try:
            logger.info(f"Checking holder count for token {token_address}")
            async with self.solana_tracker:
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
                        
                        alert_data = {
                            'token_address': token_address,
                            'old_holders': old_count,
                            'new_holders': holder_count
                        }
                        
                        await self.notifier.send_holder_alert(alert_data)
                        
                        await self.storage.save_alert_log({
                            'token_address': token_address,
                            'alert_type': 'holders',
                            'old_value': old_count,
                            'new_value': holder_count,
                            'change_percent': change_percent
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
    
    async def add_token(self, token_address: str):
        if token_address not in self.tokens:
            self.tokens.append(token_address)
            
            # Save to persistent storage
            await self.storage.add_tracked_token(token_address)
            
            logger.info(f"✅ Token added to tracking: {token_address}")
            console_msg = f"✅ Token added to tracking: {token_address}"
            print(console_msg)
            
            # Send Telegram confirmation with token details
            await self._send_token_added_confirmation(token_address)
        else:
            logger.warning(f"Token {token_address} is already being tracked")
            console_msg = f"⚠️ Token {token_address} is already being tracked"
            print(console_msg)
    
    async def remove_token(self, token_address: str):
        if token_address in self.tokens:
            self.tokens.remove(token_address)
            self._price_cache.pop(token_address, None)
            self._holder_cache.pop(token_address, None)
            
            # Remove from persistent storage
            await self.storage.remove_tracked_token(token_address)
            
            logger.info(f"❌ Token removed from tracking: {token_address}")
            console_msg = f"❌ Token removed from tracking: {token_address}"
            print(console_msg)
        else:
            logger.warning(f"Token {token_address} was not being tracked")
            console_msg = f"⚠️ Token {token_address} was not being tracked"
            print(console_msg)
    
    def update_threshold(self, new_threshold: float):
        self.price_threshold = new_threshold
    
    async def set_token_threshold(self, token_address: str, threshold: float, direction: str = 'both'):
        """Set a specific threshold and direction for a token"""
        if token_address in self.tokens:
            if threshold > 0:
                self.token_thresholds[token_address] = {'value': threshold, 'direction': direction}
            else:
                self.token_thresholds.pop(token_address, None)
            
            # Save to storage
            await self.storage.set_token_threshold(token_address, threshold, direction)
    
    async def reset_price_reference(self, token_address: str):
        """Reset the price reference for a token to current price"""
        if token_address not in self.tokens:
            raise ValueError(f"Token {token_address} is not being tracked")
        
        try:
            # Get current price
            async with self.dexscreener_api:
                price_data = await self.dexscreener_api.get_token_price(token_address)
            current_price = price_data['price']
            
            # Update cache with new reference price
            self._price_cache[token_address] = current_price
            
            # Save the new reference price to storage
            await self.storage.save_price_data(token_address, price_data)
            
            logger.info(f"Price reference reset for {price_data['symbol']} to ${current_price:.8f}")
            
            # Send confirmation message
            message = f"🔄 **Price Reference Reset**\n\n"
            message += f"📊 **Token:** {price_data['name']} ({price_data['symbol']})\n"
            message += f"💰 **New Reference Price:** ${current_price:.8f}\n"
            message += f"📈 **Market Cap:** ${price_data.get('market_cap', 0):,.2f}\n"
            message += f"💧 **Liquidity:** ${price_data.get('liquidity', 0):,.2f}\n"
            message += f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
            message += f"✅ Future alerts will use this as the new baseline price."
            
            await self.notifier.send_message(message)
            
            return current_price
            
        except Exception as e:
            logger.error(f"Error resetting price reference for {token_address}: {e}")
            raise
    
    def get_token_threshold(self, token_address: str) -> float:
        """Get the threshold value for a specific token (returns global if no specific threshold)"""
        token_config = self.token_thresholds.get(token_address, {'value': self.price_threshold})
        return token_config.get('value', self.price_threshold)
    
    def get_token_direction(self, token_address: str) -> str:
        """Get the direction for a specific token"""
        token_config = self.token_thresholds.get(token_address, {'direction': 'both'})
        return token_config.get('direction', 'both')
    
    def get_token_by_name_or_symbol(self, query: str) -> Optional[str]:
        """Find token address by name or symbol"""
        query_lower = query.lower()
        # Simple lookup from cached token data
        for token_address in self.tokens:
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
                    for tracked_address in self.tokens:
                        try:
                            async with self.dexscreener_api:
                                temp_data = await self.dexscreener_api.get_token_price(tracked_address)
                            if (temp_data['name'].lower() == token_identifier.lower() or 
                                temp_data['symbol'].lower() == token_identifier.lower()):
                                token_address = tracked_address
                                break
                        except:
                            continue
                    else:
                        raise APIError(f"Token '{token_identifier}' not found in tracked tokens")
            
            # Check if token is being tracked
            if token_address not in self.tokens:
                raise APIError(f"Token '{token_identifier}' is not being tracked")
            
            # Get current data
            async with self.dexscreener_api:
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
    
    async def _send_token_added_confirmation(self, token_address: str):
        """Send Telegram confirmation with detailed token information when a new token is added"""
        try:
            # Get detailed token data from DexScreener
            async with self.dexscreener_api:
                token_data = await self.dexscreener_api.get_token_price(token_address)
            
            # Try to get holder count
            try:
                holder_count = await self.solana_tracker.get_token_holders_count(token_address)
                token_data['holder_count'] = holder_count
            except Exception as e:
                logger.warning(f"Could not get holder count for {token_address}: {e}")
                token_data['holder_count'] = 0
            
            # Format confirmation message with only requested variables
            message = f"🎯 **Token Successfully Added to Tracking!**\n\n"
            message += f"🏷️ **Name:** {token_data['name']}\n"
            message += f"🔤 **Symbol:** {token_data['symbol']}\n"
            message += f"🔗 **Address:** `{token_address}`\n"
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
            
            message += f"\n🎯 **Now tracking for price changes >= {self.price_threshold}%**"
            
            await self.notifier.send_message(message)
            
        except Exception as e:
            logger.error(f"Error sending token added confirmation: {e}")
            # Send basic confirmation if detailed data fails
            basic_message = f"✅ **Token Added to Tracking**\n\nAddress: `{token_address}`\nNow monitoring for price changes >= {self.price_threshold}%"
            await self.notifier.send_message(basic_message)