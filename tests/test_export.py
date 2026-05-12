"""Tests for export – SRT, ASS output, and the shared build_export_name helper."""

import tempfile
import os
from pathlib import Path

from app.models.caption import Caption
from app.services.export_service import export_srt, export_ass, export_ttml, export_ebu_tt, export_smpte_tt, export_ebu_stl, export_mcc
from app.exporters.ttml_dfxp import TTMLExporter
from app.exporters.base import BaseExporter
from app.utils.export_helpers import build_export_name
from app.services.caption_engine import normalize_captions


def test_srt_export_contains_text():
    captions = [
        Caption(start_ms=0, end_ms=2000, text="Hello world"),
        Caption(start_ms=2500, end_ms=4000, text="Goodbye world"),
    ]
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False, mode="w") as f:
        path = f.name
    try:
        export_srt(captions, path)
        content = Path(path).read_text(encoding="utf-8")
        assert "Hello world" in content
        assert "Goodbye world" in content
        assert "00:00:00,000" in content
        assert "00:00:02,000" in content
    finally:
        os.unlink(path)


def test_srt_export_edited_text():
    """Editing a caption's text should appear in the exported SRT."""
    captions = [Caption(start_ms=0, end_ms=1000, text="Original")]
    captions[0].text = "Edited caption text"
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False, mode="w") as f:
        path = f.name
    try:
        export_srt(captions, path)
        content = Path(path).read_text(encoding="utf-8")
        assert "Edited caption text" in content
        assert "Original" not in content
    finally:
        os.unlink(path)


def test_ass_export_newline_conversion():
    captions = [
        Caption(start_ms=0, end_ms=2000, text="Line one\nLine two"),
    ]
    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w") as f:
        path = f.name
    try:
        export_ass(captions, path)
        content = Path(path).read_text(encoding="utf-8")
        assert "\\N" in content  # ASS line break
        # Raw newline should not appear in dialogue lines
        for line in content.split("\n"):
            if line.startswith("Dialogue:"):
                assert "\nLine two" not in line
    finally:
        os.unlink(path)

# ── TTML Exporter Layers ────────────────────────────────────────────────────────────

def test_ttml_schema_conversion():
    """Verify internal Caption formats cleanly translate to additive Cue schema without breaking default styling values."""
    captions = [
        Caption(start_ms=1000, end_ms=2000, text="First Block\nBreak"),
    ]
    cues = BaseExporter.convert_captions(captions)
    assert len(cues) == 1
    cue = cues[0]
    assert cue.start == 1000
    assert cue.end == 2000
    assert cue.text == "First Block\nBreak"
    assert cue.style is not None
    assert cue.style.font_family == "Arial"
    assert cue.region.region_name == "default-region"

def test_ttml_export():
    """Verify TTML structure explicitly maps cues to safe regions & valid XML namespaces."""
    captions = [
        Caption(start_ms=0, end_ms=2000, text="Hello & world"),
        Caption(start_ms=2500, end_ms=4555, text="Newline\nhere")
    ]
    
    with tempfile.NamedTemporaryFile(suffix=".ttml", delete=False, mode="w") as f:
        path = f.name
    try:
        export_ttml(captions, path)
        content = Path(path).read_text(encoding="utf-8")
        
        # Check explicit namespaces
        assert 'xmlns="http://www.w3.org/ns/ttml"' in content
        assert 'xml:id="style-0"' in content
        
        # Check first caption (special & escape translation safely executed by saxutils)
        assert 'begin="00:00:00.000"' in content
        assert 'end="00:00:02.000"' in content
        assert 'Hello &amp; world' in content
        
        # Check second caption correctly parsed the multiline newline to <br /> element
        assert 'begin="00:00:02.500"' in content
        assert 'end="00:00:04.555"' in content
        assert 'Newline<br />here' in content
        
    finally:
        os.unlink(path)


# ── build_export_name tests (testing production code) ────────────────────────

def test_export_name_srt():
    result = build_export_name("C:/test/video.mp4", ".srt")
    assert result.endswith(".srt")
    assert "video" in result


def test_export_name_ass():
    result = build_export_name("C:/test/video.mp4", ".ass")
    assert result.endswith(".ass")
    assert "video" in result


def test_export_name_subtitled_mp4():
    """Stem suffix should not crash (was a ValueError with Path.with_suffix)."""
    result = build_export_name("C:/test/video.mp4", "_subtitled.mp4")
    assert result.endswith("video_subtitled.mp4")


def test_export_name_no_media():
    result = build_export_name("", ".srt")
    assert result == "export.srt"


def test_export_name_no_media_stem_suffix():
    result = build_export_name("", "_subtitled.mp4")
    assert result == "export_subtitled.mp4"


def test_export_name_ttml_xml():
    result = build_export_name("C:/test/video.mp4", "_ttml.xml")
    assert result.endswith("video_ttml.xml")


def test_export_name_ebu_tt_xml():
    result = build_export_name("C:/test/video.mp4", "_ebu_tt.xml")
    assert result.endswith("video_ebu_tt.xml")


def test_export_name_smpte_tt_xml():
    result = build_export_name("C:/test/video.mp4", "_smpte_tt.xml")
    assert result.endswith("video_smpte_tt.xml")


def test_export_name_ebu_stl():
    result = build_export_name("C:/test/video.mp4", "_ebu.stl")
    assert result.endswith("video_ebu.stl")


def test_export_name_mcc():
    result = build_export_name("C:/test/video.mp4", ".mcc")
    assert result.endswith(".mcc")
    assert "video" in result


# ── SRT/ASS should not contain zero-duration captions ────────────────────────

def test_srt_export_omits_zero_duration():
    """Captions normalized to zero-duration at media end should be dropped."""
    captions = [
        Caption(start_ms=0, end_ms=2000, text="Visible"),
        Caption(start_ms=4000, end_ms=5000, text="After media end"),
    ]
    captions = normalize_captions(captions, media_duration_ms=3000)
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False, mode="w") as f:
        path = f.name
    try:
        export_srt(captions, path)
        content = Path(path).read_text(encoding="utf-8")
        # "Visible" should be present; zero-dur caption should not produce a standalone cue
        assert "Visible" in content
        # No cue with identical start/end times
        lines = content.strip().split("\n")
        for line in lines:
            if "-->" in line:
                parts = line.split("-->")
                assert parts[0].strip() != parts[1].strip()
    finally:
        os.unlink(path)


def test_ass_export_omits_zero_duration():
    """Same as above for ASS format."""
    captions = [
        Caption(start_ms=0, end_ms=2000, text="Visible"),
        Caption(start_ms=4000, end_ms=5000, text="After media end"),
    ]
    captions = normalize_captions(captions, media_duration_ms=3000)
    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w") as f:
        path = f.name
    try:
        export_ass(captions, path)
        content = Path(path).read_text(encoding="utf-8")
        assert "Visible" in content
        # Every Dialogue line should have different start and end
        for line in content.split("\n"):
            if line.startswith("Dialogue:"):
                parts = line.split(",")
                start, end = parts[1], parts[2]
                assert start != end
    finally:
        os.unlink(path)

def test_ttml_schema_cues_independent_styles():
    """Verify that multiple cues generate independent copies of the baseline style/region."""
    from app.exporters.base import BaseExporter
    from app.models.caption import Caption
    captions = [
        Caption(start_ms=1000, end_ms=2000, text="First"),
        Caption(start_ms=2000, end_ms=3000, text="Second"),
    ]
    cues = BaseExporter.convert_captions(captions)
    assert len(cues) == 2
    assert cues[0].style is not cues[1].style
    assert cues[0].region is not cues[1].region
    
    # Prove mutating one does not mutate the other
    cues[0].style.font_family = "Courier New"
    assert cues[1].style.font_family == "Arial"

def test_ttml_export_dynamic_styles():
    """Verify TTML structure accurately processes multi-styling cues."""
    from app.models.cue import Cue, CueStyle, CueRegion
    from app.exporters.ttml_dfxp import TTMLExporter
    cues = [
        Cue(start=0, end=1000, text="One", style=CueStyle(font_family="Arial"), region=CueRegion(origin="0% 0%")),
        Cue(start=1000, end=2000, text="Two", style=CueStyle(font_family="Helvetica"), region=CueRegion(origin="0% 50%")),
        Cue(start=2000, end=3000, text="Three", style=CueStyle(font_family="Arial"), region=CueRegion(origin="0% 0%"))
    ]
    exporter = TTMLExporter()
    content = exporter.generate(cues)
    
    # We should have exactly 2 style blocks and 2 layout blocks
    assert content.count('<style xml:id="style-') == 2
    assert content.count('<region xml:id="bottom-') == 2
    
    assert 'region="bottom-0" style="style-0"' in content
    assert 'region="bottom-1" style="style-1"' in content
    
    assert 'tts:fontFamily="Helvetica"' in content

def test_ttml_full_schema_attributes():
    """Verify TTML schema honors italic, bold, underline and maps semantic region names."""
    from app.models.cue import Cue, CueStyle, CueRegion
    from app.exporters.ttml_dfxp import TTMLExporter
    cues = [
        # Normal
        Cue(start=0, end=1000, text="One", style=CueStyle(), region=CueRegion()),
        # Italic only
        Cue(start=1000, end=2000, text="Two", style=CueStyle(italic=True), region=CueRegion(region_name="custom-name")),
        # Bold only
        Cue(start=2000, end=3000, text="Three", style=CueStyle(bold=True), region=CueRegion()),
        # Underline only
        Cue(start=3000, end=4000, text="Four", style=CueStyle(underline=True), region=CueRegion())
    ]
    exporter = TTMLExporter()
    content = exporter.generate(cues)
    
    # Assert semantic id behavior explicitly hooks onto region_name
    assert 'xml:id="custom_name-1"' in content

    # Assert distinct styles based ONLY on stylistic attributes
    assert content.count('<style xml:id="style-') == 4
    
    # Assert emission blocks exist correctly mapped
    assert 'tts:fontStyle="italic"' in content
    assert 'tts:fontWeight="bold"' in content 
    assert 'tts:textDecoration="underline"' in content 
    
    assert 'tts:fontStyle="normal"' in content
    assert 'tts:fontWeight="normal"' in content
    assert 'tts:textDecoration="none"' in content


# ── EBU-TT exporter tests ────────────────────────────────────────────────────

def test_ebu_tt_structure_and_namespaces():
    """Verify EBU-TT output contains required namespaces and EBU metadata."""
    captions = [
        Caption(start_ms=0, end_ms=2000, text="Hello & world"),
        Caption(start_ms=2500, end_ms=4555, text="Newline\nhere")
    ]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as f:
        path = f.name
    try:
        export_ebu_tt(captions, path)
        content = Path(path).read_text(encoding="utf-8")

        # EBU-TT namespaces
        assert 'xmlns="http://www.w3.org/ns/ttml"' in content
        assert 'xmlns:ebuttm="urn:ebu:tt:metadata"' in content
        assert 'xmlns:ebutts="urn:ebu:tt:style"' in content
        assert 'ttp:timeBase="media"' in content

        # EBU metadata block
        assert 'ebuttm:documentMetadata' in content
        assert 'ebuttm:conformsToStandard' in content

        # EBU-TT specific style attribute
        assert 'ebutts:linePadding="0.5c"' in content
    finally:
        os.unlink(path)


def test_ebu_tt_timing_and_text():
    """Verify EBU-TT timing codes and text escaping."""
    captions = [
        Caption(start_ms=0, end_ms=2000, text="Hello & world"),
        Caption(start_ms=2500, end_ms=4555, text="Newline\nhere")
    ]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as f:
        path = f.name
    try:
        export_ebu_tt(captions, path)
        content = Path(path).read_text(encoding="utf-8")

        # Timing
        assert 'begin="00:00:00.000"' in content
        assert 'end="00:00:02.000"' in content
        assert 'begin="00:00:02.500"' in content
        assert 'end="00:00:04.555"' in content

        # Escaping
        assert 'Hello &amp; world' in content

        # Newline → <br />
        assert 'Newline<br />here' in content
    finally:
        os.unlink(path)


def test_ebu_tt_explicit_styles_and_regions():
    """Verify EBU-TT emits explicit style/region blocks driven by the normalized schema."""
    from app.models.cue import Cue, CueStyle, CueRegion
    from app.exporters.ebu_tt import EBUTTExporter

    cues = [
        Cue(start=0, end=1000, text="Normal",
            style=CueStyle(), region=CueRegion()),
        Cue(start=1000, end=2000, text="Styled",
            style=CueStyle(italic=True, bold=True, underline=True, font_family="Courier New"),
            region=CueRegion(region_name="top", origin="10% 10%", extent="80% 20%")),
    ]
    exporter = EBUTTExporter()
    content = exporter.generate(cues)

    # Two distinct styles
    assert content.count('<style xml:id="style-') == 2

    # Styled cue attributes
    assert 'tts:fontFamily="Courier New"' in content
    assert 'tts:fontStyle="italic"' in content
    assert 'tts:fontWeight="bold"' in content
    assert 'tts:textDecoration="underline"' in content

    # Normal cue defaults
    assert 'tts:fontStyle="normal"' in content
    assert 'tts:fontWeight="normal"' in content
    assert 'tts:textDecoration="none"' in content

    # Region with semantic name
    assert 'xml:id="top-1"' in content
    assert 'tts:origin="10% 10%"' in content
    assert 'tts:extent="80% 20%"' in content

    # EBU-TT region attributes
    assert 'tts:displayAlign="after"' in content
    assert 'tts:overflow="visible"' in content


# ── SMPTE-TT exporter tests ──────────────────────────────────────────────────

def test_smpte_tt_structure_and_namespaces():
    """Verify SMPTE-TT output contains required namespaces and SMPTE metadata."""
    captions = [
        Caption(start_ms=0, end_ms=2000, text="Hello & world"),
        Caption(start_ms=2500, end_ms=4555, text="Newline\nhere")
    ]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as f:
        path = f.name
    try:
        export_smpte_tt(captions, path)
        content = Path(path).read_text(encoding="utf-8")

        # SMPTE-TT namespaces
        assert 'xmlns="http://www.w3.org/ns/ttml"' in content
        assert 'xmlns:smpte="http://www.smpte-ra.org/schemas/2052-1/2010/smpte-tt"' in content
        assert 'ttp:timeBase="media"' in content
        assert 'ttp:cellResolution="32 15"' in content

        # SMPTE metadata block
        assert 'smpte:information' in content
        assert 'smpte:mode="Enhanced"' in content
    finally:
        os.unlink(path)


def test_smpte_tt_timing_and_text():
    """Verify SMPTE-TT timing codes and text escaping."""
    captions = [
        Caption(start_ms=0, end_ms=2000, text="Hello & world"),
        Caption(start_ms=2500, end_ms=4555, text="Newline\nhere")
    ]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as f:
        path = f.name
    try:
        export_smpte_tt(captions, path)
        content = Path(path).read_text(encoding="utf-8")

        # Timing
        assert 'begin="00:00:00.000"' in content
        assert 'end="00:00:02.000"' in content
        assert 'begin="00:00:02.500"' in content
        assert 'end="00:00:04.555"' in content

        # Escaping
        assert 'Hello &amp; world' in content

        # Newline → <br />
        assert 'Newline<br />here' in content
    finally:
        os.unlink(path)


def test_smpte_tt_explicit_styles_and_regions():
    """Verify SMPTE-TT emits explicit style/region blocks driven by the normalized schema."""
    from app.models.cue import Cue, CueStyle, CueRegion
    from app.exporters.smpte_tt import SMPTETTExporter

    cues = [
        Cue(start=0, end=1000, text="Normal",
            style=CueStyle(), region=CueRegion()),
        Cue(start=1000, end=2000, text="Styled",
            style=CueStyle(italic=True, bold=True, underline=True, font_family="Courier New"),
            region=CueRegion(region_name="top", origin="10% 10%", extent="80% 20%")),
    ]
    exporter = SMPTETTExporter()
    content = exporter.generate(cues)

    # Two distinct styles
    assert content.count('<style xml:id="style-') == 2

    # Styled cue attributes
    assert 'tts:fontFamily="Courier New"' in content
    assert 'tts:fontStyle="italic"' in content
    assert 'tts:fontWeight="bold"' in content
    assert 'tts:textDecoration="underline"' in content

    # Normal cue defaults
    assert 'tts:fontStyle="normal"' in content
    assert 'tts:fontWeight="normal"' in content
    assert 'tts:textDecoration="none"' in content

    # Region with semantic name
    assert 'xml:id="top-1"' in content
    assert 'tts:origin="10% 10%"' in content
    assert 'tts:extent="80% 20%"' in content

    # SMPTE-TT region attributes
    assert 'tts:displayAlign="after"' in content
    assert 'tts:writingMode="lrtb"' in content
    assert 'tts:overflow="visible"' in content


# ── EBU STL exporter tests ───────────────────────────────────────────────────

def test_ebu_stl_binary_structure():
    """Verify EBU STL produces correct binary structure (GSI + TTI blocks)."""
    captions = [
        Caption(start_ms=0, end_ms=2000, text="Hello world"),
        Caption(start_ms=2500, end_ms=4000, text="Second cue")
    ]
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        path = f.name
    try:
        export_ebu_stl(captions, path)
        data = Path(path).read_bytes()

        # GSI block is 1024 bytes + 2 TTI blocks of 128 bytes each
        assert len(data) == 1024 + 2 * 128

        # GSI header checks
        assert data[0:3] == b'850'  # Code Page Number
        assert data[3:11] == b'STL25.01'  # Disk Format Code
        assert data[12:14] == b'00'  # CCT Latin
        assert data[14:16] == b'EN'  # Language Code
        assert b'Lil Word Export' in data[16:48]
    finally:
        os.unlink(path)


def test_ebu_stl_timing():
    """Verify EBU STL TTI timecodes are correct."""
    captions = [
        Caption(start_ms=3600000 + 120000 + 5000 + 200, end_ms=3600000 + 120000 + 10000 + 400,
                text="Timed cue")
    ]
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        path = f.name
    try:
        export_ebu_stl(captions, path)
        data = Path(path).read_bytes()

        # TTI starts at offset 1024
        tti = data[1024:1024 + 128]
        # TCI at bytes 5-8: 01:02:05.200 at 25fps = frame 5
        assert tti[5] == 1   # hours
        assert tti[6] == 2   # minutes
        assert tti[7] == 5   # seconds
        assert tti[8] == 5   # frames (200ms * 25fps / 1000 = 5)
        # TCO at bytes 9-12: 01:02:10.400 at 25fps = frame 10
        assert tti[9] == 1   # hours
        assert tti[10] == 2  # minutes
        assert tti[11] == 10 # seconds
        assert tti[12] == 10 # frames (400ms * 25fps / 1000 = 10)
    finally:
        os.unlink(path)


def test_ebu_stl_text_encoding():
    """Verify EBU STL text field encoding and newline handling."""
    captions = [
        Caption(start_ms=0, end_ms=1000, text="Line one\nLine two")
    ]
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        path = f.name
    try:
        export_ebu_stl(captions, path)
        data = Path(path).read_bytes()

        # TTI text field starts at offset 1024 + 16
        text_field = data[1024 + 16: 1024 + 128]
        assert b'Line one' in text_field
        assert 0x8A in text_field  # Teletext newline
        assert b'Line two' in text_field
        assert text_field.endswith(b'\x8f')  # Filler padding at end
    finally:
        os.unlink(path)


def test_ebu_stl_justification():
    """Verify EBU STL honors text alignment from CueStyle."""
    from app.models.cue import Cue, CueStyle, CueRegion
    from app.exporters.ebu_stl import EBUSTLExporter

    cues = [
        Cue(start=0, end=1000, text="Left", style=CueStyle(text_align='left'), region=CueRegion()),
        Cue(start=1000, end=2000, text="Center", style=CueStyle(text_align='center'), region=CueRegion()),
        Cue(start=2000, end=3000, text="Right", style=CueStyle(text_align='right'), region=CueRegion()),
    ]
    exporter = EBUSTLExporter()
    data = exporter.generate(cues)

    # JC byte is at offset 14 within each 128-byte TTI block
    tti_0 = data[1024:1024 + 128]
    tti_1 = data[1024 + 128:1024 + 256]
    tti_2 = data[1024 + 256:1024 + 384]

    assert tti_0[14] == 0x01  # left
    assert tti_1[14] == 0x02  # center
    assert tti_2[14] == 0x03  # right


# ── MCC exporter tests ────────────────────────────────────────────────────────

def test_mcc_structure_and_header():
    """Verify MCC output contains required header fields with real generated metadata."""
    captions = [
        Caption(start_ms=0, end_ms=2000, text="Hello world"),
    ]
    with tempfile.NamedTemporaryFile(suffix=".mcc", delete=False, mode="w") as f:
        path = f.name
    try:
        export_mcc(captions, path)
        content = Path(path).read_text(encoding="utf-8")

        # MCC format header
        assert 'File Format=MacCaption_MCC V1.0' in content
        assert 'Creation Program=Lil Word' in content
        assert 'Time Code Rate=30' in content
        assert 'Caption Data' in content

        # Real generated UUID — 16 hex chars, not the old fixed placeholder
        import re
        uuid_match = re.search(r'UUID=([0-9a-f]{16})', content)
        assert uuid_match is not None, "UUID should be a 16-char hex string, not a fixed placeholder"

        # Real generated date — YYYY-MM-DD format
        date_match = re.search(r'Creation Date=(\d{4}-\d{2}-\d{2})', content)
        assert date_match is not None, "Creation Date should be in YYYY-MM-DD format"

        # Real generated time — HH:MM:SS format
        time_match = re.search(r'Creation Time=(\d{2}:\d{2}:\d{2})', content)
        assert time_match is not None, "Creation Time should be in HH:MM:SS format"
    finally:
        os.unlink(path)


def test_mcc_timing():
    """Verify MCC timecodes are correct SMPTE format."""
    captions = [
        Caption(start_ms=0, end_ms=2000, text="First"),
        Caption(start_ms=3600000 + 120000 + 5000 + 333, end_ms=3600000 + 120000 + 10000, text="Second"),
    ]
    with tempfile.NamedTemporaryFile(suffix=".mcc", delete=False, mode="w") as f:
        path = f.name
    try:
        export_mcc(captions, path)
        content = Path(path).read_text(encoding="utf-8")

        # First cue
        assert '00:00:00:00' in content  # start
        assert '00:00:02:00' in content  # end (erase line)

        # Second cue — 1h 2m 5s 333ms at 30fps = frame 9
        assert '01:02:05:09' in content
        assert '01:02:10:00' in content
    finally:
        os.unlink(path)


def test_mcc_caption_data_encoding():
    """Verify MCC text encoding produces hex caption data."""
    captions = [
        Caption(start_ms=0, end_ms=1000, text="Hi"),
    ]
    with tempfile.NamedTemporaryFile(suffix=".mcc", delete=False, mode="w") as f:
        path = f.name
    try:
        export_mcc(captions, path)
        content = Path(path).read_text(encoding="utf-8")

        # 'H' = 0x48, 'i' = 0x69 → hex pairs 4880 6980
        assert '4880' in content
        assert '6980' in content

        # Pop-on caption control codes
        assert '9420' in content  # Resume caption loading
        assert '942F' in content  # End of caption (flip)
        assert '942C' in content  # Erase displayed memory
    finally:
        os.unlink(path)


def test_mcc_newline_handling():
    """Verify MCC newlines produce carriage return control codes."""
    captions = [
        Caption(start_ms=0, end_ms=1000, text="Line1\nLine2"),
    ]
    with tempfile.NamedTemporaryFile(suffix=".mcc", delete=False, mode="w") as f:
        path = f.name
    try:
        export_mcc(captions, path)
        content = Path(path).read_text(encoding="utf-8")

        # Newline produces CEA-608 carriage return sequence
        assert '94AD' in content  # Carriage return
    finally:
        os.unlink(path)


def test_mcc_italic_style():
    """Verify MCC emits CEA-608 italic mid-row code when CueStyle.italic is set."""
    from app.models.cue import Cue, CueStyle, CueRegion
    from app.exporters.mcc import MCCExporter

    cues = [
        Cue(start=0, end=1000, text="Emphasis",
            style=CueStyle(italic=True), region=CueRegion()),
    ]
    exporter = MCCExporter()
    content = exporter.generate(cues)
    # 91AE = italic on (mid-row code)
    assert '91AE' in content


def test_mcc_underline_style():
    """Verify MCC emits CEA-608 underline mid-row code when CueStyle.underline is set."""
    from app.models.cue import Cue, CueStyle, CueRegion
    from app.exporters.mcc import MCCExporter

    cues = [
        Cue(start=0, end=1000, text="Underlined",
            style=CueStyle(underline=True), region=CueRegion()),
    ]
    exporter = MCCExporter()
    content = exporter.generate(cues)
    # 9121 = underline on (mid-row code)
    assert '9121' in content


def test_mcc_italic_underline_combined():
    """Verify MCC emits combined italic+underline mid-row code."""
    from app.models.cue import Cue, CueStyle, CueRegion
    from app.exporters.mcc import MCCExporter

    cues = [
        Cue(start=0, end=1000, text="Both",
            style=CueStyle(italic=True, underline=True), region=CueRegion()),
    ]
    exporter = MCCExporter()
    content = exporter.generate(cues)
    # 91AF = italic + underline combined
    assert '91AF' in content


def test_mcc_color_mapping():
    """Verify MCC emits correct CEA-608 mid-row color codes for supported colors."""
    from app.models.cue import Cue, CueStyle, CueRegion
    from app.exporters.mcc import MCCExporter

    test_cases = [
        ('#00FF00', '9126'),  # green
        ('#0000FF', '9128'),  # blue
        ('#00FFFF', '912A'),  # cyan
        ('#FF0000', '912C'),  # red
        ('#FFFF00', '912E'),  # yellow
        ('#FF00FF', '9130'),  # magenta
    ]
    for color, expected_code in test_cases:
        cues = [
            Cue(start=0, end=1000, text="Color",
                style=CueStyle(fill_color=color), region=CueRegion()),
        ]
        exporter = MCCExporter()
        content = exporter.generate(cues)
        assert expected_code in content, f"Color {color} should produce code {expected_code}"


def test_mcc_white_is_default_no_color_code():
    """Verify MCC does not emit a redundant color code for white (the default)."""
    from app.models.cue import Cue, CueStyle, CueRegion
    from app.exporters.mcc import MCCExporter

    cues = [
        Cue(start=0, end=1000, text="Default",
            style=CueStyle(fill_color='#FFFFFF'), region=CueRegion()),
    ]
    exporter = MCCExporter()
    content = exporter.generate(cues)
    # White is the default — no color mid-row code should be emitted
    # (9120 is the white code but we skip it when it's the default)
    # The line should just have 9420 + text data + 942F
    lines = [l for l in content.split('\n') if '942F' in l]
    assert len(lines) == 1
    # Should NOT have any mid-row color code before the text data
    assert '9120' not in lines[0].split('\t')[1].split(' 9420 9420 ')[0] if '9420 9420' in lines[0] else True


def test_mcc_bold_silently_dropped():
    """Verify MCC does not crash or emit bogus codes when CueStyle.bold is set (unsupported)."""
    from app.models.cue import Cue, CueStyle, CueRegion
    from app.exporters.mcc import MCCExporter

    cues = [
        Cue(start=0, end=1000, text="Bold",
            style=CueStyle(bold=True), region=CueRegion()),
    ]
    exporter = MCCExporter()
    content = exporter.generate(cues)
    # Should still produce valid output with text data
    assert '4280' in content  # 'B' = 0x42
    # Pop-on flow still present
    assert '9420' in content
    assert '942F' in content


def test_mcc_non_ascii_fallback():
    """Verify MCC maps non-ASCII characters to '?' fallback (0x3F80)."""
    from app.models.cue import Cue, CueStyle, CueRegion
    from app.exporters.mcc import MCCExporter

    cues = [
        Cue(start=0, end=1000, text="Café",
            style=CueStyle(), region=CueRegion()),
    ]
    exporter = MCCExporter()
    content = exporter.generate(cues)
    # 'é' is non-ASCII → should map to 3F80
    assert '3F80' in content
    # 'C', 'a', 'f' should be present as normal
    assert '4380' in content  # 'C'
    assert '6180' in content  # 'a'
    assert '6680' in content  # 'f'


# ── Settings-driven export profile tests ─────────────────────────────────────

def test_settings_override_export_profile():
    """Verify that Settings overrides flow through to the export profile."""
    from app.utils.settings import Settings
    from app.validation.premiere_profiles import get_premiere_safe_profile

    # Create settings with custom export defaults
    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_settings.json")
    settings.set("export_font_family", "Courier New")
    settings.set("export_font_size", "80%")
    settings.set("export_fill_color", "#FF0000")
    settings.set("export_text_align", "left")

    profile = get_premiere_safe_profile(settings=settings)
    assert profile.default_style.font_family == "Courier New"
    assert profile.default_style.font_size == "80%"
    assert profile.default_style.fill_color == "#FF0000"
    assert profile.default_style.text_align == "left"


def test_settings_override_none_uses_defaults():
    """Verify that get_premiere_safe_profile without settings uses hardcoded defaults."""
    from app.validation.premiere_profiles import get_premiere_safe_profile

    profile = get_premiere_safe_profile(settings=None)
    assert profile.default_style.font_family == "Arial"
    assert profile.default_style.font_size == "100%"
    assert profile.default_style.fill_color == "#FFFFFF"
    assert profile.default_style.text_align == "center"


def test_settings_flow_through_ttml_export():
    """Verify that settings-configured fill_color appears in TTML output."""
    from app.utils.settings import Settings

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_settings.json")
    settings.set("export_fill_color", "#00FF00")

    captions = [Caption(start_ms=0, end_ms=1000, text="Green text")]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        path = f.name
    try:
        export_ttml(captions, path, settings=settings)
        content = Path(path).read_text(encoding="utf-8")
        assert '#00FF00' in content
    finally:
        os.unlink(path)


def test_settings_flow_through_mcc_export():
    """Verify that settings-configured fill_color produces CEA-608 color code in MCC output."""
    from app.utils.settings import Settings

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_settings.json")
    settings.set("export_fill_color", "#FF0000")  # red

    captions = [Caption(start_ms=0, end_ms=1000, text="Red")]
    with tempfile.NamedTemporaryFile(suffix=".mcc", delete=False, mode="w") as f:
        path = f.name
    try:
        export_mcc(captions, path, settings=settings)
        content = Path(path).read_text(encoding="utf-8")
        # Red color should produce CEA-608 mid-row code 912C
        assert '912C' in content
    finally:
        os.unlink(path)


# ── XML-safety tests for settings-driven TTML exports ────────────────────────

def _make_hostile_settings():
    """Create settings with XML-hostile characters in export fields."""
    from app.utils.settings import Settings
    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_hostile.json")
    settings.set("export_font_family", 'A&B <"C">')
    settings.set("export_font_size", "100%")
    settings.set("export_fill_color", "#FFFFFF")
    settings.set("export_text_align", "center")
    return settings


def test_ttml_parseable_with_hostile_settings():
    """Verify TTML export remains well-formed XML when settings contain &, <, \"."""
    import xml.etree.ElementTree as ET

    settings = _make_hostile_settings()
    captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        path = f.name
    try:
        export_ttml(captions, path, settings=settings)
        content = Path(path).read_text(encoding="utf-8")
        # Must parse as valid XML without exception
        ET.fromstring(content)
        # Escaped value should be present
        assert '&amp;' in content
    finally:
        os.unlink(path)


def test_ebu_tt_parseable_with_hostile_settings():
    """Verify EBU-TT export remains well-formed XML when settings contain &, <, \"."""
    import xml.etree.ElementTree as ET

    settings = _make_hostile_settings()
    captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        path = f.name
    try:
        export_ebu_tt(captions, path, settings=settings)
        content = Path(path).read_text(encoding="utf-8")
        ET.fromstring(content)
        assert '&amp;' in content
    finally:
        os.unlink(path)


def test_smpte_tt_parseable_with_hostile_settings():
    """Verify SMPTE-TT export remains well-formed XML when settings contain &, <, \"."""
    import xml.etree.ElementTree as ET

    settings = _make_hostile_settings()
    captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        path = f.name
    try:
        export_smpte_tt(captions, path, settings=settings)
        content = Path(path).read_text(encoding="utf-8")
        ET.fromstring(content)
        assert '&amp;' in content
    finally:
        os.unlink(path)


# ── Validator unit tests ─────────────────────────────────────────────────────

def test_validate_font_size_valid_values():
    """Verify valid CSS font-size patterns are accepted."""
    from app.validation.export_style_validators import validate_font_size
    assert validate_font_size("100%") == "100%"
    assert validate_font_size("80%") == "80%"
    assert validate_font_size("24px") == "24px"
    assert validate_font_size("12pt") == "12pt"
    assert validate_font_size("1.2em") == "1.2em"
    assert validate_font_size("0.8em") == "0.8em"


def test_validate_font_size_invalid_values():
    """Verify invalid font-size strings fall back to default."""
    from app.validation.export_style_validators import validate_font_size
    assert validate_font_size("definitely-not-a-size") == "100%"
    assert validate_font_size("big") == "100%"
    assert validate_font_size("24") == "100%"  # missing unit
    assert validate_font_size("px24") == "100%"  # wrong order
    assert validate_font_size("") == "100%"


def test_validate_fill_color_valid_values():
    """Verify valid hex color patterns are accepted and uppercased."""
    from app.validation.export_style_validators import validate_fill_color
    assert validate_fill_color("#FFFFFF") == "#FFFFFF"
    assert validate_fill_color("#ff0000") == "#FF0000"
    assert validate_fill_color("#00FF00AA") == "#00FF00AA"


def test_validate_fill_color_invalid_values():
    """Verify invalid color strings fall back to default."""
    from app.validation.export_style_validators import validate_fill_color
    assert validate_fill_color("not-a-color") == "#FFFFFF"
    assert validate_fill_color("red") == "#FFFFFF"
    assert validate_fill_color("#GGG") == "#FFFFFF"
    assert validate_fill_color("#12345") == "#FFFFFF"  # wrong length
    assert validate_fill_color("") == "#FFFFFF"


def test_invalid_settings_normalized_in_ttml_export():
    """Verify TTML export normalizes invalid settings instead of writing them through."""
    import xml.etree.ElementTree as ET
    from app.utils.settings import Settings

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_invalid.json")
    settings.set("export_font_size", "definitely-not-a-size")
    settings.set("export_fill_color", "not-a-color")

    captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        path = f.name
    try:
        export_ttml(captions, path, settings=settings)
        content = Path(path).read_text(encoding="utf-8")
        # Must parse as valid XML
        ET.fromstring(content)
        # Invalid values should NOT appear in output
        assert 'definitely-not-a-size' not in content
        assert 'not-a-color' not in content
        # Defaults should appear instead
        assert '100%' in content    # default font size
        assert '#FFFFFF' in content  # default fill color
    finally:
        os.unlink(path)


def test_invalid_settings_normalized_in_profile():
    """Verify the profile factory normalizes invalid settings directly."""
    from app.utils.settings import Settings
    from app.validation.premiere_profiles import get_premiere_safe_profile

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_bad_profile.json")
    settings.set("export_font_size", "banana")
    settings.set("export_fill_color", "xyz")

    profile = get_premiere_safe_profile(settings=settings)
    assert profile.default_style.font_size == "100%"
    assert profile.default_style.fill_color == "#FFFFFF"


# ── Background color settings tests ─────────────────────────────────────────

def test_background_color_flows_through_ttml_export():
    """Verify configured background_color appears in TTML output."""
    from app.utils.settings import Settings

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_bg.json")
    settings.set("export_background_color", "#000000CC")

    captions = [Caption(start_ms=0, end_ms=1000, text="BG test")]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        path = f.name
    try:
        export_ttml(captions, path, settings=settings)
        content = Path(path).read_text(encoding="utf-8")
        assert '#000000CC' in content
    finally:
        os.unlink(path)


def test_background_color_default_is_transparent():
    """Verify default background_color is transparent when no setting is configured."""
    from app.utils.settings import Settings
    from app.validation.premiere_profiles import get_premiere_safe_profile

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_bg_default.json")
    profile = get_premiere_safe_profile(settings=settings)
    assert profile.default_style.background_color == "#00000000"


def test_invalid_background_color_normalized_in_profile():
    """Verify invalid background_color is normalized to transparent default in profile factory."""
    from app.utils.settings import Settings
    from app.validation.premiere_profiles import get_premiere_safe_profile

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_bad_bg.json")
    settings.set("export_background_color", "not-a-color")

    profile = get_premiere_safe_profile(settings=settings)
    assert profile.default_style.background_color == "#00000000"  # transparent default


def test_invalid_background_color_not_in_ttml_output():
    """Verify invalid background_color does not appear raw in TTML output."""
    import xml.etree.ElementTree as ET
    from app.utils.settings import Settings

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_bad_bg_ttml.json")
    settings.set("export_background_color", "garbage")

    captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        path = f.name
    try:
        export_ttml(captions, path, settings=settings)
        content = Path(path).read_text(encoding="utf-8")
        ET.fromstring(content)  # must parse
        assert 'garbage' not in content
        assert '#00000000' in content  # transparent fallback
    finally:
        os.unlink(path)


# ── Background color validator unit tests ────────────────────────────────────

def test_validate_background_color_valid_values():
    """Verify valid hex colors are accepted by validate_background_color."""
    from app.validation.export_style_validators import validate_background_color
    assert validate_background_color("#00000000") == "#00000000"
    assert validate_background_color("#000000CC") == "#000000CC"
    assert validate_background_color("#ff0000") == "#FF0000"
    assert validate_background_color("#FFFFFF") == "#FFFFFF"


def test_validate_background_color_invalid_falls_back_to_transparent():
    """Verify invalid values fall back to transparent #00000000."""
    from app.validation.export_style_validators import validate_background_color
    assert validate_background_color("not-a-color") == "#00000000"
    assert validate_background_color("red") == "#00000000"
    assert validate_background_color("") == "#00000000"
    assert validate_background_color("#GGG") == "#00000000"


def test_validate_fill_color_still_defaults_to_white():
    """Verify fill color validator still defaults to white (not transparent)."""
    from app.validation.export_style_validators import validate_fill_color
    assert validate_fill_color("not-a-color") == "#FFFFFF"
    assert validate_fill_color("") == "#FFFFFF"


# ── Region placement validator tests ─────────────────────────────────────────

def test_validate_region_origin_valid():
    """Verify valid origin patterns are accepted."""
    from app.validation.export_style_validators import validate_region_origin
    assert validate_region_origin("10% 80%") == "10% 80%"
    assert validate_region_origin("0% 0%") == "0% 0%"
    assert validate_region_origin("5.5% 85%") == "5.5% 85%"
    assert validate_region_origin("100% 100%") == "100% 100%"


def test_validate_region_origin_invalid():
    """Verify invalid origin strings fall back to default."""
    from app.validation.export_style_validators import validate_region_origin
    assert validate_region_origin("bad") == "10% 80%"
    assert validate_region_origin("10 80") == "10% 80%"  # missing %
    assert validate_region_origin("10%") == "10% 80%"    # single value
    assert validate_region_origin("") == "10% 80%"


def test_validate_region_extent_valid():
    """Verify valid extent patterns are accepted."""
    from app.validation.export_style_validators import validate_region_extent
    assert validate_region_extent("80% 15%") == "80% 15%"
    assert validate_region_extent("100% 100%") == "100% 100%"
    assert validate_region_extent("50.5% 20%") == "50.5% 20%"


def test_validate_region_extent_invalid():
    """Verify invalid extent strings fall back to default."""
    from app.validation.export_style_validators import validate_region_extent
    assert validate_region_extent("bad") == "80% 15%"
    assert validate_region_extent("80px 15px") == "80% 15%"
    assert validate_region_extent("") == "80% 15%"


def test_region_placement_flows_through_profile():
    """Verify configured placement appears in the export profile."""
    from app.utils.settings import Settings
    from app.validation.premiere_profiles import get_premiere_safe_profile

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_placement.json")
    settings.set("export_region_origin", "5% 70%")
    settings.set("export_region_extent", "90% 25%")

    profile = get_premiere_safe_profile(settings=settings)
    assert profile.default_region.origin == "5% 70%"
    assert profile.default_region.extent == "90% 25%"


def test_invalid_region_placement_normalized_in_profile():
    """Verify invalid placement values are normalized to defaults."""
    from app.utils.settings import Settings
    from app.validation.premiere_profiles import get_premiere_safe_profile

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_bad_placement.json")
    settings.set("export_region_origin", "garbage")
    settings.set("export_region_extent", "nonsense")

    profile = get_premiere_safe_profile(settings=settings)
    assert profile.default_region.origin == "10% 80%"
    assert profile.default_region.extent == "80% 15%"


def test_region_placement_in_ttml_output():
    """Verify configured region placement appears in TTML XML output."""
    import xml.etree.ElementTree as ET
    from app.utils.settings import Settings

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_placement_ttml.json")
    settings.set("export_region_origin", "5% 70%")
    settings.set("export_region_extent", "90% 25%")

    captions = [Caption(start_ms=0, end_ms=1000, text="Placed")]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        path = f.name
    try:
        export_ttml(captions, path, settings=settings)
        content = Path(path).read_text(encoding="utf-8")
        ET.fromstring(content)  # must parse
        assert '5% 70%' in content
        assert '90% 25%' in content
    finally:
        os.unlink(path)


def test_invalid_region_placement_not_in_ttml_output():
    """Verify invalid placement does not appear raw in TTML output."""
    import xml.etree.ElementTree as ET
    from app.utils.settings import Settings

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_bad_place_ttml.json")
    settings.set("export_region_origin", "garbage")

    captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        path = f.name
    try:
        export_ttml(captions, path, settings=settings)
        content = Path(path).read_text(encoding="utf-8")
        ET.fromstring(content)
        assert 'garbage' not in content
        assert '10% 80%' in content  # default origin
    finally:
        os.unlink(path)


# ── Out-of-range region placement tests ──────────────────────────────────────

def test_validate_region_origin_out_of_range():
    """Verify out-of-range origin values are normalized to defaults."""
    from app.validation.export_style_validators import validate_region_origin
    assert validate_region_origin("999% 999%") == "10% 80%"
    assert validate_region_origin("101% 50%") == "10% 80%"
    assert validate_region_origin("50% 101%") == "10% 80%"
    assert validate_region_origin("150% 200%") == "10% 80%"


def test_validate_region_extent_out_of_range():
    """Verify out-of-range extent values are normalized to defaults."""
    from app.validation.export_style_validators import validate_region_extent
    assert validate_region_extent("500% 250%") == "80% 15%"
    assert validate_region_extent("101% 15%") == "80% 15%"
    assert validate_region_extent("80% 101%") == "80% 15%"


def test_validate_region_boundary_values():
    """Verify boundary values 0% and 100% are accepted."""
    from app.validation.export_style_validators import validate_region_origin, validate_region_extent
    assert validate_region_origin("0% 0%") == "0% 0%"
    assert validate_region_origin("100% 100%") == "100% 100%"
    assert validate_region_extent("0% 0%") == "0% 0%"
    assert validate_region_extent("100% 100%") == "100% 100%"


def test_out_of_range_origin_normalized_in_profile():
    """Verify profile factory normalizes out-of-range origin to default."""
    from app.utils.settings import Settings
    from app.validation.premiere_profiles import get_premiere_safe_profile

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_oor_origin.json")
    settings.set("export_region_origin", "999% 999%")

    profile = get_premiere_safe_profile(settings=settings)
    assert profile.default_region.origin == "10% 80%"


def test_out_of_range_extent_normalized_in_profile():
    """Verify profile factory normalizes out-of-range extent to default."""
    from app.utils.settings import Settings
    from app.validation.premiere_profiles import get_premiere_safe_profile

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_oor_extent.json")
    settings.set("export_region_extent", "500% 250%")

    profile = get_premiere_safe_profile(settings=settings)
    assert profile.default_region.extent == "80% 15%"


def test_out_of_range_origin_not_in_ttml_output():
    """Verify out-of-range origin does not appear in TTML export output."""
    import xml.etree.ElementTree as ET
    from app.utils.settings import Settings

    settings = Settings(settings_file=Path(tempfile.mkdtemp()) / "test_oor_ttml.json")
    settings.set("export_region_origin", "999% 999%")

    captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        path = f.name
    try:
        export_ttml(captions, path, settings=settings)
        content = Path(path).read_text(encoding="utf-8")
        ET.fromstring(content)
        assert '999%' not in content
        assert '10% 80%' in content  # default origin
    finally:
        os.unlink(path)
