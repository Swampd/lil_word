"""Project metadata model."""

from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class Project:
    """Represents a Lil Word project."""
    id: Optional[int] = None
    title: str = "Untitled"
    media_path: str = ""
    audio_path: str = ""
    proxy_path: str = ""
    media_duration_ms: int = 0
    has_video: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
