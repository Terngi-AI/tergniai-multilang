class TerngiError(Exception):
    """Base exception for all Terngi SDK errors."""
    pass


class AuthenticationError(TerngiError):
    """Raised when authentication credentials (API key) are missing or invalid."""
    pass


class APIResponseError(TerngiError):
    """Raised when the Terngi API returns an HTTP error status code."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API Error {status_code}: {detail}")
