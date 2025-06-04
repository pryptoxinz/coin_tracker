from typing import Dict, Any, List, Optional
from .base import BaseAPI, APIError
import aiohttp
import logging

logger = logging.getLogger(__name__)

class DexScreenerAPI(BaseAPI):
    def __init__(self):
        super().__init__("https://api.dexscreener.com/latest/dex/", rate_limit=0.5)
    
    async def get_token_price(self, token_address: str) -> Dict[str, Any]:
        try:
            logger.info(f"Fetching token data for {token_address}")
            response = await self._make_request("GET", f"tokens/{token_address}")
            
            if not response.get('pairs'):
                logger.warning(f"No trading pairs found for token {token_address}")
                raise APIError(f"Token {token_address} not found or has no trading pairs")
            
            # Get the most liquid pair (first one is usually highest volume)
            main_pair = response['pairs'][0]
            token_info = main_pair['baseToken'] if main_pair['baseToken']['address'] == token_address else main_pair['quoteToken']
            
            price_usd = float(main_pair.get('priceUsd', 0))
            market_cap = main_pair.get('marketCap', 0)
            liquidity = main_pair.get('liquidity', {}).get('usd', 0)
            volume_24h = main_pair.get('volume', {}).get('h24', 0)
            price_change_24h = main_pair.get('priceChange', {}).get('h24', 0)
            
            token_data = {
                'address': token_address,
                'name': token_info.get('name', 'Unknown'),
                'symbol': token_info.get('symbol', 'UNK'),
                'price': price_usd,
                'market_cap': market_cap,
                'liquidity': liquidity,
                'volume_24h': volume_24h,
                'price_change_24h': price_change_24h,
                'dex': main_pair.get('dexId', 'unknown'),
                'timestamp': main_pair.get('pairCreatedAt', 0),
                'fdv': main_pair.get('fdv', 0),
                'volume_1h': main_pair.get('volume', {}).get('h1', 0),
                'volume_6h': main_pair.get('volume', {}).get('h6', 0),
                'price_change_1h': main_pair.get('priceChange', {}).get('h1', 0),
                'price_change_6h': main_pair.get('priceChange', {}).get('h6', 0),
                'txns_24h_buys': main_pair.get('txns', {}).get('h24', {}).get('buys', 0),
                'txns_24h_sells': main_pair.get('txns', {}).get('h24', {}).get('sells', 0),
                'websites': main_pair.get('info', {}).get('websites', []),
                'socials': main_pair.get('info', {}).get('socials', []),
                'image_url': main_pair.get('info', {}).get('imageUrl', ''),
                'pair_address': main_pair.get('pairAddress', ''),
                'chain_id': main_pair.get('chainId', 'unknown')
            }
            
            logger.info(f"Token data fetched successfully: {token_info.get('name')} ({token_info.get('symbol')}) - ${price_usd:.6f}")
            return token_data
            
        except Exception as e:
            logger.error(f"Failed to fetch price for {token_address}: {str(e)}")
            raise APIError(f"Failed to fetch price for {token_address}: {str(e)}")
    
    async def get_multiple_prices(self, token_addresses: List[str]) -> Dict[str, Dict[str, Any]]:
        try:
            logger.info(f"Fetching data for {len(token_addresses)} tokens")
            result = {}
            
            # DexScreener doesn't support bulk requests, so fetch individually
            for address in token_addresses:
                try:
                    token_data = await self.get_token_price(address)
                    result[address] = token_data
                except APIError as e:
                    logger.warning(f"Failed to fetch data for {address}: {str(e)}")
                    continue
            
            logger.info(f"Successfully fetched data for {len(result)}/{len(token_addresses)} tokens")
            return result
        except Exception as e:
            logger.error(f"Failed to fetch multiple prices: {str(e)}")
            raise APIError(f"Failed to fetch multiple prices: {str(e)}")
    
    async def get_token_info(self, token_address: str) -> Dict[str, Any]:
        return await self.get_token_price(token_address)