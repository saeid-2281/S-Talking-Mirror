class STalkingError(Exception):
    """Base exception for S Talking."""


class ConfigurationError(STalkingError):
    """Raised when settings are missing or invalid."""


class CSVValidationError(STalkingError):
    """Raised when the input CSV is invalid."""


class ProviderError(STalkingError):
    """Raised when a TTS provider request fails."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
        provider_code: str | None = None,
        request_id: str | None = None,
        technical_details: str | None = None,
    ) -> None:
        super().__init__(message)
        self.user_message = message
        self.retryable = retryable
        self.http_status = http_status
        self.provider_code = provider_code
        self.request_id = request_id
        self.technical_details = technical_details or message
