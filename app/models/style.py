from dataclasses import dataclass

@dataclass
class CueStyle:
    """Explicit style configuration for a caption cue."""
    text_align: str = "center"
    italic: bool = False
    bold: bool = False
    underline: bool = False
    font_family: str = "Arial"
    font_size: str = "100%"
    fill_color: str = "#FFFFFF"
    background_color: str = "#00000000"
