"""Validation helpers for user-configured export style settings.

Provides normalize/validate functions for freeform text fields in the
ExportSettingsDialog so obviously invalid values are caught at the
dialog boundary rather than silently flowing into TTML attribute output.
"""

import re

# CSS-style font-size patterns accepted by TTML renderers:
#   - percentage: "100%", "80%"
#   - pixel: "24px", "18px"
#   - point: "12pt"
#   - em: "1.2em"
_FONT_SIZE_PATTERN = re.compile(
    r'^\d+(\.\d+)?(px|pt|em|%)$',
    re.IGNORECASE
)

# Hex color patterns:
#   - 6-digit: #RRGGBB
#   - 8-digit with alpha: #RRGGBBAA
_HEX_COLOR_PATTERN = re.compile(
    r'^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$'
)

_DEFAULT_FONT_SIZE = "100%"
_DEFAULT_FILL_COLOR = "#FFFFFF"
_DEFAULT_BACKGROUND_COLOR = "#00000000"
_DEFAULT_REGION_ORIGIN = "10% 80%"
_DEFAULT_REGION_EXTENT = "80% 15%"

# TTML region placement format: two percentage values separated by space
# e.g., "10% 80%", "0% 0%", "5.5% 85%"
_REGION_PAIR_PATTERN = re.compile(
    r'^\d+(\.\d+)?%\s+\d+(\.\d+)?%$'
)


def validate_font_size(value: str) -> str:
    """Validate and normalize a font-size string.

    Returns the value if it matches a recognized CSS-style font-size
    pattern (e.g., '100%', '24px', '12pt', '1.2em').
    Returns the default '100%' if the value is empty or invalid.
    """
    stripped = value.strip()
    if not stripped:
        return _DEFAULT_FONT_SIZE
    if _FONT_SIZE_PATTERN.match(stripped):
        return stripped
    return _DEFAULT_FONT_SIZE


def _validate_hex_color(value: str, default: str) -> str:
    """Shared hex color validation with a caller-specified default."""
    stripped = value.strip()
    if not stripped:
        return default
    if _HEX_COLOR_PATTERN.match(stripped):
        return stripped.upper()
    return default


def validate_fill_color(value: str) -> str:
    """Validate and normalize a foreground/text hex color string.

    Returns the value (uppercased) if it matches #RRGGBB or #RRGGBBAA format.
    Returns the default '#FFFFFF' (opaque white) if the value is empty or invalid.
    """
    return _validate_hex_color(value, _DEFAULT_FILL_COLOR)


def validate_background_color(value: str) -> str:
    """Validate and normalize a background hex color string.

    Returns the value (uppercased) if it matches #RRGGBB or #RRGGBBAA format.
    Returns the default '#00000000' (fully transparent) if the value is empty or invalid.
    """
    return _validate_hex_color(value, _DEFAULT_BACKGROUND_COLOR)


def _validate_region_pair(value: str, default: str) -> str:
    """Shared region percentage-pair validation with range enforcement.

    Accepts 'X% Y%' where both X and Y are between 0 and 100 (inclusive).
    Returns *default* if the value is empty, malformed, or out of range.
    """
    stripped = value.strip()
    if not stripped:
        return default
    if not _REGION_PAIR_PATTERN.match(stripped):
        return default
    # Extract numeric values and enforce 0–100 range
    parts = stripped.replace('%', '').split()
    try:
        x, y = float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return default
    if not (0 <= x <= 100 and 0 <= y <= 100):
        return default
    return stripped


def validate_region_origin(value: str) -> str:
    """Validate a TTML region origin string (e.g., '10% 80%').

    Returns the value if it matches the 'X% Y%' percentage-pair format
    with both components in the 0–100 range.
    Returns the default '10% 80%' if the value is empty, malformed, or out of range.
    """
    return _validate_region_pair(value, _DEFAULT_REGION_ORIGIN)


def validate_region_extent(value: str) -> str:
    """Validate a TTML region extent string (e.g., '80% 15%').

    Returns the value if it matches the 'X% Y%' percentage-pair format
    with both components in the 0–100 range.
    Returns the default '80% 15%' if the value is empty, malformed, or out of range.
    """
    return _validate_region_pair(value, _DEFAULT_REGION_EXTENT)

