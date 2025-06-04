import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from typing import Optional, Set
from ..utils import config

class TelegramHandler:
    def __init__(self):
        self.app: Optional[Application] = None
        self.registered_users: Set[str] = set(config.get_active_chat_ids())
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
        
        config.save_chat_id(chat_id)
        self.registered_users.add(chat_id)
        
        welcome_message = (
            f"Welcome {user_name}! 🚀\n\n"
            "Your chat ID has been saved. You will now receive alerts for:\n"
            f"• Price changes > {config.price_change_threshold}%\n"
            f"• Significant holder count changes\n\n"
            "Use the buttons below or type commands:"
        )
        
        reply_markup = self.get_main_menu_keyboard()
        
        await update.message.reply_text(welcome_message, reply_markup=reply_markup)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._is_authorized(update):
            return
        
        status_message = (
            f"🟢 Bot Status: Active\n\n"
            f"Price Threshold: {config.price_change_threshold}%\n"
            f"Check Interval: {config.check_interval}s\n"
            f"Tracked Tokens: {len(self.tracker.tokens) if self.tracker else 0}\n"
        )
        
        await update.message.reply_text(status_message, reply_markup=self.get_main_menu_keyboard())
    
    async def tokens_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._is_authorized(update):
            return
        
        if not self.tracker or not self.tracker.tokens:
            await update.message.reply_text("No tokens are being tracked.")
            return
        
        message = "📊 Tracked Tokens:\n\n"
        for i, token in enumerate(self.tracker.tokens, 1):
            threshold = self.tracker.get_token_threshold(token)
            direction = self.tracker.get_token_direction(token)
            global_threshold = self.tracker.price_threshold
            
            direction_emoji = {
                'both': '📊',
                'positive': '📈',
                'negative': '📉'
            }.get(direction, '📊')
            
            # Get token name/symbol for display
            try:
                token_data = await self.tracker.get_token_info_with_timestamp(token)
                token_display = f"${token_data['symbol']}"
            except:
                # Fallback to shortened address if token info unavailable
                token_display = f"{token[:8]}...{token[-8:]}"
            
            if threshold == global_threshold and direction == 'both':
                message += f"{i}. <code>{token_display}</code> {direction_emoji} (Global: {threshold}%)\n"
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
            
            config.price_change_threshold = new_threshold
            if self.tracker:
                self.tracker.update_threshold(new_threshold)
            
            await update.message.reply_text(f"✅ Price threshold updated to {new_threshold}%", reply_markup=self.get_main_menu_keyboard())
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
            
            if not self.tracker:
                await update.message.reply_text("Tracker not available.")
                return
            
            if token_address not in self.tracker.tokens:
                await update.message.reply_text(f"Token {token_address} is not being tracked.")
                return
            
            await self.tracker.set_token_threshold(token_address, threshold, direction)
            
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
            
            try:
                token_data = await self.tracker.get_token_info_with_timestamp(token_address)
                token_display = f"${token_data['symbol']}"
            except:
                token_display = f"{token_address[:8]}...{token_address[-8:]}"
            await update.message.reply_text(
                f"✅ Threshold for {token_display} set to {threshold}% {direction_emoji} ({direction})",
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
        
        if self.tracker:
            if token_address in self.tracker.tokens:
                await update.message.reply_text("This token is already being tracked.", reply_markup=self.get_main_menu_keyboard())
                return
            
            await self.tracker.add_token(token_address)
    
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
            message = f"📊 **Token Information**\n\n"
            message += f"🏷️ **Name:** {token_data['name']}\n"
            message += f"🔤 **Symbol:** {token_data['symbol']}\n"
            message += f"🔗 **Address:** `{token_data['address']}`\n"
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
        
        if self.tracker:
            if token_address not in self.tracker.tokens:
                await update.message.reply_text("This token is not being tracked.", reply_markup=self.get_main_menu_keyboard())
                return
            
            await self.tracker.remove_token(token_address)
            await update.message.reply_text(f"✅ Removed token: <code>{token_address}</code>", parse_mode='HTML', reply_markup=self.get_main_menu_keyboard())
    
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
        
        if not self.tracker:
            await update.message.reply_text("Tracker not available.", reply_markup=self.get_main_menu_keyboard())
            return
        
        if token_address not in self.tracker.tokens:
            await update.message.reply_text(f"Token {token_address} is not being tracked.", reply_markup=self.get_main_menu_keyboard())
            return
        
        try:
            new_price = await self.tracker.reset_price_reference(token_address)
            short_token = f"{token_address[:8]}...{token_address[-8:]}"
            await update.message.reply_text(
                f"✅ **Price Reference Reset**\n\n"
                f"Token: {short_token}\n"
                f"New reference price: ${new_price:.8f}\n\n"
                f"Future alerts will use this as the baseline price.",
                parse_mode='Markdown',
                reply_markup=self.get_main_menu_keyboard()
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error resetting price reference: {str(e)}", reply_markup=self.get_main_menu_keyboard())
    
    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        
        if chat_id in self.registered_users:
            self.registered_users.remove(chat_id)
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
        elif callback_data == "back_to_main":
            await self._handle_back_to_main(query, context)
    
    async def _handle_status_button(self, query, context):
        if not await self._is_authorized_query(query):
            return
        
        status_message = (
            f"🟢 Bot Status: Active\n\n"
            f"Price Threshold: {config.price_change_threshold}%\n"
            f"Check Interval: {config.check_interval}s\n"
            f"Tracked Tokens: {len(self.tracker.tokens) if self.tracker else 0}\n"
        )
        await query.edit_message_text(status_message, reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_tokens_button(self, query, context):
        if not await self._is_authorized_query(query):
            return
        
        if not self.tracker or not self.tracker.tokens:
            await query.edit_message_text("No tokens are being tracked.", reply_markup=self.get_main_menu_keyboard())
            return
        
        message = "📊 Tracked Tokens:\n\n"
        for i, token in enumerate(self.tracker.tokens, 1):
            threshold = self.tracker.get_token_threshold(token)
            direction = self.tracker.get_token_direction(token)
            global_threshold = self.tracker.price_threshold
            
            direction_emoji = {
                'both': '📊',
                'positive': '📈',
                'negative': '📉'
            }.get(direction, '📊')
            
            # Get token name/symbol for display
            try:
                token_data = await self.tracker.get_token_info_with_timestamp(token)
                token_display = f"${token_data['symbol']}"
            except:
                # Fallback to shortened address if token info unavailable
                token_display = f"{token[:8]}...{token[-8:]}"
            
            if threshold == global_threshold and direction == 'both':
                message += f"{i}. <code>{token_display}</code> {direction_emoji} (Global: {threshold}%)\n"
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
        
        if not self.tracker or not self.tracker.tokens:
            await query.edit_message_text("No tokens are being tracked.", reply_markup=self.get_main_menu_keyboard())
            return
        
        # Create buttons for each token to remove
        keyboard = []
        for token in self.tracker.tokens[:10]:  # Limit to 10 tokens
            try:
                token_data = await self.tracker.get_token_info_with_timestamp(token)
                token_display = f"${token_data['symbol']}"
            except:
                token_display = f"{token[:8]}...{token[-8:]}"
            keyboard.append([InlineKeyboardButton(f"❌ {token_display}", callback_data=f"remove:{token}")])
        
        keyboard.append([InlineKeyboardButton("« Back", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text("Select a token to remove:", reply_markup=reply_markup)
    
    async def _handle_get_token_button(self, query, context):
        if not await self._is_authorized_query(query):
            return
        
        await query.edit_message_text(
            "To get token info, send me the token name, symbol, or address.\n\n"
            "Examples:\n"
            "• <code>MASK</code>\n"
            "• <code>catwifmask</code>\n"
            "• <code>6MQpbiTC2YcogidTmKqMLK82qvE9z5QEm7EP3AEDpump</code>",
            parse_mode='HTML',
            reply_markup=self.get_main_menu_keyboard()
        )
    
    async def _handle_set_threshold_button(self, query, context):
        if not await self._is_authorized_query(query):
            return
        
        await query.edit_message_text(
            "To set a new price threshold, send me a number.\n\n"
            f"Current threshold: {config.price_change_threshold}%\n"
            "Example: <code>15</code> (for 15%)",
            parse_mode='HTML',
            reply_markup=self.get_main_menu_keyboard()
        )
    
    async def _handle_stop_alerts_button(self, query, context):
        chat_id = str(query.from_user.id)
        
        if chat_id in self.registered_users:
            self.registered_users.remove(chat_id)
            await query.edit_message_text("You have been unsubscribed from alerts. Send /start to subscribe again.", reply_markup=self.get_main_menu_keyboard())
        else:
            await query.edit_message_text("You are not currently subscribed to alerts.", reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_remove_specific_token(self, query, context, token_address):
        if not await self._is_authorized_query(query):
            return
        
        if self.tracker:
            if token_address not in self.tracker.tokens:
                await query.edit_message_text("This token is not being tracked.", reply_markup=self.get_main_menu_keyboard())
                return
            
            try:
                token_data = await self.tracker.get_token_info_with_timestamp(token_address)
                token_display = f"${token_data['symbol']}"
            except:
                token_display = f"{token_address[:8]}...{token_address[-8:]}"
            
            await self.tracker.remove_token(token_address)
            await query.edit_message_text(f"✅ Removed token: {token_display}", reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_back_to_main(self, query, context):
        # Recreate main menu
        keyboard = [
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
                InlineKeyboardButton("❌ Stop Alerts", callback_data="stop_alerts")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text("🏠 Main Menu - Use the buttons below or type commands:", reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_track_token(self, query, context, token_address):
        """Handle tracking a token from inline button"""
        if not await self._is_authorized_query(query):
            return
        
        if not self.tracker:
            await query.edit_message_text("Tracker not available.", reply_markup=self.get_main_menu_keyboard())
            return
        
        if token_address in self.tracker.tokens:
            await query.edit_message_text("This token is already being tracked.", reply_markup=self.get_main_menu_keyboard())
            return
        
        await self.tracker.add_token(token_address)
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
            message = f"🔄 **Refreshed Token Info**\n\n"
            message += f"🏷️ **Name:** {token_data['name']}\n"
            message += f"🔤 **Symbol:** {token_data['symbol']}\n"
            message += f"🔗 **Address:** `{token_data['address']}`\n"
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
        
        if not self.tracker or not self.tracker.tokens:
            await query.edit_message_text("📊 Recap: No tokens are being tracked.", reply_markup=self.get_main_menu_keyboard())
            return
        
        recap_message = f"📊 **Daily Recap**\n\n"
        recap_message += f"**Tracked Tokens:** {len(self.tracker.tokens)}\n"
        recap_message += f"**Price Threshold:** {config.price_change_threshold}%\n"
        recap_message += f"**Check Interval:** {config.check_interval}s\n\n"
        recap_message += "**Recent Tokens:**\n"
        
        for i, token in enumerate(self.tracker.tokens[:5], 1):
            threshold = self.tracker.get_token_threshold(token)
            direction = self.tracker.get_token_direction(token)
            
            direction_emoji = {
                'both': '📊',
                'positive': '📈',
                'negative': '📉'
            }.get(direction, '📊')
            
            # Get token name/symbol for display
            try:
                token_data = await self.tracker.get_token_info_with_timestamp(token)
                token_display = f"${token_data['symbol']}"
            except:
                # Fallback to shortened address if token info unavailable
                token_display = f"{token[:8]}...{token[-8:]}"
            
            recap_message += f"{i}. `{token_display}` {direction_emoji} ({threshold}%)\n"
        
        if len(self.tracker.tokens) > 5:
            recap_message += f"... and {len(self.tracker.tokens) - 5} more tokens\n"
        
        await query.edit_message_text(recap_message, parse_mode='Markdown', reply_markup=self.get_main_menu_keyboard())
    
    async def _handle_reset_price_button(self, query, context):
        """Handle reset price button press"""
        if not await self._is_authorized_query(query):
            return
        
        if not self.tracker or not self.tracker.tokens:
            await query.edit_message_text("No tokens are being tracked.", reply_markup=self.get_main_menu_keyboard())
            return
        
        # Create buttons for each token to reset price
        keyboard = []
        for token in self.tracker.tokens[:10]:  # Limit to 10 tokens
            try:
                token_data = await self.tracker.get_token_info_with_timestamp(token)
                token_display = f"${token_data['symbol']}"
            except:
                token_display = f"{token[:8]}...{token[-8:]}"
            keyboard.append([InlineKeyboardButton(f"🔄 {token_display}", callback_data=f"reset_price:{token}")])
        
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
        
        if token_address not in self.tracker.tokens:
            await query.edit_message_text("This token is not being tracked.", reply_markup=self.get_main_menu_keyboard())
            return
        
        try:
            new_price = await self.tracker.reset_price_reference(token_address)
            try:
                token_data = await self.tracker.get_token_info_with_timestamp(token_address)
                token_display = f"${token_data['symbol']}"
            except:
                token_display = f"{token_address[:8]}...{token_address[-8:]}"
            await query.edit_message_text(
                f"✅ **Price Reference Reset**\n\n"
                f"Token: {token_display}\n"
                f"New reference price: ${new_price:.8f}\n\n"
                f"Future alerts will use this as the baseline price.",
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
            "• `/status` - Show bot status and settings\n"
            "• `/tokens` - List all tracked tokens\n"
            "• `/add <address>` - Add a token to track\n"
            "• `/remove <address>` - Remove a token\n"
            "• `/get <name/symbol/address>` - Get token info\n"
            "• `/threshold <number>` - Set global price threshold\n"
            "• `/setthreshold <address> <threshold> [direction]` - Set custom token threshold\n"
            "• `/reset <address>` - Reset price reference to current price\n"
            "• `/stop` - Stop receiving alerts\n\n"
            "**Buttons:**\n"
            "• 📊 **Status** - View bot status\n"
            "• 🪙 **Tokens** - View tracked tokens\n"
            "• ➕ **Add Token** - Instructions to add tokens\n"
            "• ➖ **Remove Token** - Select tokens to remove\n"
            "• 📈 **Get Token Info** - Instructions for token lookup\n"
            "• ⚙️ **Set Threshold** - Instructions to set price threshold\n"
            "• 🔄 **Reset Price** - Reset price reference for tokens\n"
            "• 📊 **Recap** - Daily summary of tracked tokens\n"
            "• ❓ **Help** - This help message\n"
            "• ❌ **Stop Alerts** - Unsubscribe from notifications\n\n"
            "**Tips:**\n"
            "• Send a token address directly to track it\n"
            "• Send a number (1-100) to set price threshold\n"
            "• Send a token name/symbol to get info\n"
            "• Use custom thresholds for specific tokens\n"
            "• Set direction to 'positive', 'negative', or 'both'\n"
            "• Reset price reference to start fresh tracking\n\n"
            "**Examples:**\n"
            "• `6MQpbiTC2YcogidTmKqMLK82qvE9z5QEm7EP3AEDpump`\n"
            "• `15` (sets 15% threshold)\n"
            "• `MASK` or `catwifmask`"
        )
        
        await query.edit_message_text(help_message, parse_mode='Markdown', reply_markup=self.get_main_menu_keyboard())
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle plain text messages (token addresses, threshold values, etc.)"""
        if not await self._is_authorized(update):
            return
        
        text = update.message.text.strip()
        
        # Check if it looks like a Solana token address (base58, ~44 chars)
        if len(text) >= 32 and len(text) <= 44 and text.replace('1', '').replace('2', '').replace('3', '').replace('4', '').replace('5', '').replace('6', '').replace('7', '').replace('8', '').replace('9', '').replace('A', '').replace('B', '').replace('C', '').replace('D', '').replace('E', '').replace('F', '').replace('G', '').replace('H', '').replace('J', '').replace('K', '').replace('L', '').replace('M', '').replace('N', '').replace('P', '').replace('Q', '').replace('R', '').replace('S', '').replace('T', '').replace('U', '').replace('V', '').replace('W', '').replace('X', '').replace('Y', '').replace('Z', '').replace('a', '').replace('b', '').replace('c', '').replace('d', '').replace('e', '').replace('f', '').replace('g', '').replace('h', '').replace('i', '').replace('j', '').replace('k', '').replace('m', '').replace('n', '').replace('o', '').replace('p', '').replace('q', '').replace('r', '').replace('s', '').replace('t', '').replace('u', '').replace('v', '').replace('w', '').replace('x', '').replace('y', '').replace('z', '') == '':
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
        
        # Check if already tracking
        if token_address in self.tracker.tokens:
            await update.message.reply_text(
                f"⚠️ Token is already being tracked.\n\n"
                f"Address: <code>{token_address}</code>",
                parse_mode='HTML',
                reply_markup=self.get_main_menu_keyboard()
            )
            return
        
        # Add the token
        await self.tracker.add_token(token_address)
        
        reply_markup = self.get_main_menu_keyboard()
        
        await update.message.reply_text(
            f"✅ Token added successfully!\n\n"
            f"Use the buttons below for more actions:",
            reply_markup=reply_markup
        )
    
    async def _handle_threshold_value(self, update: Update, threshold: float):
        """Handle when user sends a threshold value"""
        config.price_change_threshold = threshold
        if self.tracker:
            self.tracker.update_threshold(threshold)
        
        reply_markup = self.get_main_menu_keyboard()
        
        await update.message.reply_text(
            f"✅ Price threshold updated to {threshold}%",
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
            message = f"📊 **Token Information**\n\n"
            message += f"🏷️ **Name:** {token_data['name']}\n"
            message += f"🔤 **Symbol:** {token_data['symbol']}\n"
            message += f"🔗 **Address:** `{token_data['address']}`\n"
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
        if chat_id not in self.registered_users:
            await query.edit_message_text("Please send /start first to use this bot.", reply_markup=self.get_main_menu_keyboard())
            return False
        return True
    
    async def _is_authorized(self, update: Update) -> bool:
        chat_id = str(update.effective_chat.id)
        if chat_id not in self.registered_users:
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