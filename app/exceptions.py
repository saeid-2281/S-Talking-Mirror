class STalkingError(Exception):
    """Base exception for S Talking."""


class ConfigurationError(STalkingError):
    """Raised when settings are missing or invalid."""


class CSVValidationError(STalkingError):
    """Raised when the input CSV is invalid."""


class ProviderError(STalkingError):
    """Raised when a TTS provider request fails."""
