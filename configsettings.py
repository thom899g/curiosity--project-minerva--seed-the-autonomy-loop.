"""
Configuration module for Project MINERVA.
Centralized settings with environment variable loading and type validation.
Architectural Choice: Separation of concerns - all configuration in one place
for easy maintenance and security auditing.
"""
import os
import json
from typing import Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path
from decimal import Decimal, getcontext
from dotenv import load_dotenv

# Set decimal precision for financial calculations
getcontext().prec = 10

load_dotenv()

@dataclass
class ExchangeConfig:
    """Exchange API configuration with validation"""
    api_key: str
    api_secret: str
    exchange_id: str = "binance"
    sandbox: bool = False
    
    def __post_init__(self):
        if not self.api_key or not self.api_secret:
            raise ValueError("API credentials must be provided")
        if len(self.api_key) < 20 or len(self.api_secret) < 20:
            raise ValueError("Invalid API credentials format")

@dataclass
class TradingConfig:
    """Trading parameters with safety bounds"""
    trading_pair: str = "BTC/USDT"
    base_buy_amount: Decimal = Decimal("10.0")  # USDT per DCA cycle
    max_buy_amount: Decimal = Decimal("50.0")   # Safety cap
    total_capital: Decimal = Decimal("162.0")   # 90% of $180
    max_position_size: Decimal = Decimal("153.9")  # 95% of trading capital
    
    # Volatility thresholds
    volatility_window_hours: int = 24
    volatility_threshold_multiplier: float = 2.0
    max_delay_hours: int = 24
    
    # Performance-based sizing
    evaluation_cycles: int = 10
    profit_threshold: float = 0.01  # 1%
    size_increment_step: float = 0.05  # 5%
    max_size_multiplier: float = 1.5  # 150%
    
    # Exit mechanisms
    trailing_stop_percent: float = 0.03  # 3%
    liquidity_filter_percent: float = 0.005  # 0.5%
    
    def __post_init__(self):
        # Validate all decimal amounts are positive
        for field in ['base_buy_amount', 'max_buy_amount', 'total_capital', 'max_position_size']:
            value = getattr(self, field)
            if value <= Decimal("0"):
                raise ValueError(f"{field} must be positive")

@dataclass
class CircuitBreakerConfig:
    """Circuit breaker thresholds for risk management"""
    price_drop_threshold: float = 0.10  # 10% in 1 hour
    price_drop_window_minutes: int = 60
    buying_pause_hours: int = 12
    
    portfolio_loss_threshold: float = 0.15  # 15% from ATH
    max_capital_loss_threshold: float = 0.20  # 20% - triggers manual review
    
    def __post_init__(self):
        if not (0 < self.price_drop_threshold < 1):
            raise ValueError("price_drop_threshold must be between 0 and 1")

@dataclass
class FirebaseConfig:
    """Firebase configuration with path validation"""
    service_account_path: str
    project_id: str
    collection_prefix: str = "minerva_v1"
    
    def __post_init__(self):
        if not Path(self.service_account_path).exists():
            raise FileNotFoundError(f"Firebase service account file not found: {self.service_account_path}")

@dataclass
class TelegramConfig:
    """Telegram bot configuration"""
    bot_token: str
    chat_id: str
    
    def __post_init__(self):
        if not self.bot_token.startswith("bot"):
            raise ValueError("Invalid Telegram bot token format")

@dataclass 
class TreasuryConfig:
    """Treasury management configuration"""
    cold_wallet_address: str
    profit_split_treasury: float = 0.80  # 80%
    profit_split_reinvestment: float = 0.20  # 20%
    min_profit_threshold: Decimal = Decimal("5.0")  # $5 minimum
    withdrawal_batch_days: int = 7
    
    def __post_init__(self):
        if len(self.cold_wallet_address) < 26:
            raise ValueError("Invalid wallet address length")
        if abs(self.profit_split_treasury + self.profit_split_reinvestment - 1.0) > 0.001:
            raise ValueError("Profit splits must sum to 1.0")

class Settings:
    """Main settings singleton with environment validation"""
    
    def __init__(self):
        self._validate_environment()
        
        # Exchange
        self.exchange = ExchangeConfig(
            api_key=os.getenv("BINANCE_API_KEY", ""),
            api_secret=os.getenv("BINANCE_API_SECRET", "")
        )
        
        # Trading
        self.trading = TradingConfig()
        
        # Circuit breakers
        self.circuit_breakers = CircuitBreakerConfig()
        
        # Firebase
        firebase_key_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "firebase-key.json")
        self.firebase = FirebaseConfig(
            service_account_path=firebase_key_path,
            project_id=os.getenv("FIREBASE_PROJECT_ID", "project-minerva")
        )
        
        # Telegram
        self.telegram = TelegramConfig(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.getenv("TELEGRAM_CHAT_ID", "")
        )
        
        # Treasury
        self.treasury = TreasuryConfig(
            cold_wallet_address=os.getenv("COLD_WALLET_ADDRESS", "")
        )
        
        # System paths
        self.emergency_pause_file = Path("emergency_pause.json")
        self.sqlite_db_path = Path("minerva_state.db")
        
        # Celery/RabbitMQ
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.celery_broker = self.redis_url
        self.celery_backend = self.redis_url
        
        # Validation
        self._validate_settings()
    
    def _validate_environment(self) -> None:
        """Validate required environment variables"""
        required_vars = [
            "BINANCE_API_KEY",
            "BINANCE_API_SECRET", 
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "COLD_WALLET_ADDRESS"
        ]
        
        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            raise EnvironmentError(f"Missing required environment variables: {missing}")
    
    def _validate_settings(self) -> None:
        """Cross-validate all settings for consistency"""
        if self.trading.base_buy_amount > self.trading.max_buy_amount:
            raise ValueError("base_buy_amount cannot exceed max_buy_amount")
        
        if self.trading.max_position_size > self.trading.total_capital:
            raise ValueError("max_position_size cannot exceed total_capital")
    
    def get_firestore_collection(self, name: str) -> str:
        """Get full collection name with prefix"""
        return f"{self.firebase.collection_prefix}_{name}"

# Global settings instance
settings = Settings()