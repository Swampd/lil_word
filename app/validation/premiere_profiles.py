from dataclasses import dataclass
from typing import Optional

from app.models.style import CueStyle
from app.models.region import CueRegion


@dataclass
class ExportProfile:
    """Explicit styling and layout baseline for specific export targets."""
    default_style: CueStyle
    default_region: CueRegion


def get_premiere_safe_profile(settings=None) -> ExportProfile:
    """Return a conservative Premiere-safe TTML formatting profile.

    If a Settings object is provided, user-configured export defaults
    override the hardcoded baseline values for font_family, font_size,
    fill_color, text_align, background_color, region_origin, and region_extent.
    """
    font_family = "Arial"
    font_size = "100%"
    fill_color = "#FFFFFF"
    background_color = "#00000000"
    text_align = "center"
    region_origin = "10% 80%"
    region_extent = "80% 15%"

    if settings is not None:
        from app.validation.export_style_validators import (
            validate_font_size, validate_fill_color, validate_background_color,
            validate_region_origin, validate_region_extent,
        )
        font_family = settings.get("export_font_family", font_family)
        font_size = validate_font_size(settings.get("export_font_size", font_size))
        fill_color = validate_fill_color(settings.get("export_fill_color", fill_color))
        background_color = validate_background_color(settings.get("export_background_color", background_color))
        text_align = settings.get("export_text_align", text_align)
        region_origin = validate_region_origin(settings.get("export_region_origin", region_origin))
        region_extent = validate_region_extent(settings.get("export_region_extent", region_extent))

    return ExportProfile(
        default_style=CueStyle(
            font_family=font_family,
            font_size=font_size,
            fill_color=fill_color,
            background_color=background_color,
            text_align=text_align
        ),
        default_region=CueRegion(
            region_name="default-region",
            origin=region_origin,
            extent=region_extent
        )
    )
