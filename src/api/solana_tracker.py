from typing import Dict, Any, Optional
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from .base import BaseAPI, APIError
import base64
import struct
import aiohttp
import logging

logger = logging.getLogger(__name__)

class SolanaTracker(BaseAPI):
    def __init__(self, rpc_url: str):
        super().__init__(rpc_url, rate_limit=0.1)
        self.client = AsyncClient(rpc_url)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.close()
    
    async def get_token_supply(self, token_address: str) -> Dict[str, Any]:
        try:
            mint_pubkey = Pubkey.from_string(token_address)
            response = await self.client.get_token_supply(mint_pubkey)
            
            if response['result'] is None:
                raise APIError(f"Failed to get token supply for {token_address}")
            
            supply_info = response['result']['value']
            return {
                'supply': int(supply_info['amount']),
                'decimals': supply_info['decimals'],
                'ui_amount': float(supply_info['uiAmountString'])
            }
        except Exception as e:
            raise APIError(f"Failed to get token supply: {str(e)}")
    
    async def get_token_holders_count(self, token_address: str) -> int:
        """
        Get holder count for a Solana token using free methods.
        Try Birdeye API first (free), then fallback to RPC
        """
        
        # Method 1: Try alternative free APIs
        try:
            holder_count = await self._get_holders_alternative_apis(token_address)
            if holder_count > 0:
                return holder_count
        except Exception as e:
            logger.debug(f"Alternative APIs failed: {e}")
        
        # Method 2: Fallback to direct RPC call
        try:
            mint_pubkey = Pubkey.from_string(token_address)
            
            TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
            
            response = await self.client.get_program_accounts(
                TOKEN_PROGRAM_ID,
                encoding="base64",
                filters=[
                    {"dataSize": 165},
                    {"memcmp": {
                        "offset": 0,
                        "bytes": str(mint_pubkey)
                    }}
                ]
            )
            
            if response['result'] is None:
                logger.warning(f"No holder data found for {token_address}")
                return 0
            
            holders = set()
            for account in response['result']:
                account_data = base64.b64decode(account['account']['data'][0])
                owner_pubkey = Pubkey(account_data[32:64])
                amount = struct.unpack('<Q', account_data[64:72])[0]
                
                if amount > 0:
                    holders.add(str(owner_pubkey))
            
            holder_count = len(holders)
            logger.info(f"RPC: Token {token_address} has {holder_count} holders")
            return holder_count
            
        except Exception as e:
            logger.error(f"Failed to get token holders for {token_address}: {str(e)}")
            return 0
    
    async def _get_holders_alternative_apis(self, token_address: str) -> int:
        """Try alternative free APIs for holder count"""
        
        # Try GMGN API (appears to be free)
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://gmgn.ai/defi/quotation/v1/tokens/sol/{token_address}"
                
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("code") == 0 and "data" in data:
                            token_info = data["data"].get("token", {})
                            holder_count = token_info.get("holder_count", 0)
                            if holder_count > 0:
                                logger.info(f"GMGN API: Token {token_address} has {holder_count} holders")
                                return int(holder_count)
        except Exception as e:
            logger.debug(f"GMGN API error: {e}")
        
        # Try Pump.fun API for pump tokens
        try:
            if "pump" in token_address.lower():
                async with aiohttp.ClientSession() as session:
                    url = f"https://frontend-api.pump.fun/coins/{token_address}"
                    
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            holder_count = data.get("holder_count", 0)
                            if holder_count > 0:
                                logger.info(f"Pump.fun API: Token {token_address} has {holder_count} holders")
                                return int(holder_count)
        except Exception as e:
            logger.debug(f"Pump.fun API error: {e}")
        
        return 0
    
    async def get_token_price(self, token_address: str) -> Dict[str, Any]:
        raise NotImplementedError("Use DexScreenerAPI for price data")
    
    async def get_token_info(self, token_address: str) -> Dict[str, Any]:
        supply_info = await self.get_token_supply(token_address)
        holders_count = await self.get_token_holders_count(token_address)
        
        return {
            'address': token_address,
            'supply': supply_info['supply'],
            'decimals': supply_info['decimals'],
            'ui_amount': supply_info['ui_amount'],
            'holders_count': holders_count
        }