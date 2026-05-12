from dataclasses import dataclass

@dataclass
class CueRegion:
    """Spatial definition representing where cues should spawn on-screen."""
    region_name: str = "bottom"
    origin: str = "10% 80%"  # e.g., left 10%, top 80%
    extent: str = "80% 15%"  # e.g., width 80%, height 15%
