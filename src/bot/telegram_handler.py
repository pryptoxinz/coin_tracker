import asyncio
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from typing import Optional, Set
from ..utils import config
from ..storage.user_manager import UserManager

logger = logging.getLogger(__name__)

class TelegramHandler:
    def __init__(self, user_manager: UserManager):
        self.app: Optional[Application] = None
        self.user_manager = user_manager
        self.tracker = None
    
    def set_tracker(self, tracker):
        self.tracker = tracker
    
    def get_main_menu_keyboard(self):
        """Return the main menu keyboard that should be shown with every message"""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Status", callback_data="status"),
                InlineKeyboardButton("🪙 Tokens", callback_data="tokens")
            ],
            [
                InlineKeyboardButton("➕ Add Token", callback_data="add_token"),
                InlineKeyboardButton("➖ Remove Token", callback_data="remove_token")
            ],
            [
                InlineKeyboardButton("📈 Get Token Info", callback_data="get_token"),
                InlineKeyboardButton("⚙️ Set Threshold", callback_data="set_threshold")
            ],
            [
                InlineKeyboardButton("🔄 Reset Price", callback_data="reset_price"),
                InlineKeyboardButton("📊 Recap", callback_data="recap")
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="help"),
                InlineKeyboardButton("❌ Stop Alerts", callback_data="stop_alerts")
            ]
        ])
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        user_name = update.effective_user.username or update.effective_user.first_name
        
        # Register user with UserManager
        self.user_manager.register_user(chat_id)
        
        # Get user's threshold  
        user_threshold = self.user_manager.get_user_threshold(chat_id)['value']
        
        welcome_message = (
            f"Welcome {user_name}! 🚀\n\n"
            "Your chat ID has been saved. You will now receive alerts for:\n"
            f"• Price changes > {user_threshold}%\n"
            f"• Significant holder count changes\n\n"
            "Use the buttons below or type commands:"
        )
        
        reply_markup = self.get_main_menu_keyboard()
        
        await update.message.reply_text(welcome_message, reply_markup=reply_markup)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._is_authorized(update):
            return
        
        chat_id = str(update.effective_chat.id)
        user_data = self.user_manager.get_user(chat_id)
        
        if not user_data:
            await update.message.reply_text("User not found. Please send /start first.", reply_markup=self.get_main_menu_keyboard())
            return
        
        # Get user's tokens count
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        status_message = (
            f"🟢 Bot Status: Active\n\n"
            f"Your Settings:\n"
            f"• Price Threshold: {user_data['global_threshold']}%\n"
            f"• Tracked Tokens: {len(user_tokens)}\n"
            f"• Alerts: {'Enabled' if user_data['active'] else 'Disabled'}\n\n"
            f"Global Settings:\n"
            f"• Check Interval: {config.check_interval}s\n"
        )
        
        await update.message.reply_text(status_message, reply_markup=self.get_main_menu_keyboard())
    
    async def tokens_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._is_authorized(update):
            return
        
        chat_id = str(update.effective_chat.id)
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        if not user_tokens:
            await update.message.reply_text("You are not tracking any tokens.", reply_markup=self.get_main_menu_keyboard())
            return
        
        message = "📊 Your Tracked Tokens:\n\n"
        for i, token_address in enumerate(user_tokens, 1):
            threshold_config = self.user_manager.get_user_threshold(chat_id, token_address)
            threshold = threshold_config['value']
            direction = threshold_config.get('direction', 'both')
            user_global_threshold = self.user_manager.get_user_threshold(chat_id)['value']
            
            direction_emoji = {
                'both': '📊',
                'positive': '📈',
                'negative': '📉'
            }.get(direction, '📊')
            
            # Get token name/symbol for display
            if self.tracker:
                try:
                    token_info = await self.tracker.get_token_info_with_timestamp(token_address)
                    token_display = f"${token_info['symbol']}"
                except:
                    # Fallback to shortened address if token info unavailable
                    token_display = f"{token_address[:8]}...{token_address[-8:]}"
            else:
                token_display = f"{token_address[:8]}...{token_address[-8:]}"
            
            if threshold == user_global_threshold and direction == 'both':
                message += f"{i}. <code>{token_display}</code> {direction_emoji} (Your Default: {threshold}%)\n"
            else:
                message += f"{i}. <code>{token_display}</code> {direction_emoji} (Custom: {threshold}% {direction})\n"
        
        await update.message.reply_text(message, parse_mode='HTML', reply_markup=self.get_main_menu_keyboard())
    
    async def threshold_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._is_authorized(update):
            return
        
        if not context.args or len(context.args) != 1:
            await update.message.reply_text("Usage: /threshold <value>\nExample: /threshold 15", reply_markup=self.get_main_menu_keyboard())
            return
        
        try:
            new_threshold = float(context.args[0])
            if new_threshold <= 0 or new_threshold > 100:
                await update.message.reply_text("Threshold must be between 0 and 100", reply_markup=self.get_main_menu_keyboard())
                return
            
            chat_id = str(update.effective_chat.id)
            self.user_manager.set_user_global_threshold(chat_id, new_threshold)
            
            await update.message.reply_text(f"✅ Your price threshold updated to {new_threshold}%", reply_markup=self.get_main_menu_keyboard())
        except ValueError:
            await update.message.reply_text("Invalid threshold value. Please enter a number.", reply_markup=self.get_main_menu_keyboard())
    
    async def set_token_threshold_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set threshold for a specific token: /setthreshold <token_address> <threshold> [direction]"""
        if not await self._is_authorized(update):
            return
        
        if not context.args or len(context.args) < 2 or len(context.args) > 3:
            await update.message.reply_text(
                "Usage: /setthreshold <token_address> <threshold> [direction]\n\n"
                "Directions:\n"
                "• `both` - Alert on positive OR negative changes (default)\n"
                "• `positive` - Alert only on price increases\n"
                "• `negative` - Alert only on price decreases\n\n"
                "Examples:\n"
                "• `/setthreshold 6MQpbiTC2YcogidTmKqMLK82qvE9z5QEm7EP3AEDpump 25`\n"
                "• `/setthreshold 6MQpbiTC2YcogidTmKqMLK82qvE9z5QEm7EP3AEDpump 15 positive`",
                parse_mode='Markdown'
            )
            return
        
        token_address = context.args[0]
        direction = context.args[2].lower() if len(context.args) > 2 else 'both'
        
        if direction not in ['both', 'positive', 'negative']:
            await update.message.reply_text("Direction must be 'both', 'positive', or 'negative'")
            return
        
        try:
            threshold = float(context.args[1])
            if threshold <= 0 or threshold > 100:
                await update.message.reply_text("Threshold must be between 0 and 100")
                return
            
            chat_id = str(update.effective_chat.id)
            user_tokens = self.user_manager.get_user_tokens(chat_id)
            
            if token_address not in user_tokens:
                await update.message.reply_text(f"You are not tracking this token. Add it first with /add")
                return
            
            # Update token threshold for this user
            self.user_manager.set_user_token_threshold(chat_id, token_address, threshold, direction)
            
            # Add inline keyboard
            keyboard = [
                [
                    InlineKeyboardButton("📊 Status", callback_data="status"),
                    InlineKeyboardButton("🪙 Tokens", callback_data="tokens")
                ],
                [
                    InlineKeyboardButton("📈 Main Menu", callback_data="back_to_main")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            direction_emoji = {
                'both': '📊',
                'positive': '📈',
                'negative': '📉'
            }.get(direction, '📊')
            
            if self.tracker:
                try:
                    token_data = await self.tracker.get_token_info_with_timestamp(token_address)
                    token_display = f"${token_data['symbol']}"
                except:
                    token_display = f"{token_address[:8]}...{token_address[-8:]}"
            else:
                token_display = f"{token_address[:8]}...{token_address[-8:]}"
                
            await update.message.reply_text(
                f"✅ Your threshold for {token_display} set to {threshold}% {direction_emoji} ({direction})",
                reply_markup=reply_markup
            )
            
        except ValueError:
            await update.message.reply_text("Invalid threshold value. Please enter a number.", reply_markup=self.get_main_menu_keyboard())
    
    async def add_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._is_authorized(update):
            return
        
        if not context.args or len(context.args) != 1:
            await update.message.reply_text("Usage: /add <token_address>", reply_markup=self.get_main_menu_keyboard())
            return
        
        token_address = context.args[0]
        chat_id = str(update.effective_chat.id)
        
        # Check if user already tracks this token
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        if token_address in user_tokens:
            # Show token info instead of error
            if self.tracker:
                try:
                    token_data = await self.tracker.get_token_info_with_timestamp(token_address)
                    
                    # Get user's threshold for this token
                    threshold_config = self.user_manager.get_user_threshold(chat_id, token_address)
                    entry_price = self.user_manager.get_entry_price(chat_id, token_address)
                    
                    message = f"ℹ️ **Already Tracking This Token**\n\n"
                    message += f"🏷️ **Name:** {token_data['name']}\n"
                    message += f"🔤 **Symbol:** {token_data['symbol']}\n"
                    message += f"💰 **Current Price:** ${token_data['price']:.8f}\n"
                    if entry_price:
                        price_change = ((token_data['price'] - entry_price) / entry_price) * 100
                        emoji = "📈" if price_change > 0 else "📉"
                        message += f"📊 **Entry Price:** ${entry_price:.8f}\n"
                        message += f"📊 **Entry Performance:** {emoji} {price_change:+.2f}% since entry\n"
                    message += f"📈 **Market Cap:** ${token_data.get('market_cap', 0):,.2f}\n"
                    message += f"💧 **Liquidity:** ${token_data.get('liquidity', 0):,.2f}\n"
                    message += f"🎯 **Your Threshold:** {threshold_config['value']}% ({threshold_config['direction']})\n"
                    
                    # Add action buttons
                    keyboard = [
                        [
                            InlineKeyboardButton("🔄 Reset Price Reference", callback_data=f"reset_price:{token_address}"),
                            InlineKeyboardButton("⚙️ Set Threshold", callback_data=f"set_threshold:{token_address}")
                        ],
                        [
                            InlineKeyboardButton("❌ Remove Token", callback_data=f"remove:{token_address}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
                    return
                except Exception as e:
                    # Fallback to basic message if token info fails
                    pass
            
            await update.message.reply_text(
                f"⚠️ You are already tracking this token.\n\n"
                f"Address: <code>{token_address}</code>",
                parse_mode='HTML',
                reply_markup=self.get_main_menu_keyboard()
            )
            return
        
        # Add token via tracker (handles entry price automatically)
        if self.tracker:
            await self.tracker.add_token(chat_id, token_address)
        else:
            # Fallback if tracker not available
            self.user_manager.add_token_to_user(chat_id, token_address)
        
        await update.message.reply_text(f"✅ Token added to your tracking list!", reply_markup=self.get_main_menu_keyboard())
    
    async def get_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._is_authorized(update):
            return
        
        if not context.args or len(context.args) != 1:
            await update.message.reply_text("Usage: /get <token_name/symbol/address>\nExample: /get MASK or /get catwifmask", reply_markup=self.get_main_menu_keyboard())
            return
        
        token_identifier = context.args[0]
        
        if not self.tracker:
            await update.message.reply_text("Tracker not available.", reply_markup=self.get_main_menu_keyboard())
            return
        
        try:
            token_data = await self.tracker.get_token_info_with_timestamp(token_identifier)
            
            # Format message with only requested variables
            chat_id = str(update.effective_chat.id)
            message = f"📊 **Token Information**\n\n"
            message += f"🏷️ **Name:** {token_data['name']}\n"
            message += f"🔤 **Symbol:** {token_data['symbol']}\n"
            message += f"🔗 **Address:** `{token_data['address']}`\n"
            message += f"💰 **Current Price:** ${token_data['price']:.8f}\n"
            
            # Check if user is tracking this token and show entry performance
            user_tokens = self.user_manager.get_user_tokens(chat_id)
            if token_data['address'] in user_tokens:
                entry_price = self.user_manager.get_entry_price(chat_id, token_data['address'])
                if entry_price:
                    price_change = ((token_data['price'] - entry_price) / entry_price) * 100
                    emoji = "📈" if price_change > 0 else "📉"
                    message += f"📊 **Entry Price:** ${entry_price:.8f}\n"
                    message += f"📊 **Entry Performance:** {emoji} {price_change:+.2f}% since entry\n"
                message += f"🎯 **You're tracking this token**\n"
            
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
            
            # Create keyboard with copy address button
            keyboard = [
                [
                    InlineKeyboardButton("📋 Copy Address", callback_data=f"copy:{token_data['address']}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=reply_markup)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def remove_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._is_authorized(update):
            return
        
        if not context.args or len(context.args) != 1:
            await update.message.reply_text("Usage: /remove <token_address>", reply_markup=self.get_main_menu_keyboard())
            return
        
        token_address = context.args[0]
        chat_id = str(update.effective_chat.id)
        
        # Check if user tracks this token
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        if token_address not in user_tokens:
            await update.message.reply_text("You are not tracking this token.", reply_markup=self.get_main_menu_keyboard())
            return
        
        # Remove token for this user
        self.user_manager.remove_token_from_user(chat_id, token_address)
        
        # Check if any other users are tracking this token
        # If not, remove from tracker
        if self.tracker:
            still_tracked = False
            for user_id in self.user_manager.get_active_users():
                if token_address in self.user_manager.get_user_tokens(user_id):
                    still_tracked = True
                    break
            
            if not still_tracked:
                await self.tracker.remove_token(chat_id, token_address)
        
        await update.message.reply_text(f"✅ Removed token from your tracking list", parse_mode='HTML', reply_markup=self.get_main_menu_keyboard())
    
    async def reset_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reset price reference for a token: /reset <token_address>"""
        if not await self._is_authorized(update):
            return
        
        if not context.args or len(context.args) != 1:
            await update.message.reply_text(
                "Usage: /reset <token_address>\n\n"
                "This will reset the price reference to the current price.\n"
                "Future alerts will use this new price as the baseline.\n\n"
                "Example: `/reset 6MQpbiTC2YcogidTmKqMLK82qvE9z5QEm7EP3AEDpump`",
                parse_mode='Markdown',
                reply_markup=self.get_main_menu_keyboard()
            )
            return
        
        token_address = context.args[0]
        chat_id = str(update.effective_chat.id)
        
        if not self.tracker:
            await update.message.reply_text("Tracker not available.", reply_markup=self.get_main_menu_keyboard())
            return
        
        # Check if user tracks this token
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        if token_address not in user_tokens:
            await update.message.reply_text(f"You are not tracking this token.", reply_markup=self.get_main_menu_keyboard())
            return
        
        try:
            # Reset price reference for this user
            new_price = await self.tracker.reset_price_reference(chat_id, token_address)
            short_token = f"{token_address[:8]}...{token_address[-8:]}"
            await update.message.reply_text(
                f"✅ **Price Reference Reset**\n\n"
                f"Token: {short_token}\n"
                f"New reference price: ${new_price:.8f}\n\n"
                f"Your future alerts will use this as the baseline price.",
                parse_mode='Markdown',
                reply_markup=self.get_main_menu_keyboard()
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error resetting price reference: {str(e)}", reply_markup=self.get_main_menu_keyboard())
    
    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        
        # Deactivate user
        self.user_manager.deactivate_user(chat_id)
        
        await update.message.reply_text("You have been unsubscribed from alerts. Send /start to subscribe again.", reply_markup=self.get_main_menu_keyboard())
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button presses"""
        query = update.callback_query
        await query.answer()
        
        callback_data = query.data
        
        if callback_data == "status":
            await self._handle_status_button(query, context)
        elif callback_data == "tokens":
            await self._handle_tokens_button(query, context)
        elif callback_data == "add_token":
            await self._handle_add_token_button(query, context)
        elif callback_data == "remove_token":
            await self._handle_remove_token_button(query, context)
        elif callback_data == "get_token":
            await self._handle_get_token_button(query, context)
        elif callback_data == "set_threshold":
            await self._handle_set_threshold_button(query, context)
        elif callback_data == "stop_alerts":
            await self._handle_stop_alerts_button(query, context)
        elif callback_data == "recap":
            await self._handle_recap_button(query, context)
        elif callback_data == "reset_price":
            await self._handle_reset_price_button(query, context)
        elif callback_data == "help":
            await self._handle_help_button(query, context)
        elif callback_data.startswith("remove:"):
            token_address = callback_data.split(":", 1)[1]
            await self._handle_remove_specific_token(query, context, token_address)
        elif callback_data.startswith("track:"):
            token_address = callback_data.split(":", 1)[1]
            await self._handle_track_token(query, context, token_address)
        elif callback_data.startswith("refresh:"):
            token_address = callback_data.split(":", 1)[1]
            await self._handle_refresh_token(query, context, token_address)
        elif callback_data.startswith("reset_price:"):
            token_address = callback_data.split(":", 1)[1]
            await self._handle_reset_price_specific(query, context, token_address)
        elif callback_data.startswith("copy:"):
            token_address = callback_data.split(":", 1)[1]
            await self._handle_copy_address(query, context, token_address)
        elif callback_data.startswith("show_token:"):
            token_address = callback_data.split(":", 1)[1]
            await self._handle_show_token_info(query, context, token_address)
        elif callback_data.startswith("set_threshold:"):
            token_address = callback_data.split(":", 1)[1]
            await self._handle_set_threshold_specific(query, context, token_address)
        elif callback_data == "separator":
            # Ignore separator button clicks
            await query.answer()
            return
        elif callback_data == "back_to_main":
            await self._handle_back_to_main(query, context)
    
    async def _handle_status_button(self, query, context):
        if not await self._is_authorized_query(query):
            return
        
        chat_id = str(query.from_user.id)
        user_data = self.user_manager.get_user(chat_id)
        
        if not user_data:
            await query.edit_message_text("User not found. Please send /start first.", reply_markup=self.get_main_menu_keyboard())
            return
        
        # Get user's tokens count
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        status_message = (
            f"🟢 Bot Status: Active\n\n"
            f"Your Settings:\n"
            f"• Price Threshold: {user_data['global_threshold']}%\n"
            f"• Tracked Tokens: {len(user_tokens)}\n"
            f"• Alerts: {'Enabled' if user_data['active'] else 'Disabled'}\n\n"
            f"Global Settings:\n"
            f"• Check Interval: {config.check_interval}s\n"
        )
        
        await query.edit_message_text(status_message, reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_tokens_button(self, query, context):
        if not await self._is_authorized_query(query):
            return
        
        chat_id = str(query.from_user.id)
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        if not user_tokens:
            await query.edit_message_text("You are not tracking any tokens.", reply_markup=self.get_main_menu_keyboard())
            return
        
        message = "📊 Your Tracked Tokens:\n\n"
        for i, token_address in enumerate(user_tokens, 1):
            threshold_config = self.user_manager.get_user_threshold(chat_id, token_address)
            threshold = threshold_config['value']
            direction = threshold_config.get('direction', 'both')
            user_global_threshold = self.user_manager.get_user_threshold(chat_id)['value']
            
            direction_emoji = {
                'both': '📊',
                'positive': '📈',
                'negative': '📉'
            }.get(direction, '📊')
            
            # Get token name/symbol for display
            if self.tracker:
                try:
                    token_info = await self.tracker.get_token_info_with_timestamp(token_address)
                    token_display = f"${token_info['symbol']}"
                except:
                    # Fallback to shortened address if token info unavailable
                    token_display = f"{token_address[:8]}...{token_address[-8:]}"
            else:
                token_display = f"{token_address[:8]}...{token_address[-8:]}"
            
            if threshold == user_global_threshold and direction == 'both':
                message += f"{i}. <code>{token_display}</code> {direction_emoji} (Your Default: {threshold}%)\n"
            else:
                message += f"{i}. <code>{token_display}</code> {direction_emoji} (Custom: {threshold}% {direction})\n"
        
        await query.edit_message_text(message, parse_mode='HTML', reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_add_token_button(self, query, context):
        if not await self._is_authorized_query(query):
            return
        
        await query.edit_message_text(
            "To add a token, send me the token address.\n\n"
            "Format: <code>token_address</code>\n"
            "Example: <code>6MQpbiTC2YcogidTmKqMLK82qvE9z5QEm7EP3AEDpump</code>",
            parse_mode='HTML',
            reply_markup=self.get_main_menu_keyboard()
        )
    
    async def _handle_remove_token_button(self, query, context):
        if not await self._is_authorized_query(query):
            return
        
        chat_id = str(query.from_user.id)
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        if not user_tokens:
            await query.edit_message_text("You are not tracking any tokens.", reply_markup=self.get_main_menu_keyboard())
            return
        
        # Create buttons for each token to remove
        keyboard = []
        for token_address in user_tokens[:10]:  # Limit to 10 tokens
            if self.tracker:
                try:
                    token_data = await self.tracker.get_token_info_with_timestamp(token_address)
                    token_display = f"${token_data['symbol']}"
                except:
                    token_display = f"{token_address[:8]}...{token_address[-8:]}"
            else:
                token_display = f"{token_address[:8]}...{token_address[-8:]}"
            keyboard.append([InlineKeyboardButton(f"❌ {token_display}", callback_data=f"remove:{token_address}")])
        
        keyboard.append([InlineKeyboardButton("« Back", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text("Select a token to remove:", reply_markup=reply_markup)
    
    async def _handle_get_token_button(self, query, context):
        if not await self._is_authorized_query(query):
            return
        
        chat_id = str(query.from_user.id)
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        message = "📈 **Get Token Info**\n\n"
        
        if user_tokens:
            message += "**Your Tracked Tokens:**\n"
            keyboard = []
            
            # Add buttons for user's tracked tokens (limit to 10)
            for token_address in list(user_tokens)[:10]:
                if self.tracker:
                    try:
                        token_data = await self.tracker.get_token_info_with_timestamp(token_address)
                        token_display = f"{token_data['symbol']}"
                    except:
                        token_display = f"{token_address[:8]}...{token_address[-8:]}"
                else:
                    token_display = f"{token_address[:8]}...{token_address[-8:]}"
                
                keyboard.append([InlineKeyboardButton(f"📊 {token_display}", callback_data=f"show_token:{token_address}")])
            
            # Add separator and instructions
            keyboard.append([InlineKeyboardButton("─────────────", callback_data="separator")])
            message += "\nClick a token above to see its info, or send:\n\n"
        else:
            message += "You have no tracked tokens yet.\n\n"
            message += "To get token info, send me:\n\n"
            keyboard = []
        
        message += "• Token name: <code>MASK</code>\n"
        message += "• Token symbol: <code>catwifmask</code>\n"
        message += "• Token address: <code>6MQpbiTC2YcogidTmKqMLK82qvE9z5QEm7EP3AEDpump</code>"
        
        # Add back button
        keyboard.append([InlineKeyboardButton("« Back to Main Menu", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, parse_mode='HTML', reply_markup=reply_markup)
    
    async def _handle_set_threshold_button(self, query, context):
        if not await self._is_authorized_query(query):
            return
        
        chat_id = str(query.from_user.id)
        user_threshold = self.user_manager.get_user_threshold(chat_id)['value']
        
        await query.edit_message_text(
            "To set a new price threshold, send me a number.\n\n"
            f"Your current threshold: {user_threshold}%\n"
            "Example: <code>15</code> (for 15%)",
            parse_mode='HTML',
            reply_markup=self.get_main_menu_keyboard()
        )
    
    async def _handle_stop_alerts_button(self, query, context):
        chat_id = str(query.from_user.id)
        
        # Deactivate user
        self.user_manager.deactivate_user(chat_id)
        
        await query.edit_message_text("You have been unsubscribed from alerts. Send /start to subscribe again.", reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_remove_specific_token(self, query, context, token_address):
        if not await self._is_authorized_query(query):
            return
        
        chat_id = str(query.from_user.id)
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        if token_address not in user_tokens:
            await query.edit_message_text("You are not tracking this token.", reply_markup=self.get_main_menu_keyboard())
            return
        
        # Remove token for this user
        self.user_manager.remove_token_from_user(chat_id, token_address)
        
        # Check if any other users are tracking this token
        if self.tracker:
            still_tracked = False
            for user_id in self.user_manager.get_active_users():
                if token_address in self.user_manager.get_user_tokens(user_id):
                    still_tracked = True
                    break
            
            if not still_tracked:
                await self.tracker.remove_token(chat_id, token_address)
        
        if self.tracker:
            try:
                token_data = await self.tracker.get_token_info_with_timestamp(token_address)
                token_display = f"${token_data['symbol']}"
            except:
                token_display = f"{token_address[:8]}...{token_address[-8:]}"
        else:
            token_display = f"{token_address[:8]}...{token_address[-8:]}"
        
        await query.edit_message_text(f"✅ Removed token: {token_display}", reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_back_to_main(self, query, context):
        # Recreate main menu
        await query.edit_message_text("🏠 Main Menu - Use the buttons below or type commands:", reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_track_token(self, query, context, token_address):
        """Handle tracking a token from inline button"""
        if not await self._is_authorized_query(query):
            return
        
        if not self.tracker:
            await query.edit_message_text("Tracker not available.", reply_markup=self.get_main_menu_keyboard())
            return
        
        chat_id = str(query.from_user.id)
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        if token_address in user_tokens:
            await query.edit_message_text("You are already tracking this token.", reply_markup=self.get_main_menu_keyboard())
            return
        
        # Add token via tracker (handles entry price automatically)
        if self.tracker:
            await self.tracker.add_token(chat_id, token_address)
        else:
            # Fallback if tracker not available
            self.user_manager.add_token_to_user(chat_id, token_address)
        
        try:
            token_data = await self.tracker.get_token_info_with_timestamp(token_address)
            token_display = f"${token_data['symbol']}"
        except:
            token_display = f"{token_address[:8]}...{token_address[-8:]}"
        await query.edit_message_text(f"✅ Now tracking token: {token_display}", reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_refresh_token(self, query, context, token_address):
        """Handle refreshing token info from inline button"""
        if not await self._is_authorized_query(query):
            return
        
        if not self.tracker:
            await query.edit_message_text("Tracker not available.")
            return
        
        try:
            token_data = await self.tracker.get_token_info_with_timestamp(token_address)
            
            # Format refreshed message with only requested variables
            chat_id = str(query.from_user.id)
            message = f"🔄 **Refreshed Token Info**\n\n"
            message += f"🏷️ **Name:** {token_data['name']}\n"
            message += f"🔤 **Symbol:** {token_data['symbol']}\n"
            message += f"🔗 **Address:** `{token_data['address']}`\n"
            message += f"💰 **Current Price:** ${token_data['price']:.8f}\n"
            
            # Check if user is tracking this token and show entry performance
            user_tokens = self.user_manager.get_user_tokens(chat_id)
            if token_data['address'] in user_tokens:
                entry_price = self.user_manager.get_entry_price(chat_id, token_data['address'])
                if entry_price:
                    price_change = ((token_data['price'] - entry_price) / entry_price) * 100
                    emoji = "📈" if price_change > 0 else "📉"
                    message += f"📊 **Entry Price:** ${entry_price:.8f}\n"
                    message += f"📊 **Entry Performance:** {emoji} {price_change:+.2f}% since entry\n"
                message += f"🎯 **You're tracking this token**\n"
            
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
            
            message += f"\n🕐 **Updated:** {token_data['fetched_timestamp']}"
            
            # Update keyboard
            keyboard = [
                [
                    InlineKeyboardButton("➕ Track This", callback_data=f"track:{token_address}"),
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh:{token_address}")
                ],
                [
                    InlineKeyboardButton("📋 Copy Address", callback_data=f"copy:{token_address}")
                ],
                [
                    InlineKeyboardButton("📈 Main Menu", callback_data="back_to_main")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)
            
        except Exception as e:
            await query.edit_message_text(f"❌ Error refreshing token data: {str(e)}", reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_recap_button(self, query, context):
        """Handle recap button press"""
        if not await self._is_authorized_query(query):
            return
        
        chat_id = str(query.from_user.id)
        user_data = self.user_manager.get_user(chat_id)
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        if not user_tokens:
            await query.edit_message_text("📊 Recap: You are not tracking any tokens.", reply_markup=self.get_main_menu_keyboard())
            return
        
        recap_message = f"📊 **Your Daily Recap**\n\n"
        recap_message += f"**Your Tracked Tokens:** {len(user_tokens)}\n"
        recap_message += f"**Your Price Threshold:** {user_data['global_threshold']}%\n"
        recap_message += f"**Alerts Status:** {'Enabled' if user_data['active'] else 'Disabled'}\n\n"
        recap_message += "**Your Recent Tokens:**\n"
        
        for i, token_address in enumerate(list(user_tokens)[:5], 1):
            threshold_config = self.user_manager.get_user_threshold(chat_id, token_address)
            threshold = threshold_config['value']
            direction = threshold_config.get('direction', 'both')
            
            direction_emoji = {
                'both': '📊',
                'positive': '📈',
                'negative': '📉'
            }.get(direction, '📊')
            
            # Get token name/symbol for display
            if self.tracker:
                try:
                    token_info = await self.tracker.get_token_info_with_timestamp(token_address)
                    token_display = f"${token_info['symbol']}"
                except:
                    # Fallback to shortened address if token info unavailable
                    token_display = f"{token_address[:8]}...{token_address[-8:]}"
            else:
                token_display = f"{token_address[:8]}...{token_address[-8:]}"
            
            recap_message += f"{i}. `{token_display}` {direction_emoji} ({threshold}%)\n"
        
        if len(user_tokens) > 5:
            recap_message += f"... and {len(user_tokens) - 5} more tokens\n"
        
        await query.edit_message_text(recap_message, parse_mode='Markdown', reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_reset_price_button(self, query, context):
        """Handle reset price button press"""
        if not await self._is_authorized_query(query):
            return
        
        chat_id = str(query.from_user.id)
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        if not user_tokens:
            await query.edit_message_text("You are not tracking any tokens.", reply_markup=self.get_main_menu_keyboard())
            return
        
        # Create buttons for each token to reset price
        keyboard = []
        for token_address in user_tokens[:10]:  # Limit to 10 tokens
            if self.tracker:
                try:
                    token_data = await self.tracker.get_token_info_with_timestamp(token_address)
                    token_display = f"${token_data['symbol']}"
                except:
                    token_display = f"{token_address[:8]}...{token_address[-8:]}"
            else:
                token_display = f"{token_address[:8]}...{token_address[-8:]}"
            keyboard.append([InlineKeyboardButton(f"🔄 {token_display}", callback_data=f"reset_price:{token_address}")])
        
        keyboard.append([InlineKeyboardButton("« Back", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔄 **Reset Price Reference**\n\n"
            "Select a token to reset its price reference to the current price. "
            "Future alerts will use this new price as the baseline.\n\n"
            "Select a token:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def _handle_reset_price_specific(self, query, context, token_address):
        """Handle resetting price reference for a specific token"""
        if not await self._is_authorized_query(query):
            return
        
        if not self.tracker:
            await query.edit_message_text("Tracker not available.", reply_markup=self.get_main_menu_keyboard())
            return
        
        chat_id = str(query.from_user.id)
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        if token_address not in user_tokens:
            await query.edit_message_text("You are not tracking this token.", reply_markup=self.get_main_menu_keyboard())
            return
        
        try:
            new_price = await self.tracker.reset_price_reference(chat_id, token_address)
            try:
                token_data = await self.tracker.get_token_info_with_timestamp(token_address)
                token_display = f"${token_data['symbol']}"
            except:
                token_display = f"{token_address[:8]}...{token_address[-8:]}"
            await query.edit_message_text(
                f"✅ **Price Reference Reset**\n\n"
                f"Token: {token_display}\n"
                f"New reference price: ${new_price:.8f}\n\n"
                f"Your future alerts will use this as the baseline price.",
                parse_mode='Markdown',
                reply_markup=self.get_main_menu_keyboard()
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Error resetting price reference: {str(e)}", reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_copy_address(self, query, context, token_address):
        """Handle copy address button press"""
        if not await self._is_authorized_query(query):
            return
        
        # Unfortunately, Telegram bots cannot directly copy to clipboard
        # But we can show the address in a way that's easy to copy
        await query.answer(
            text=f"Address copied! {token_address}",
            show_alert=True
        )

    async def _handle_help_button(self, query, context):
        """Handle help button press"""
        if not await self._is_authorized_query(query):
            return
        
        help_message = (
            "❓ **Help - Crypto Trading Bot**\n\n"
            "**Commands:**\n"
            "• `/start` - Initialize the bot and show menu\n"
            "• `/status` - Show your bot status and settings\n"
            "• `/tokens` - List your tracked tokens\n"
            "• `/add <address>` - Add a token to track\n"
            "• `/remove <address>` - Remove a token\n"
            "• `/get <name/symbol/address>` - Get token info\n"
            "• `/threshold <number>` - Set your global price threshold\n"
            "• `/setthreshold <address> <threshold> [direction]` - Set custom token threshold\n"
            "• `/reset <address>` - Reset price reference to current price\n"
            "• `/stop` - Stop receiving alerts\n\n"
            "**Buttons:**\n"
            "• 📊 **Status** - View your bot status\n"
            "• 🪙 **Tokens** - View your tracked tokens\n"
            "• ➕ **Add Token** - Instructions to add tokens\n"
            "• ➖ **Remove Token** - Select tokens to remove\n"
            "• 📈 **Get Token Info** - Instructions for token lookup\n"
            "• ⚙️ **Set Threshold** - Instructions to set price threshold\n"
            "• 🔄 **Reset Price** - Reset price reference for tokens\n"
            "• 📊 **Recap** - Summary of your tracked tokens\n"
            "• ❓ **Help** - This help message\n"
            "• ❌ **Stop Alerts** - Unsubscribe from notifications\n\n"
            "**Tips:**\n"
            "• Send a token address directly to track it\n"
            "• Send a number (1-100) to set price threshold\n"
            "• Send a token name/symbol to get info\n"
            "• Use custom thresholds for specific tokens\n"
            "• Set direction to 'positive', 'negative', or 'both'\n"
            "• Reset price reference to start fresh tracking\n"
            "• Each user has their own tracking list and settings\n\n"
            "**Examples:**\n"
            "• `6MQpbiTC2YcogidTmKqMLK82qvE9z5QEm7EP3AEDpump`\n"
            "• `15` (sets 15% threshold)\n"
            "• `MASK` or `catwifmask`"
        )
        
        await query.edit_message_text(help_message, parse_mode='Markdown', reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_show_token_info(self, query, context, token_address):
        """Handle showing token info for user's tracked token"""
        if not await self._is_authorized_query(query):
            return
        
        if not self.tracker:
            await query.edit_message_text("Tracker not available.", reply_markup=self.get_main_menu_keyboard())
            return
        
        chat_id = str(query.from_user.id)
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        if token_address not in user_tokens:
            await query.edit_message_text("You are not tracking this token.", reply_markup=self.get_main_menu_keyboard())
            return
        
        try:
            token_data = await self.tracker.get_token_info_with_timestamp(token_address)
            
            # Get user's tracking info
            threshold_config = self.user_manager.get_user_threshold(chat_id, token_address)
            entry_price = self.user_manager.get_entry_price(chat_id, token_address)
            
            # Format message with tracking status
            message = f"📊 **Token Information** (Tracking)\n\n"
            message += f"🏷️ **Name:** {token_data['name']}\n"
            message += f"🔤 **Symbol:** {token_data['symbol']}\n"
            message += f"🔗 **Address:** `{token_address}`\n"
            message += f"💰 **Current Price:** ${token_data['price']:.8f}\n"
            
            # Show P&L if entry price available
            if entry_price:
                price_change = ((token_data['price'] - entry_price) / entry_price) * 100
                emoji = "📈" if price_change > 0 else "📉"
                message += f"📊 **Entry Price:** ${entry_price:.8f}\n"
                message += f"📊 **Entry Performance:** {emoji} {price_change:+.2f}% since entry\n"
            
            message += f"📈 **Market Cap:** ${token_data.get('market_cap', 0):,.2f}\n"
            message += f"💧 **Liquidity:** ${token_data.get('liquidity', 0):,.2f}\n"
            message += f"📊 **24h Volume:** ${token_data.get('volume_24h', 0):,.2f}\n"
            
            # Price changes
            if token_data.get('price_change_24h') is not None:
                change_24h = token_data['price_change_24h']
                emoji = "📈" if change_24h > 0 else "📉"
                message += f"📊 **24h Change:** {emoji} {change_24h:+.2f}%\n"
            
            if token_data.get('price_change_1h') is not None:
                change_1h = token_data['price_change_1h']
                emoji = "📈" if change_1h > 0 else "📉"
                message += f"⏰ **1h Change:** {emoji} {change_1h:+.2f}%\n"
            
            message += f"\n🎯 **Your Alert Settings:**\n"
            message += f"📊 **Threshold:** {threshold_config['value']}% ({threshold_config['direction']})\n"
            message += f"🕐 **Updated:** {token_data['fetched_timestamp']}"
            
            # Create action buttons
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh:{token_address}"),
                    InlineKeyboardButton("🔄 Reset Price", callback_data=f"reset_price:{token_address}")
                ],
                [
                    InlineKeyboardButton("⚙️ Set Threshold", callback_data=f"set_threshold:{token_address}"),
                    InlineKeyboardButton("❌ Remove", callback_data=f"remove:{token_address}")
                ],
                [
                    InlineKeyboardButton("📋 Copy Address", callback_data=f"copy:{token_address}")
                ],
                [
                    InlineKeyboardButton("« Back", callback_data="get_token"),
                    InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=reply_markup)
            
        except Exception as e:
            await query.edit_message_text(f"❌ Error getting token info: {str(e)}", reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_set_threshold_specific(self, query, context, token_address):
        """Handle setting threshold for a specific token via button"""
        if not await self._is_authorized_query(query):
            return
        
        chat_id = str(query.from_user.id)
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        
        if token_address not in user_tokens:
            await query.edit_message_text("You are not tracking this token.", reply_markup=self.get_main_menu_keyboard())
            return
        
        try:
            token_data = await self.tracker.get_token_info_with_timestamp(token_address)
            token_display = f"{token_data['symbol']}"
        except:
            token_display = f"{token_address[:8]}...{token_address[-8:]}"
        
        current_threshold = self.user_manager.get_user_threshold(chat_id, token_address)
        
        await query.edit_message_text(
            f"⚙️ **Set Threshold for {token_display}**\n\n"
            f"Current threshold: {current_threshold['value']}% ({current_threshold['direction']})\n\n"
            f"To set a new threshold, use the command:\n"
            f"`/setthreshold {token_address} <threshold> [direction]`\n\n"
            f"Examples:\n"
            f"• `/setthreshold {token_address} 25` (25% both directions)\n"
            f"• `/setthreshold {token_address} 15 positive` (15% only up)\n"
            f"• `/setthreshold {token_address} 10 negative` (10% only down)",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data=f"show_token:{token_address}")]])
        )
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle plain text messages (token addresses, threshold values, etc.)"""
        if not await self._is_authorized(update):
            return
        
        text = update.message.text.strip()
        
        # Check if it looks like a Solana token address (base58, ~44 chars)
        if len(text) >= 32 and len(text) <= 44 and re.match(r'^[1-9A-HJ-NP-Za-km-z]+$', text):
            # Handle token address
            await self._handle_token_address(update, text)
        else:
            # Try to parse as threshold
            try:
                threshold = float(text)
                if 0 < threshold <= 100:
                    await self._handle_threshold_value(update, threshold)
                else:
                    await self._handle_unknown_message(update, text)
            except ValueError:
                # Try to handle as token name/symbol query
                await self._handle_token_query(update, text)
    
    async def _handle_token_address(self, update: Update, token_address: str):
        """Handle when user sends a token address"""
        if not self.tracker:
            await update.message.reply_text("Tracker not available.", reply_markup=self.get_main_menu_keyboard())
            return
        
        chat_id = str(update.effective_chat.id)
        
        # Check if already tracking
        user_tokens = self.user_manager.get_user_tokens(chat_id)
        if token_address in user_tokens:
            # Show token info instead of error
            try:
                token_data = await self.tracker.get_token_info_with_timestamp(token_address)
                
                # Get user's threshold for this token
                threshold_config = self.user_manager.get_user_threshold(chat_id, token_address)
                entry_price = self.user_manager.get_entry_price(chat_id, token_address)
                
                message = f"ℹ️ **Already Tracking This Token**\n\n"
                message += f"🏷️ **Name:** {token_data['name']}\n"
                message += f"🔤 **Symbol:** {token_data['symbol']}\n"
                message += f"💰 **Current Price:** ${token_data['price']:.8f}\n"
                if entry_price:
                    price_change = ((token_data['price'] - entry_price) / entry_price) * 100
                    emoji = "📈" if price_change > 0 else "📉"
                    message += f"📊 **Entry Price:** ${entry_price:.8f}\n"
                    message += f"📊 **Entry Performance:** {emoji} {price_change:+.2f}% since entry\n"
                message += f"📈 **Market Cap:** ${token_data.get('market_cap', 0):,.2f}\n"
                message += f"💧 **Liquidity:** ${token_data.get('liquidity', 0):,.2f}\n"
                message += f"🎯 **Your Threshold:** {threshold_config['value']}% ({threshold_config['direction']})\n"
                
                # Add action buttons
                keyboard = [
                    [
                        InlineKeyboardButton("🔄 Reset Price Reference", callback_data=f"reset_price:{token_address}"),
                        InlineKeyboardButton("⚙️ Set Threshold", callback_data=f"set_threshold:{token_address}")
                    ],
                    [
                        InlineKeyboardButton("❌ Remove Token", callback_data=f"remove:{token_address}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
                return
            except Exception as e:
                # Fallback to basic message if token info fails
                await update.message.reply_text(
                    f"⚠️ You are already tracking this token.\n\n"
                    f"Address: <code>{token_address}</code>",
                    parse_mode='HTML',
                    reply_markup=self.get_main_menu_keyboard()
                )
                return
        
        # Add token via tracker (handles entry price automatically)
        if self.tracker:
            await self.tracker.add_token(chat_id, token_address)
        else:
            # Fallback if tracker not available
            self.user_manager.add_token_to_user(chat_id, token_address)
        
        reply_markup = self.get_main_menu_keyboard()
        
        await update.message.reply_text(
            f"✅ Token added to your tracking list!\n\n"
            f"Use the buttons below for more actions:",
            reply_markup=reply_markup
        )
    
    async def _handle_threshold_value(self, update: Update, threshold: float):
        """Handle when user sends a threshold value"""
        chat_id = str(update.effective_chat.id)
        self.user_manager.set_user_global_threshold(chat_id, threshold)
        
        reply_markup = self.get_main_menu_keyboard()
        
        await update.message.reply_text(
            f"✅ Your price threshold updated to {threshold}%",
            reply_markup=reply_markup
        )
    
    async def _handle_token_query(self, update: Update, query: str):
        """Handle when user sends a token name/symbol for info"""
        if not self.tracker:
            await update.message.reply_text("Tracker not available.", reply_markup=self.get_main_menu_keyboard())
            return
        
        try:
            token_data = await self.tracker.get_token_info_with_timestamp(query)
            
            # Format message with inline keyboard
            keyboard = [
                [
                    InlineKeyboardButton("➕ Track This", callback_data=f"track:{token_data['address']}"),
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh:{token_data['address']}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Format message with only requested variables
            chat_id = str(update.effective_chat.id)
            message = f"📊 **Token Information**\n\n"
            message += f"🏷️ **Name:** {token_data['name']}\n"
            message += f"🔤 **Symbol:** {token_data['symbol']}\n"
            message += f"🔗 **Address:** `{token_data['address']}`\n"
            message += f"💰 **Current Price:** ${token_data['price']:.8f}\n"
            
            # Check if user is tracking this token and show entry performance
            user_tokens = self.user_manager.get_user_tokens(chat_id)
            if token_data['address'] in user_tokens:
                entry_price = self.user_manager.get_entry_price(chat_id, token_data['address'])
                if entry_price:
                    price_change = ((token_data['price'] - entry_price) / entry_price) * 100
                    emoji = "📈" if price_change > 0 else "📉"
                    message += f"📊 **Entry Price:** ${entry_price:.8f}\n"
                    message += f"📊 **Entry Performance:** {emoji} {price_change:+.2f}% since entry\n"
                message += f"🎯 **You're tracking this token**\n"
            
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
            
            # Add copy address button to existing keyboard
            keyboard = [
                [
                    InlineKeyboardButton("➕ Track This", callback_data=f"track:{token_data['address']}"),
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh:{token_data['address']}")
                ],
                [
                    InlineKeyboardButton("📋 Copy Address", callback_data=f"copy:{token_data['address']}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                message, 
                parse_mode='Markdown', 
                disable_web_page_preview=True,
                reply_markup=reply_markup
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Could not find token: {query}", reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_unknown_message(self, update: Update, text: str):
        """Handle unrecognized messages"""
        reply_markup = self.get_main_menu_keyboard()
        
        await update.message.reply_text(
            "I didn't understand that message. Use the buttons below or send:\n\n"
            "• A token address to track it\n"
            "• A number (1-100) to set price threshold\n"
            "• A token name/symbol to get info",
            reply_markup=reply_markup
        )
    
    async def _is_authorized_query(self, query) -> bool:
        chat_id = str(query.from_user.id)
        user_data = self.user_manager.get_user(chat_id)
        if not user_data or not user_data['active']:
            await query.edit_message_text("Please send /start first to use this bot.", reply_markup=self.get_main_menu_keyboard())
            return False
        return True
    
    async def _is_authorized(self, update: Update) -> bool:
        chat_id = str(update.effective_chat.id)
        user_data = self.user_manager.get_user(chat_id)
        if not user_data or not user_data['active']:
            await update.message.reply_text("Please send /start first to use this bot.", reply_markup=self.get_main_menu_keyboard())
            return False
        return True
    
    async def initialize(self):
        self.app = Application.builder().token(config.telegram_bot_token).build()
        
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("tokens", self.tokens_command))
        self.app.add_handler(CommandHandler("threshold", self.threshold_command))
        self.app.add_handler(CommandHandler("setthreshold", self.set_token_threshold_command))
        self.app.add_handler(CommandHandler("add", self.add_command))
        self.app.add_handler(CommandHandler("get", self.get_command))
        self.app.add_handler(CommandHandler("remove", self.remove_command))
        self.app.add_handler(CommandHandler("reset", self.reset_command))
        self.app.add_handler(CommandHandler("stop", self.stop_command))
        
        # Add callback query handler for inline buttons
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Add text message handler for non-command messages
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))
        
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
    
    async def shutdown(self):
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()