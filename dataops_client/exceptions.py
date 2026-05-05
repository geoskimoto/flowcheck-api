"""Custom exceptions for DataOps API Client."""


class DataOpsAPIError(Exception):
    """Base exception for all DataOps API errors."""
    
    def __init__(self, message, status_code=None, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class AuthenticationError(DataOpsAPIError):
    """Raised when authentication fails."""
    pass


class NotFoundError(DataOpsAPIError):
    """Raised when a resource is not found (404)."""
    pass


class ValidationError(DataOpsAPIError):
    """Raised when request validation fails (400)."""
    pass


class RateLimitError(DataOpsAPIError):
    """Raised when rate limit is exceeded (429)."""
    pass


class TimeoutError(DataOpsAPIError):
    """Raised when a request times out."""
    pass


class ServerError(DataOpsAPIError):
    """Raised when server returns 5xx error."""
    pass
