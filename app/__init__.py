"""S-Talking package initialization."""

from app.config.media_runtime import configure_media_runtime
from app.release import RELEASE_CHANNEL, VERSION

# Configure Qt Multimedia before application services import PySide6.QtMultimedia.
MEDIA_RUNTIME = configure_media_runtime()

__version__ = VERSION
__release_channel__ = RELEASE_CHANNEL

__all__ = [
    "MEDIA_RUNTIME",
    "RELEASE_CHANNEL",
    "VERSION",
    "__release_channel__",
    "__version__",
]