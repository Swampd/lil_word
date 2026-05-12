from typing import Optional
from dataclasses import dataclass

from .style import CueStyle
from .region import CueRegion


@dataclass
class Cue:
    """An exporter-oriented styled text fragment tied to a time segment."""
    start: int
    end: int
    text: str
    style: Optional[CueStyle] = None
    region: Optional[CueRegion] = None
