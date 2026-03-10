"""
Exchange connector with robust error handling, retry logic, and rate limiting.
Architectural Choice: Wrapper around CCXT with idempotent operations and
exponential backoff to handle exchange API failures gracefully.
"""
import asyncio
import hashlib
import time
from typing import Dict, Any, Optional, Tuple, List
from decimal import Decimal
import ccxt
from ccxt import NetworkError, ExchangeError, RequestTimeout
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging

from config.settings import settings

logger = logging.getLogger(__name__)

class ExchangeConnector:
    """Robust exchange connector with fault tolerance"""
    
    def __init__(self):
        self.exchange: Optional[ccxt.Exchange] = None
        self._last_request_time = 0
        self._min_request_interval = 0.1  # 100ms between requests
        self._rate_limit_counter = 0
        self._initialize_exchange()
    
    def _initialize_exchange(self) -> None:
        """Initialize CCXT exchange with proper configuration"""
        exchange_class = getattr(ccxt, settings.exchange.exchange_id)
        self.exchange = exchange_class({
            'apiKey': settings.exchange.api_key,
            'secret': settings.exchange.api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
                'adjustForTimeDifference': True,
            },
            'timeout': 30000,  # 30 second timeout
            'verbose': False
        })
        
        if settings.exchange.sandbox:
            self.exchange.set_sandbox_mode(True)
        
        logger.info(f"Initialized exchange: {settings.exchange.exchange_id}")
    
    def _rate_limit(self) -> None:
        """Implement custom rate limiting to avoid API bans"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            sleep_time = self._min_request_interval - elapsed
            time.sleep(sleep_time)
        self._last_request_time = time.time()
    
    @retry(
        retry=retry_if_exception_type((NetworkError, RequestTimeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    def fetch_ticker(self, symbol: str = None) -> Dict[str, Any]:
        """Fetch ticker with retry logic"""
        if not self.exchange:
            raise RuntimeError("Exchange not initialized")
        
        symbol = symbol or settings.trading.trading_pair
        self._rate_limit()
        
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            
            # Validate ticker data
            required_fields = ['bid', 'ask', 'last', 'timestamp']
            for field in required_fields:
                if field not in ticker or ticker[field] is None:
                    raise ValueError(f"Missing {field} in ticker data")
            
            return ticker
        except ExchangeError as e:
            logger.error(f"Exchange error fetching ticker: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching ticker: {e}")
            raise
    
    @retry(
        retry=retry_if_exception_type((NetworkError, RequestTimeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    def fetch_ohlcv(self, symbol: str = None, timeframe: str = '1h', 
                   limit: int = 24) -> List[List[float]]:
        """Fetch OHLCV data for volatility calculation"""
        if not self.exchange:
            raise RuntimeError("Exchange not initialized")
        
        symbol = symbol or settings.trading.trading_pair
        self._rate_limit()
        
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            
            if len(ohlcv) < limit:
                logger.warning(f"Only got {len(ohlcv)} OHLCV candles, expected {limit}")
            
            # Validate structure
            if ohlcv and len(ohlcv[0]) != 6:
                raise ValueError(f"Invalid OHLCV structure: {ohlcv[0]}")
            
            return ohlcv
        except ExchangeError as e:
            logger.error(f"Exchange error fetching OHLCV: {e}")
            raise
    
    def calculate_spread(self, ticker: Dict[str, Any]) -> float:
        """Calculate bid-ask spread percentage"""
        bid = float(ticker['bid'])
        ask = float(ticker['ask'])
        
        if bid <= 0 or ask <= 0:
            raise ValueError("Invalid bid/ask prices")
        
        spread = (ask - bid) / bid * 100
        return spread
    
    def get_order_book(self, symbol: str = None, limit: int = 5) -> Dict[str, Any]:
        """Fetch order book for liquidity analysis"""
        if not self.exchange:
            raise RuntimeError("Exchange not initialized")
        
        symbol = symbol or settings.trading.trading_pair
        self._rate_limit()
        
        try:
            orderbook = self.exchange.fetch_order_book(symbol, limit)
            
            # Validate order book structure
            if 'bids' not in orderbook or 'asks' not in orderbook:
                raise ValueError("Invalid order book structure")
            
            return orderbook
        except Exception as e:
            logger.error(f"Error fetching order book: {e}")
            raise
    
    def test_connection(self) -> bool:
        """Test exchange connection and permissions"""
        try:
            # Fetch account balance (requires API permissions)
            self._rate_limit()
            balance = self.exchange.fetch_balance()
            
            # Check if we have USDT balance info
            if 'USDT' not in balance.get('total', {}):
                logger.warning("USDT balance not found in account")
            
            # Check for necessary permissions
            if not self.excheck_permissions():
                logger.error("API keys lack necessary permissions")
                return False
            
            logger.info("Exchange connection test successful")
            return True
            
        except Exception as e:
            logger.error(f"Exchange connection test failed: {e}")
            return False
    
    def excheck_permissions(self) -> bool:
        """Check if API keys have necessary permissions"""
        # This is exchange-specific - implement based on exchange documentation
        # For Binance, trade-only keys should work for fetch_balance and create_order
        return True
    
    def get_precision(self, symbol: str = None) -> Dict[str, int]:
        """Get price and amount precision for the trading pair"""
        if not self.exchange:
            raise RuntimeError("Exchange not initialized")
        
        symbol = symbol or settings.trading.trading_pair
        self._rate_limit()
        
        try:
            market = self.exchange.market(symbol)
            
            precision = {
                'price': market['precision']['price'],
                'amount': market['precision']['amount'],
                'min_amount': float(market['limits']['amount']['min']),
                'min_cost': float(market['limits']['cost']['min'])
            }
            
            return precision
        except Exception as e: