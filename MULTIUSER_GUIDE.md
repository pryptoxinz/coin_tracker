# Multi-User Crypto Bot Guide 🚀

Your crypto bot now supports multiple users with individual tracking and alert preferences!

## 🌟 Key Features Implemented

### ✅ Individual User Management
- Each user has their own account with unique settings
- Users can only see and manage their own tracked tokens
- Data is completely isolated between users

### ✅ Per-User Token Tracking
- Multiple users can track the same token (like "kitty") simultaneously
- Each user has their own **entry price** for each token
- Price alerts are calculated from each user's individual entry price

### ✅ Customizable Thresholds
- **Global Threshold**: Each user can set their own default alert threshold
- **Per-Token Threshold**: Users can set specific thresholds for individual tokens
- **Directional Alerts**: Choose to get alerts for:
  - `both` - Price increases OR decreases
  - `positive` - Only price increases
  - `negative` - Only price decreases

### ✅ Smart Alert System
- Users only receive alerts for tokens they're tracking
- Alerts include both current change and total change from entry price
- Each user's alerts respect their individual threshold settings

## 🎯 Usage Examples

### Scenario: You and Your Friend Track "Kitty" Token

**You:**
- Add kitty token when price is $0.0005 (your entry price)
- Set your global threshold to 15%
- Set kitty-specific threshold to 10% (both directions)

**Your Friend:**
- Adds same kitty token when price is $0.0008 (their entry price)
- Sets their global threshold to 25%
- Sets kitty-specific threshold to 30% (positive only)

**Result:**
- When kitty price moves, you each get alerts based on YOUR entry price and YOUR thresholds
- You might get an alert at 10% change while your friend won't get one until 30%
- Your friend only gets alerts for price increases, you get alerts for both

## 📱 Available Commands

### Basic Commands
- `/start` - Register and activate your account
- `/status` - View your personal bot status and settings
- `/tokens` - List YOUR tracked tokens with thresholds

### Token Management
- `/add <token_address>` - Add token to YOUR tracking list
- `/remove <token_address>` - Remove token from YOUR tracking list
- `/get <token_name>` - Get current token information

### Threshold Settings
- `/threshold <value>` - Set YOUR global threshold (e.g., `/threshold 20`)
- `/setthreshold <token> <value> [direction]` - Set token-specific threshold
  - Example: `/setthreshold 6MQp...pump 15 positive`

### Price Management
- `/reset <token_address>` - Reset YOUR price reference for a token

## 🛠️ Button Interface

The bot provides an intuitive button interface:
- 📊 **Status** - Your personal status
- 🪙 **Tokens** - Your tracked tokens
- ➕ **Add Token** - Add new token
- ➖ **Remove Token** - Remove your tokens
- ⚙️ **Set Threshold** - Adjust your settings

## 💾 Data Structure

Each user's data is stored with:
```json
{
  "user_id": {
    "active": true,
    "tracked_tokens": ["token1", "token2"],
    "global_threshold": 20.0,
    "token_thresholds": {
      "token1": {"value": 15.0, "direction": "both"}
    },
    "entry_prices": {
      "token1": {"price": 0.001, "timestamp": "2025-06-04T..."}
    }
  }
}
```

## 🔧 Technical Implementation

### Architecture Changes
1. **UserManager**: New class handling all user-specific data
2. **Per-User Tracking**: TokenTracker now supports multiple users per token
3. **User-Specific Alerts**: Notifications sent only to relevant users
4. **Data Migration**: Existing users automatically migrated to new system

### Key Files Modified
- `src/storage/user_manager.py` - User management system
- `src/tracker/token_tracker.py` - Multi-user tracking logic
- `src/bot/telegram_handler.py` - User-specific commands
- `src/bot/telegram_notifier.py` - Individual user notifications
- `main.py` - Integration and initialization

## 🧪 Testing

Run the test suite to verify functionality:
```bash
./venv/bin/python test_multiuser.py
```

## 🎉 Benefits

1. **No Conflicts**: You and your friend can have completely different settings
2. **Individual Entry Prices**: Track your actual purchase price for accurate P/L
3. **Personalized Alerts**: Get alerts when YOU want them, not when others do
4. **Efficient Resource Usage**: Bot only tracks tokens that at least one user wants
5. **Privacy**: Users can't see each other's tokens or settings

## 💡 Pro Tips

- Set conservative global thresholds and aggressive per-token thresholds for important tokens
- Use directional thresholds (`positive` only) for tokens you're bullish on
- Reset price references after major news events for fresh alert baselines
- Use the `/get` command to check token info before adding to tracking

Your crypto bot is now ready for multi-user operation! 🚀