import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class UserManager:
    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self.users_file = os.path.join(config_dir, "chat_ids.json")
        self.users = {}
        self._load_users()
        self._migrate_if_needed()
    
    def _load_users(self):
        """Load users from chat_ids.json"""
        if os.path.exists(self.users_file):
            try:
                with open(self.users_file, 'r') as f:
                    self.users = json.load(f)
            except Exception as e:
                logger.error(f"Error loading users: {e}")
                self.users = {}
    
    def _save_users(self):
        """Save users to chat_ids.json"""
        try:
            with open(self.users_file, 'w') as f:
                json.dump(self.users, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving users: {e}")
    
    def _migrate_if_needed(self):
        """Migrate old format to new format if needed"""
        migration_needed = False
        
        for user_id, user_data in self.users.items():
            if isinstance(user_data, dict):
                # Check if it's the old format
                if 'tracked_tokens' not in user_data:
                    migration_needed = True
                    # Migrate to new format
                    self.users[user_id] = {
                        'active': user_data.get('active', True),
                        'registered_at': user_data.get('registered_at', datetime.now().strftime("%a %b %d %I:%M:%S %p %Z %Y")),
                        'tracked_tokens': [],
                        'global_threshold': 20.0,  # Default threshold
                        'token_thresholds': {},
                        'entry_prices': {}  # Store entry prices for tokens
                    }
        
        if migration_needed:
            logger.info("Migrated user data to new format")
            self._save_users()
    
    def register_user(self, user_id: str) -> bool:
        """Register a new user or reactivate existing user"""
        if user_id not in self.users:
            self.users[user_id] = {
                'active': True,
                'registered_at': datetime.now().strftime("%a %b %d %I:%M:%S %p %Z %Y"),
                'tracked_tokens': [],
                'global_threshold': 20.0,
                'token_thresholds': {},
                'entry_prices': {}
            }
            logger.info(f"Registered new user: {user_id}")
        else:
            self.users[user_id]['active'] = True
            logger.info(f"Reactivated user: {user_id}")
        
        self._save_users()
        return True
    
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user data"""
        return self.users.get(user_id)
    
    def is_user_active(self, user_id: str) -> bool:
        """Check if user is active"""
        user = self.get_user(user_id)
        return user is not None and user.get('active', False)
    
    def get_active_users(self) -> List[str]:
        """Get list of active user IDs"""
        return [user_id for user_id, data in self.users.items() 
                if data.get('active', False)]
    
    def add_token_to_user(self, user_id: str, token_address: str, entry_price: float = None) -> bool:
        """Add a token to user's tracking list"""
        if user_id not in self.users:
            return False
        
        if token_address not in self.users[user_id]['tracked_tokens']:
            self.users[user_id]['tracked_tokens'].append(token_address)
            
            # Store entry price if provided
            if entry_price is not None:
                self.users[user_id]['entry_prices'][token_address] = {
                    'price': entry_price,
                    'timestamp': datetime.now().isoformat()
                }
            
            self._save_users()
            return True
        return False
    
    def remove_token_from_user(self, user_id: str, token_address: str) -> bool:
        """Remove a token from user's tracking list"""
        if user_id not in self.users:
            return False
        
        if token_address in self.users[user_id]['tracked_tokens']:
            self.users[user_id]['tracked_tokens'].remove(token_address)
            
            # Remove entry price if exists
            if token_address in self.users[user_id]['entry_prices']:
                del self.users[user_id]['entry_prices'][token_address]
            
            # Remove token threshold if exists
            if token_address in self.users[user_id]['token_thresholds']:
                del self.users[user_id]['token_thresholds'][token_address]
            
            self._save_users()
            return True
        return False
    
    def get_user_tokens(self, user_id: str) -> List[str]:
        """Get list of tokens tracked by user"""
        user = self.get_user(user_id)
        return user.get('tracked_tokens', []) if user else []
    
    def set_user_global_threshold(self, user_id: str, threshold: float) -> bool:
        """Set user's global threshold"""
        if user_id not in self.users:
            return False
        
        self.users[user_id]['global_threshold'] = threshold
        self._save_users()
        return True
    
    def set_user_token_threshold(self, user_id: str, token_address: str, 
                                threshold: float, direction: str = 'both') -> bool:
        """Set user's threshold for a specific token"""
        if user_id not in self.users:
            return False
        
        if token_address not in self.users[user_id]['tracked_tokens']:
            return False
        
        self.users[user_id]['token_thresholds'][token_address] = {
            'value': threshold,
            'direction': direction
        }
        self._save_users()
        return True
    
    def get_user_threshold(self, user_id: str, token_address: str = None) -> Dict[str, Any]:
        """Get user's threshold for a token (or global if token not specified)"""
        user = self.get_user(user_id)
        if not user:
            return {'value': 20.0, 'direction': 'both'}
        
        if token_address and token_address in user.get('token_thresholds', {}):
            return user['token_thresholds'][token_address]
        
        return {
            'value': user.get('global_threshold', 20.0),
            'direction': 'both'
        }
    
    def get_users_tracking_token(self, token_address: str) -> List[str]:
        """Get list of users tracking a specific token"""
        users = []
        for user_id, data in self.users.items():
            if data.get('active', False) and token_address in data.get('tracked_tokens', []):
                users.append(user_id)
        return users
    
    def get_entry_price(self, user_id: str, token_address: str) -> Optional[float]:
        """Get user's entry price for a token"""
        user = self.get_user(user_id)
        if user and token_address in user.get('entry_prices', {}):
            return user['entry_prices'][token_address]['price']
        return None
    
    def set_entry_price(self, user_id: str, token_address: str, price: float) -> bool:
        """Set entry price for a token (used for backfilling)"""
        if user_id not in self.users:
            return False
        
        if token_address not in self.users[user_id]['tracked_tokens']:
            return False
        
        self.users[user_id]['entry_prices'][token_address] = {
            'price': price,
            'timestamp': datetime.now().isoformat()
        }
        self._save_users()
        return True
    
    def get_all_tracked_tokens(self) -> set:
        """Get set of all tokens being tracked by any active user"""
        all_tokens = set()
        for user_id, data in self.users.items():
            if data.get('active', False):
                all_tokens.update(data.get('tracked_tokens', []))
        return all_tokens
    
    def deactivate_user(self, user_id: str) -> bool:
        """Deactivate a user (stop receiving alerts)"""
        if user_id not in self.users:
            return False
        
        self.users[user_id]['active'] = False
        self._save_users()
        logger.info(f"Deactivated user: {user_id}")
        return True
    
    def set_entry_price(self, user_id: str, token_address: str, price: float) -> bool:
        """Set entry price for a token (used for backfilling missing entry prices)"""
        if user_id not in self.users:
            return False
        
        if 'entry_prices' not in self.users[user_id]:
            self.users[user_id]['entry_prices'] = {}
        
        self.users[user_id]['entry_prices'][token_address] = {
            'price': price,
            'timestamp': datetime.now().isoformat()
        }
        self._save_users()
        logger.info(f"Set entry price for user {user_id}, token {token_address}: ${price:.8f}")
        return True