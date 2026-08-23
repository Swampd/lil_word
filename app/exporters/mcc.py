"""MCC writer – MacCaption Closed Caption file format.

This is a custom writer (no external dependency).
MCC is a text-based closed caption format used in North American broadcast
workflows, primarily for CEA-608/708 caption data interchange.

The writer consumes the shared Cue schema and maps the following fields
to CEA-608 control codes within MCC:

Supported CueStyle fields:
- ``italic``     → CEA-608 mid-row code 91AE (italic on)
- ``underline``  → CEA-608 mid-row code 9121 (underline on)
- ``italic + underline`` → CEA-608 mid-row code 91AF (italic+underline)
- ``fill_color`` → CEA-608 mid-row color codes (green, blue, cyan, red,
                   yellow, magenta); unmapped colors fall back to white.
                   White (#FFFFFF) is the CEA-608 default and is not emitted
                   as an explicit mid-row code — it is implicit.

Not supported in CEA-608 / MCC (silently dropped):
- ``bold``              – no CEA-608 equivalent
- ``font_family``       – CEA-608 uses a fixed character set
- ``font_size``         – CEA-608 uses fixed cell dimensions
- ``background_color``  – limited CEA-608 background support not implemented
- ``text_align``        – would require Preamble Address Code column offsets;
                          not implemented (all captions left-aligned in data stream)

CueRegion fields (``region_name``, ``origin``, ``extent``):
- Not mapped – CEA-608 positioning uses row/column PACs which do not
  correspond cleanly to percentage-based origin/extent.  All cues render
  at the default row 15 (bottom of screen) position.
"""

import uuid
from datetime import datetime

from .base import BaseTextExporter
from app.models.cue import Cue


# CEA-608 mid-row color codes (channel 1, field 1).
# Each code sets the foreground color and resets italic/underline.
_CEA608_COLOR_MAP = {
    '#FFFFFF': '9120',  # white
    '#ffffff': '9120',
    '#00FF00': '9126',  # green
    '#00ff00': '9126',
    '#0000FF': '9128',  # blue
    '#0000ff': '9128',
    '#00FFFF': '912A',  # cyan
    '#00ffff': '912A',
    '#FF0000': '912C',  # red
    '#ff0000': '912C',
    '#FFFF00': '912E',  # yellow
    '#ffff00': '912E',
    '#FF00FF': '9130',  # magenta
    '#ff00ff': '9130',
}


def _format_timecode(ms: int, fps: int) -> str:
    """Format milliseconds to MCC SMPTE timecode 'HH:MM:SS:FF'."""
    val = max(0, ms)
    total_seconds, remainder_ms = divmod(val, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    frames = int(remainder_ms * fps / 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def _build_style_preamble(style) -> list[str]:
    """Build CEA-608 mid-row style codes from a CueStyle object.

    Returns a list of hex control code strings to insert before caption text.
    Returns empty list if the style maps to the default (white, no emphasis).
    """
    if style is None:
        return []

    codes = []

    # Color mapping — map fill_color to CEA-608 mid-row color code
    color_code = _CEA608_COLOR_MAP.get(style.fill_color)
    if color_code and style.fill_color.upper() != '#FFFFFF':
        codes.append(color_code)

    # Emphasis mapping — italic and/or underline via mid-row codes
    if style.italic and style.underline:
        codes.append('91AF')  # italic + underline
    elif style.italic:
        codes.append('91AE')  # italic only
    elif style.underline:
        codes.append('9121')  # underline only

    # bold is not supported in CEA-608 — silently dropped

    return codes


def _encode_caption_data(text: str) -> str:
    """Encode caption text into MCC hex-encoded caption data.

    MCC uses hex-encoded byte sequences for caption channel data.
    Printable ASCII characters are mapped to their CEA-608 byte pairs.
    Newlines produce carriage return commands.
    Non-ASCII characters fall back to '?' (0x3F).
    """
    result = []
    for char in text:
        if char == '\n':
            # CEA-608 carriage return
            result.append('9420')  # Resume caption loading
            result.append('94AD')  # Carriage return
        else:
            # Map printable ASCII to CEA-608 channel 1 byte pairs
            code = ord(char)
            if 0x20 <= code <= 0x7F:
                # Standard ASCII maps to itself in CEA-608 with parity
                result.append(f'{code:02X}80')
            else:
                # Non-ASCII fallback to '?'
                result.append('3F80')
    return ' '.join(result) if result else '8080'


class MCCExporter(BaseTextExporter):
    """
    Exports Cues to MCC (MacCaption Closed Caption) format.

    MCC is a text-based closed caption interchange format commonly used
    in North American broadcast and post-production workflows for
    CEA-608/708 caption data.

    See module docstring for the full list of supported and unsupported
    CueStyle / CueRegion field mappings.
    """

    def generate(self, cues: list[Cue], fps: int = 30) -> str:
        fps = max(1, int(fps))
        now = datetime.now()
        export_uuid = uuid.uuid4().hex[:16]

        lines = []

        # MCC file header
        lines.append('File Format=MacCaption_MCC V1.0')
        lines.append('')
        lines.append('////////////////////////////////////////////////////////////////////////////////////')
        lines.append('// Computer Readable')
        lines.append('////////////////////////////////////////////////////////////////////////////////////')
        lines.append('')
        lines.append(f'UUID={export_uuid}')
        lines.append('Creation Program=Lil Word')
        lines.append(f'Creation Date={now.strftime("%Y-%m-%d")}')
        lines.append(f'Creation Time={now.strftime("%H:%M:%S")}')
        lines.append('')
        lines.append(f'Time Code Rate={fps}')
        lines.append('')
        lines.append('////////////////////////////////////////////////////////////////////////////////////')
        lines.append('// Caption Data')
        lines.append('////////////////////////////////////////////////////////////////////////////////////')
        lines.append('')

        for cue in cues:
            tc_in = _format_timecode(cue.start, fps=fps)
            tc_out = _format_timecode(cue.end, fps=fps)
            caption_data = _encode_caption_data(cue.text)
            style_codes = _build_style_preamble(cue.style)

            # Build the caption data line with optional style preamble
            style_prefix = ' '.join(style_codes) + ' ' if style_codes else ''

            # Pop-on caption: load, optional style, text, display
            lines.append(f'{tc_in}\t9420 9420 {style_prefix}{caption_data} 942F 942F')
            # Erase at out-time
            lines.append(f'{tc_out}\t942C 942C')

        lines.append('')
        return '\n'.join(lines)
