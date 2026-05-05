"""Configuration for DataOps API Client."""

import os
from typing import Optional


class ClientConfig:
    """Configuration settings for DataOps API Client."""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_token: Optional[str] = None,
        timeout: int = 60,
        verify_ssl: bool = True,
        cache_enabled: bool = True,
        cache_ttl: int = 300,
        max_retries: int = 3,
        backoff_factor: int = 2,
    ):
        """
        Initialize client configuration.
        
        Configuration can be loaded from environment variables:
        - DATAOPS_API_URL: Base URL of DataOps API
        - DATAOPS_API_TOKEN: JWT token or API key
        - DATAOPS_API_TIMEOUT: Request timeout (seconds)
        - DATAOPS_VERIFY_SSL: Whether to verify SSL certificates
        - DATAOPS_CACHE_ENABLED: Enable response caching
        - DATAOPS_CACHE_TTL: Cache time-to-live (seconds)
        """
        self.base_url = base_url or os.getenv('DATAOPS_API_URL', 'https://streamflowops.3rdplaces.io')
        self.api_token = api_token or os.getenv('DATAOPS_API_TOKEN')
        self.timeout = int(os.getenv('DATAOPS_API_TIMEOUT', timeout))
        self.verify_ssl = os.getenv('DATAOPS_VERIFY_SSL', str(verify_ssl)).lower() == 'true'
        self.cache_enabled = os.getenv('DATAOPS_CACHE_ENABLED', str(cache_enabled)).lower() == 'true'
        self.cache_ttl = int(os.getenv('DATAOPS_CACHE_TTL', cache_ttl))
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
    
    def to_dict(self):
        """Convert config to dictionary."""
        return {
            'base_url': self.base_url,
            'timeout': self.timeout,
            'verify_ssl': self.verify_ssl,
            'cache_enabled': self.cache_enabled,
            'cache_ttl': self.cache_ttl,
            'max_retries': self.max_retries,
            'backoff_factor': self.backoff_factor,
        }
    
    @classmethod
    def from_env(cls) -> 'ClientConfig':
        """Create configuration from environment variables."""
        return cls()
    
    def __repr__(self):
        return f"ClientConfig(base_url='{self.base_url}', timeout={self.timeout}, cache_enabled={self.cache_enabled})"
