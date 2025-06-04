from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import aiohttp
import asyncio
from datetime import datetime

class APIError(Exception):
    pass

class RateLimitError(APIError):
    pass

class BaseAPI(ABC):
    def __init__(self, base_url: str, rate_limit: float = 1.0):
        self.base_url = base_url
        self.rate_limit = rate_limit
        self.last_request_time = 0
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def _rate_limit_check(self):
        current_time = asyncio.get_event_loop().time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.rate_limit:
            await asyncio.sleep(self.rate_limit - time_since_last_request)
        self.last_request_time = asyncio.get_event_loop().time()
    
    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        await self._rate_limit_check()
        
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        url = f"{self.base_url}{endpoint}"
        
        try:
            async with self.session.request(method, url, **kwargs) as response:
                if response.status == 429:
                    raise RateLimitError("Rate limit exceeded")
                
                response.raise_for_status()
                return await response.json()
        
        except aiohttp.ClientError as e:
            raise APIError(f"API request failed: {str(e)}")
    
    @abstractmethod
    async def get_token_price(self, token_address: str) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    async def get_token_info(self, token_address: str) -> Dict[str, Any]:
        pass