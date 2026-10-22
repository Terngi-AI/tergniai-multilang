from typing import Optional


class TerngiError(Exception):
    """Base exception for all Terngi SDK errors."""


class APIResponseError(TerngiError):
    """Raised when the Terngi API returns an HTTP error status code."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"API Error {status_code}: {message}")


class AuthenticationError(APIResponseError):
    """Raised when the API key is missing or invalid (HTTP 401)."""


class RateLimitError(APIResponseError):
    """Raised when the client is rate-limited (HTTP 429); retry after `retry_after` seconds."""

    def __init__(self, status_code: int, message: str, retry_after: Optional[float]) -> None:
        super().__init__(status_code, message)
        self.retry_after = retry_after
