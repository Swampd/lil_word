"""Acceptance smoke test – generates a synthetic MP4 and runs the full pipeline.

Uses a workspace-local temp directory to avoid permission issues with the
system temp directory. Requires ffmpeg on PATH. Tests are skipped cleanly
if ffmpeg is unavailable or cannot write to the test directory.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models.caption import Caption
from app.services import media_service
from app.services.caption_engine import normalize_captions
from app.services.export_service import export_srt, export_ass, export_burned_video
from app.utils.export_helpers import build_audio_output_path

# ── Workspace-local test directory ───────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEST_TMP = _REPO_ROOT / ".test_tmp"


def _ensure_test_dir() -> Path:
    """Create and return a writable workspace-local temp directory."""
    _TEST_TMP.mkdir(exist_ok=True)
    return _TEST_TMP


def _ffmpeg_can_write() -> bool:
    """Check that ffmpeg is available AND can write a synthetic file to our test dir."""
    try:
        si = None
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, startupinfo=si, check=True,
        )
        # Try a minimal synthetic write
        test_dir = _ensure_test_dir()
        probe_path = str(test_dir / "_ffmpeg_probe.mp4")
        result = subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "nullsrc=s=2x2:d=0.1",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-frames:v", "1", probe_path,
        ], capture_output=True, startupinfo=si)
        if result.returncode == 0 and Path(probe_path).exists():
            Path(probe_path).unlink(missing_ok=True)
            return True
        return False
    except Exception:
        return False


_FFMPEG_OK = _ffmpeg_can_write()
skip_no_ffmpeg = pytest.mark.skipif(
    not _FFMPEG_OK,
    reason="ffmpeg not available or cannot write to test directory",
)


def _generate_synthetic_mp4(path: str, duration_s: float = 5.0):
    """Generate a synthetic MP4 with test pattern and sine wave audio."""
    si = None
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration_s}:size=320x240:rate=24",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_s}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "64k",
        "-shortest", str(path),
    ], capture_output=True, startupinfo=si, check=True)


def _generate_synthetic_mp3(path: str, duration_s: float = 5.0):
    """Generate a synthetic MP3 with sine wave audio."""
    si = None
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_s}",
        "-c:a", "libmp3lame", "-b:a", "64k",
        str(path),
    ], capture_output=True, startupinfo=si, check=True)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _test_workspace():
    """Ensure workspace-local test dir exists; clean up individual test files after."""
    test_dir = _ensure_test_dir()
    yield test_dir
    # Files are cleaned up per-test below; dir persists for speed


@pytest.fixture
def test_mp4():
    """Provide a 5-second synthetic MP4 in the workspace-local test dir."""
    test_dir = _ensure_test_dir()
    mp4_path = str(test_dir / "test_input.mp4")
    _generate_synthetic_mp4(mp4_path, 5.0)
    yield mp4_path
    Path(mp4_path).unlink(missing_ok=True)


# ── Tests ────────────────────────────────────────────────────────────────────

@skip_no_ffmpeg
def test_import_extract_audio():
    """Verify audio extraction produces mono 16kHz WAV."""
    test_dir = _ensure_test_dir()
    mp4 = str(test_dir / "extract_test.mp4")
    wav = str(test_dir / "extract_audio_16k.wav")
    try:
        _generate_synthetic_mp4(mp4, 3.0)
        media_service.extract_audio_wav(mp4, wav)
        assert Path(wav).exists()
        assert Path(wav).stat().st_size > 0

        import wave
        with wave.open(wav, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 16000
    finally:
        Path(mp4).unlink(missing_ok=True)
        Path(wav).unlink(missing_ok=True)


@skip_no_ffmpeg
def test_probe_duration():
    """Verify ffprobe returns correct duration."""
    test_dir = _ensure_test_dir()
    mp4 = str(test_dir / "probe_test.mp4")
    try:
        _generate_synthetic_mp4(mp4, 5.0)
        dur_ms = media_service.get_duration_ms(mp4)
        assert 4500 <= dur_ms <= 5500
    finally:
        Path(mp4).unlink(missing_ok=True)


@skip_no_ffmpeg
def test_srt_export_end_to_end():
    """Generate synthetic captions and export to SRT."""
    test_dir = _ensure_test_dir()
    srt_path = str(test_dir / "test_export.srt")
    try:
        captions = [
            Caption(start_ms=0, end_ms=2000, text="Hello world"),
            Caption(start_ms=2500, end_ms=4500, text="Test caption"),
        ]
        export_srt(captions, srt_path)
        content = Path(srt_path).read_text(encoding="utf-8")
        assert "Hello world" in content
        assert "Test caption" in content
    finally:
        Path(srt_path).unlink(missing_ok=True)


@skip_no_ffmpeg
def test_ass_export_end_to_end():
    """Generate synthetic captions and export to ASS."""
    test_dir = _ensure_test_dir()
    ass_path = str(test_dir / "test_export.ass")
    try:
        captions = [
            Caption(start_ms=0, end_ms=2000, text="Hello world"),
            Caption(start_ms=2500, end_ms=4500, text="Test caption"),
        ]
        export_ass(captions, ass_path)
        content = Path(ass_path).read_text(encoding="utf-8")
        assert "Dialogue:" in content
    finally:
        Path(ass_path).unlink(missing_ok=True)


@skip_no_ffmpeg
def test_burned_video_export():
    """Generate synthetic MP4, burn subtitles, verify output exists and plays."""
    test_dir = _ensure_test_dir()
    mp4_in = str(test_dir / "burn_input.mp4")
    mp4_out = str(test_dir / "burn_output.mp4")
    try:
        _generate_synthetic_mp4(mp4_in, 5.0)
        captions = [
            Caption(start_ms=500, end_ms=2000, text="Burned subtitle"),
            Caption(start_ms=2500, end_ms=4500, text="Second subtitle"),
        ]
        export_burned_video(mp4_in, captions, mp4_out)
        assert Path(mp4_out).exists()
        assert Path(mp4_out).stat().st_size > 0

        dur = media_service.get_duration_ms(mp4_out)
        assert dur > 0
    finally:
        Path(mp4_in).unlink(missing_ok=True)
        Path(mp4_out).unlink(missing_ok=True)


@skip_no_ffmpeg
def test_captions_within_media_duration():
    """Verify normalized captions all stay within media duration."""
    test_dir = _ensure_test_dir()
    mp4 = str(test_dir / "clamp_test.mp4")
    try:
        _generate_synthetic_mp4(mp4, 5.0)
        dur_ms = media_service.get_duration_ms(mp4)

        captions = [
            Caption(start_ms=0, end_ms=2000, text="First"),
            Caption(start_ms=2000, end_ms=4000, text="Second"),
            Caption(start_ms=4000, end_ms=7000, text="Third – past end"),
        ]
        result = normalize_captions(captions, media_duration_ms=dur_ms)

        for cap in result:
            assert cap.end_ms <= dur_ms
            assert cap.end_ms > cap.start_ms
    finally:
        Path(mp4).unlink(missing_ok=True)


# ── Audio path collision test ────────────────────────────────────────────────

def test_audio_output_path_unique():
    """Two calls to build_audio_output_path should produce different paths."""
    p1 = build_audio_output_path("video", "/tmp/work")
    p2 = build_audio_output_path("video", "/tmp/work")
    assert p1 != p2
    assert "video" in p1
    assert "_audio_16k.wav" in p1


def test_audio_output_path_contains_stem():
    """Audio output path should contain the media stem."""
    path = build_audio_output_path("my_clip", "/some/dir")
    assert "my_clip" in path
    assert path.endswith("_audio_16k.wav")


def test_ass_export_libass_brace_escaping_contract():
    """Verify ASS export uses libass-specific structural escapes (\\{ and \\}) to neutralize user syntax while supporting libass-compatible renderers."""
    test_dir = _ensure_test_dir()
    ass_path = str(test_dir / "test_escaping.ass")
    try:
        # A user types ASS control syntax and a literal backslash before an N
        captions = [
            Caption(start_ms=0, end_ms=2000, text=r"User text {\an8} and a \N here")
        ]
        export_ass(captions, ass_path)
        content = Path(ass_path).read_text(encoding="utf-8")
        # Should contain structural ASS brace escapes and a zero-width space after the backslash
        # The Python string literal "\\{\\\u200Ban8\\}" yields EXACTLY the characters: \{ \ \u200B a n 8 \}
        assert "\\{\\\u200Ban8\\}" in content
        assert "a \\\u200BN here" in content
        # Ensure the genuine newline conversion hasn't broken
        captions_newline = [Caption(start_ms=0, end_ms=1000, text="Line 1\nLine 2")]
        export_ass(captions_newline, ass_path)
        content2 = Path(ass_path).read_text(encoding="utf-8")
        assert "Line 1\\NLine 2" in content2
    finally:
        Path(ass_path).unlink(missing_ok=True)


def test_burned_video_windows_path_escaping():
    """Verify double-escaping behavior for FFMPEG subtitles filter."""
    from unittest.mock import patch
    import os
    
    test_dir = _ensure_test_dir()
    mp4_in = str(test_dir / "burn_input_escape.mp4")
    mp4_out = str(test_dir / "burn_output_escape.mp4")
    
    # Path with colon, space, and single quote
    dummy_ass_path = r"C:\My 'Test'\Path.ass"
    
    # Use patch to intercept the _run call without actually invoking FFMPEG
    with patch("app.services.media_service._run") as mock_run:
        # burn_subtitles requires an ASS file, but we mock the run so we don't need it to actually exist for FFMPEG,
        # but wait, the burn_subtitles function doesn't check for file existence before calling _run.
        media_service.burn_subtitles(mp4_in, dummy_ass_path, mp4_out)
        
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        
        # Find the -vf argument
        vf_idx = args.index("-vf")
        vf_arg = args[vf_idx + 1]
        
        # Expected double-escaped path:
        # C:\My 'Test'\Path.ass
        # Level 1 (normalize): C:/My 'Test'/Path.ass
        # Level 2 (escape : = ' \): C\:/My \'Test\'/Path.ass
        # Level 3 (escape , ; \ ' [ ]): C\\:/My \\\'Test\\\'/Path.ass
        expected_safe_ass = r"C\\:/My \\\'Test\\\'/Path.ass"
        assert vf_arg == f"subtitles={expected_safe_ass}"

