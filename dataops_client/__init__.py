"""
DataOps API Client Library

A Python client for consuming the StreamFlow DataOps REST API.
Provides easy access to station metadata, discharge observations, and configuration management.
"""

from .client import DataOpsClient
from .exceptions import (
    DataOpsAPIError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
    RateLimitError,
)

__version__ = "1.0.0"
__all__ = [
    "DataOpsClient",
    "DataOpsAPIError",
    "AuthenticationError",
    "NotFoundError",
    "ValidationError",
    "RateLimitError",
]
