"""EBU STL writer – EBU Tech 3264 binary subtitle format.

This is a custom writer (no external dependency).
EBU STL is a legacy binary format used in European teletext broadcasting.
Unlike the TTML-family writers, this format produces a binary file with a
fixed-length GSI (General Subtitle Information) header block followed by
fixed-length TTI (Teletext Information) records.

The writer consumes the same shared Cue schema as all other exporters.
"""

import struct

from .base import BaseBinaryExporter
from app.models.cue import Cue


def _format_timecode(ms: int, fps: int = 25) -> bytes:
    """Format milliseconds to EBU STL timecode bytes (HH, MM, SS, FF)."""
    val = max(0, ms)
    total_seconds, remainder_ms = divmod(val, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    frames = int(remainder_ms * fps / 1000)
    return bytes([hours % 100, minutes, seconds, frames])


def _encode_text_field(text: str, max_bytes: int = 112) -> bytes:
    """Encode cue text into an EBU STL TTI Text Field (TF).

    - Newlines become 0x8A (CR/LF in teletext).
    - Text is ISO 6937 / Latin-1 encoded.
    - Padded to max_bytes with 0x8F (filler).
    """
    result = bytearray()
    for char in text:
        if char == '\n':
            result.append(0x8A)  # Teletext newline
        else:
            try:
                result.extend(char.encode('latin-1'))
            except UnicodeEncodeError:
                result.append(0x3F)  # '?' fallback
    # Pad with teletext filler
    if len(result) < max_bytes:
        result.extend(b'\x8f' * (max_bytes - len(result)))
    return bytes(result[:max_bytes])


class EBUSTLExporter(BaseBinaryExporter):
    """
    Exports Cues to EBU STL (EBU Tech 3264) binary format.

    EBU STL is a legacy binary subtitle format used in European
    teletext broadcasting workflows. This writer produces a 1024-byte
    GSI header followed by 128-byte TTI records for each cue.
    """

    def generate(self, cues: list[Cue]) -> bytes:
        """Generate EBU STL binary content."""
        gsi = self._build_gsi(len(cues))
        tti_blocks = []
        for index, cue in enumerate(cues):
            tti_blocks.append(self._build_tti(index, cue))
        return gsi + b''.join(tti_blocks)

    def _build_gsi(self, subtitle_count: int) -> bytes:
        """Build the 1024-byte GSI (General Subtitle Information) block."""
        gsi = bytearray(1024)

        # Code Page Number (CPN) — 850 (Multilingual)
        gsi[0:3] = b'850'
        # Disk Format Code (DFC) — STL25.01 (25fps)
        gsi[3:11] = b'STL25.01'
        # Display Standard Code (DSC) — Level 1 Teletext
        gsi[11:12] = b'1'
        # Character Code Table (CCT) — 00 = Latin
        gsi[12:14] = b'00'
        # Language Code (LC) — EN
        gsi[14:16] = b'EN'
        # Original Programme Title (OPT) — padded to 32 bytes
        title = b'Lil Word Export'
        gsi[16:48] = title.ljust(32)
        # Original Episode Title (OET) — 32 bytes blank
        gsi[48:80] = b' ' * 32
        # Translated Programme Title (TPT) — 32 bytes blank
        gsi[80:112] = b' ' * 32
        # Translated Episode Title (TET) — 32 bytes blank
        gsi[112:144] = b' ' * 32
        # Translator's Name (TN) — 32 bytes blank
        gsi[144:176] = b' ' * 32
        # Translation Date (TCD) — 6 bytes (YYMMDD)
        gsi[176:182] = b'260421'
        # Revision Date (RD) — 6 bytes
        gsi[182:188] = b'260421'
        # Revision Number (RN) — 2 bytes
        gsi[188:190] = b'00'
        # Total Number of TTI blocks (TNB) — 5 chars
        gsi[190:195] = str(subtitle_count).rjust(5, '0').encode('ascii')[:5]
        # Total Number of Subtitles (TNS) — 5 chars
        gsi[195:200] = str(subtitle_count).rjust(5, '0').encode('ascii')[:5]
        # Total Number of Subtitle Groups (TNG) — 3 chars
        gsi[200:203] = b'001'
        # Maximum Number of Displayable Characters (MNC) — 2 chars
        gsi[203:205] = b'40'
        # Maximum Number of Displayable Rows (MNR) — 2 chars
        gsi[205:207] = b'23'
        # Time Code: Start-of-Programme (TCP) — 8 bytes HH:MM:SS:FF
        gsi[207:215] = b'00000000'
        # Time Code: First In-Cue (TCI) — 8 bytes
        gsi[215:223] = b'00000000'
        # Publisher — 32 bytes
        gsi[223:255] = b'Lil Word'.ljust(32)
        # Editor's Name — 32 bytes
        gsi[255:287] = b' ' * 32
        # Fill remainder with spaces
        gsi[287:1024] = b' ' * (1024 - 287)

        return bytes(gsi)

    def _build_tti(self, index: int, cue: Cue) -> bytes:
        """Build a single 128-byte TTI (Teletext Information) block."""
        tti = bytearray(128)

        # Subtitle Group Number (SGN) — 1 byte
        tti[0] = 0x00
        # Subtitle Number (SN) — 2 bytes (little-endian)
        struct.pack_into('<H', tti, 1, index)
        # Extension Block Number (EBN) — 1 byte (0xFF = last block)
        tti[3] = 0xFF
        # Cumulative Status (CS) — 1 byte (0x00 = not cumulative)
        tti[4] = 0x00
        # Time Code In (TCI) — 4 bytes
        tti[5:9] = _format_timecode(cue.start)
        # Time Code Out (TCO) — 4 bytes
        tti[9:13] = _format_timecode(cue.end)
        # Vertical Position (VP) — 1 byte (row 20 for bottom placement)
        tti[13] = 20
        # Justification Code (JC) — 1 byte (0x02 = centered)
        jc = 0x02  # default center
        if cue.style and cue.style.text_align == 'left':
            jc = 0x01
        elif cue.style and cue.style.text_align == 'right':
            jc = 0x03
        tti[14] = jc
        # Comment Flag (CF) — 1 byte (0x00 = subtitle data)
        tti[15] = 0x00
        # Text Field (TF) — 112 bytes
        tti[16:128] = _encode_text_field(cue.text)

        return bytes(tti)
