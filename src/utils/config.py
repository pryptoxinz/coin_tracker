import os
import json
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from dataclasses import dataclass
from pathlib import Path

load_dotenv()

@dataclass
class Config:
    telegram_bot_token: str
    telegram_chat_id: Optional[str]
    price_change_threshold: float
    check_interval: int
    solana_rpc_url: str
    data_dir: str
    config_dir: str
    
    @classmethod
    def from_env(cls) -> 'Config':
        base_dir = Path(__file__).parent.parent.parent
        return cls(
            telegram_bot_token=os.getenv('TELEGRAM_BOT_TOKEN', ''),
            telegram_chat_id=os.getenv('TELEGRAM_CHAT_ID', None),
            price_change_threshold=float(os.getenv('PRICE_CHANGE_THRESHOLD', '20')),
            check_interval=int(os.getenv('CHECK_INTERVAL', '60')),
            solana_rpc_url=os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com'),
            data_dir=str(base_dir / 'data'),
            config_dir=str(base_dir / 'config')
        )
    
    def validate(self) -> bool:
        if not self.telegram_bot_token:
            raise ValueError("Telegram bot token is required")
        return True
    
    def save_chat_id(self, chat_id: str):
        Path(self.config_dir).mkdir(parents=True, exist_ok=True)
        chat_ids_file = Path(self.config_dir) / 'chat_ids.json'
        
        chat_ids = {}
        if chat_ids_file.exists():
            with open(chat_ids_file, 'r') as f:
                chat_ids = json.load(f)
        
        chat_ids[chat_id] = {
            'active': True,
            'registered_at': os.popen('date').read().strip()
        }
        
        with open(chat_ids_file, 'w') as f:
            json.dump(chat_ids, f, indent=2)
        
        self.telegram_chat_id = chat_id
    
    def get_active_chat_ids(self) -> List[str]:
        chat_ids_file = Path(self.config_dir) / 'chat_ids.json'
        
        if not chat_ids_file.exists():
            return []
        
        with open(chat_ids_file, 'r') as f:
            chat_ids = json.load(f)
        
        return [chat_id for chat_id, info in chat_ids.items() if info.get('active', True)]

config = Config.from_env()