"""Shared color normalization helpers."""

import re


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")


def canonicalize_hex_color(value) -> str:
    """Trim and uppercase valid RGB/RGBA hex colors without changing invalid input."""
    text = str(value or "").strip()
    return text.upper() if _HEX_COLOR_RE.fullmatch(text) else text


def normalize_hex_color(value, default: str) -> str:
    """Return a canonical RGB/RGBA hex color, or ``default`` if invalid."""
    text = canonicalize_hex_color(value)
    return text if _HEX_COLOR_RE.fullmatch(text) else default
