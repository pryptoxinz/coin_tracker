import os
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import aiofiles
import asyncio
from pathlib import Path

class CSVStorage:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
    
    def _get_file_path(self, token_address: str, data_type: str = "prices") -> Path:
        safe_address = token_address.replace("/", "_")
        return self.data_dir / f"{safe_address}_{data_type}.csv"
    
    async def save_price_data(self, token_address: str, price_data: Dict[str, Any]):
        async with self._lock:
            file_path = self._get_file_path(token_address, "prices")
            
            data = {
                'timestamp': datetime.now().isoformat(),
                'price': price_data.get('price', 0),
                'address': token_address
            }
            
            df = pd.DataFrame([data])
            
            if file_path.exists():
                existing_df = pd.read_csv(file_path)
                df = pd.concat([existing_df, df], ignore_index=True)
            
            df.to_csv(file_path, index=False)
    
    async def save_holder_data(self, token_address: str, holder_count: int):
        async with self._lock:
            file_path = self._get_file_path(token_address, "holders")
            
            data = {
                'timestamp': datetime.now().isoformat(),
                'holder_count': holder_count,
                'address': token_address
            }
            
            df = pd.DataFrame([data])
            
            if file_path.exists():
                existing_df = pd.read_csv(file_path)
                df = pd.concat([existing_df, df], ignore_index=True)
            
            df.to_csv(file_path, index=False)
    
    async def get_latest_price(self, token_address: str) -> Optional[Dict[str, Any]]:
        file_path = self._get_file_path(token_address, "prices")
        
        if not file_path.exists():
            return None
        
        df = pd.read_csv(file_path)
        if df.empty:
            return None
        
        latest = df.iloc[-1]
        return {
            'timestamp': latest['timestamp'],
            'price': float(latest['price']),
            'address': latest['address']
        }
    
    async def get_price_history(self, token_address: str, limit: int = 100) -> List[Dict[str, Any]]:
        file_path = self._get_file_path(token_address, "prices")
        
        if not file_path.exists():
            return []
        
        df = pd.read_csv(file_path)
        df = df.tail(limit)
        
        return df.to_dict('records')
    
    async def get_holder_history(self, token_address: str, limit: int = 100) -> List[Dict[str, Any]]:
        file_path = self._get_file_path(token_address, "holders")
        
        if not file_path.exists():
            return []
        
        df = pd.read_csv(file_path)
        df = df.tail(limit)
        
        return df.to_dict('records')
    
    async def save_alert_log(self, alert_data: Dict[str, Any]):
        async with self._lock:
            file_path = self.data_dir / "alerts_log.csv"
            
            data = {
                'timestamp': datetime.now().isoformat(),
                'token_address': alert_data.get('token_address'),
                'alert_type': alert_data.get('alert_type'),
                'old_value': alert_data.get('old_value'),
                'new_value': alert_data.get('new_value'),
                'change_percent': alert_data.get('change_percent'),
                'message': alert_data.get('message', '')
            }
            
            df = pd.DataFrame([data])
            
            if file_path.exists():
                existing_df = pd.read_csv(file_path)
                df = pd.concat([existing_df, df], ignore_index=True)
            
            df.to_csv(file_path, index=False)
    
    async def save_tracked_tokens(self, tokens: List[str], token_thresholds: Dict[str, Dict] = None):
        """Save the list of tracked tokens to a file with optional thresholds and directions"""
        async with self._lock:
            file_path = self.data_dir / "tracked_tokens.csv"
            token_thresholds = token_thresholds or {}
            
            data = []
            for token in tokens:
                threshold_config = token_thresholds.get(token, {})
                data.append({
                    'token_address': token,
                    'added_timestamp': datetime.now().isoformat(),
                    'threshold': threshold_config.get('value', 0.0),  # 0.0 means use global threshold
                    'direction': threshold_config.get('direction', 'both')  # both, positive, negative
                })
            
            df = pd.DataFrame(data)
            df.to_csv(file_path, index=False)
    
    async def load_tracked_tokens(self) -> Tuple[List[str], Dict[str, Dict]]:
        """Load the list of tracked tokens from file with their thresholds and directions"""
        file_path = self.data_dir / "tracked_tokens.csv"
        
        if not file_path.exists():
            return [], {}
        
        try:
            df = pd.read_csv(file_path)
            if df.empty:
                return [], {}
            
            tokens = df['token_address'].tolist()
            thresholds = {}
            
            # Load thresholds and directions if columns exist
            if 'threshold' in df.columns:
                for _, row in df.iterrows():
                    token = row['token_address']
                    threshold = row.get('threshold', 0.0)
                    direction = row.get('direction', 'both')
                    
                    if threshold > 0:  # Only store non-zero thresholds
                        thresholds[token] = {
                            'value': threshold,
                            'direction': direction
                        }
                        
            return tokens, thresholds
        except Exception:
            return [], {}
    
    async def add_tracked_token(self, token_address: str, threshold: float = 0.0, direction: str = 'both'):
        """Add a single token to the tracked list with optional threshold and direction"""
        current_tokens, current_thresholds = await self.load_tracked_tokens()
        if token_address not in current_tokens:
            current_tokens.append(token_address)
            if threshold > 0:
                current_thresholds[token_address] = {'value': threshold, 'direction': direction}
            await self.save_tracked_tokens(current_tokens, current_thresholds)
    
    async def remove_tracked_token(self, token_address: str):
        """Remove a single token from the tracked list"""
        current_tokens, current_thresholds = await self.load_tracked_tokens()
        if token_address in current_tokens:
            current_tokens.remove(token_address)
            current_thresholds.pop(token_address, None)
            await self.save_tracked_tokens(current_tokens, current_thresholds)
    
    async def set_token_threshold(self, token_address: str, threshold: float, direction: str = 'both'):
        """Set a specific threshold and direction for a token"""
        current_tokens, current_thresholds = await self.load_tracked_tokens()
        if token_address in current_tokens:
            if threshold > 0:
                current_thresholds[token_address] = {'value': threshold, 'direction': direction}
            else:
                current_thresholds.pop(token_address, None)
            await self.save_tracked_tokens(current_tokens, current_thresholds)
    
    async def get_token_threshold(self, token_address: str) -> Optional[Dict]:
        """Get the specific threshold and direction for a token"""
        _, thresholds = await self.load_tracked_tokens()
        return thresholds.get(token_address)