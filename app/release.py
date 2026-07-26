from __future__ import annotations

import hashlib
import platform
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

VERSION = "0.18.0-rc1"
RELEASE_CHANNEL = "rc"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BuildMetadata:
    version: str
    release_channel: str
    schema_version: int
    generated_at: str
    python_version: str
    platform: str
    build_id: str


def build_metadata() -> dict[str, object]:
    generated_at = datetime.now(timezone.utc).isoformat()
    seed = f"{VERSION}|{RELEASE_CHANNEL}|{platform.platform()}|{sys.version}".encode("utf-8")
    metadata = BuildMetadata(
        version=VERSION,
        release_channel=RELEASE_CHANNEL,
        schema_version=SCHEMA_VERSION,
        generated_at=generated_at,
        python_version=sys.version,
        platform=platform.platform(),
        build_id=hashlib.sha256(seed).hexdigest()[:16],
    )
    return asdict(metadata)
