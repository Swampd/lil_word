"""Tests for caption engine – overlap guarantee, media boundary, and normalizer."""

from unittest.mock import patch, MagicMock
from app.models.caption import Caption, TranscriptWord
from app.services.caption_engine import generate_captions, normalize_captions
from app.ui.main_window import MainWindow
from app.utils.settings import Settings
from app.services.project_service import ProjectService
from PySide6.QtWidgets import QMessageBox, QApplication


def _make_dense_words(count: int = 20, word_dur_ms: int = 200) -> list[TranscriptWord]:
    """Create densely packed word timestamps to stress-test overlap prevention."""
    words = []
    t = 0
    for i in range(count):
        words.append(TranscriptWord(
            start_ms=t,
            end_ms=t + word_dur_ms,
            text=f"word{i}",
            confidence=0.95,
            idx=i,
        ))
        t += word_dur_ms + 10  # tiny 10ms gap between words
    return words


def _make_normal_words() -> list[TranscriptWord]:
    """Create normally spaced words."""
    texts = ["Hello", "this", "is", "a", "test", "of", "the", "caption", "system."]
    words = []
    t = 500
    for i, txt in enumerate(texts):
        dur = len(txt) * 80
        words.append(TranscriptWord(
            start_ms=t, end_ms=t + dur, text=txt, confidence=0.9, idx=i,
        ))
        t += dur + 200
    return words


def _assert_no_overlaps(captions: list[Caption]):
    """Assert that no two adjacent captions overlap."""
    for i in range(len(captions) - 1):
        assert captions[i].end_ms <= captions[i + 1].start_ms, (
            f"Overlap at index {i}: caption {i} ends at {captions[i].end_ms}, "
            f"caption {i+1} starts at {captions[i+1].start_ms}"
        )


def _assert_sorted(captions: list[Caption]):
    """Assert captions are sorted by start time."""
    for i in range(len(captions) - 1):
        assert captions[i].start_ms <= captions[i + 1].start_ms


def _assert_within_duration(captions: list[Caption], duration_ms: int):
    """Assert all captions end within media duration."""
    for i, cap in enumerate(captions):
        assert cap.end_ms <= duration_ms, (
            f"Caption {i} ends at {cap.end_ms}, media duration is {duration_ms}"
        )


def _assert_no_zero_duration(captions: list[Caption]):
    """Assert no caption has zero or negative duration."""
    for i, cap in enumerate(captions):
        assert cap.end_ms > cap.start_ms, (
            f"Caption {i} has zero/negative duration: "
            f"start={cap.start_ms}, end={cap.end_ms}"
        )


# ── Generation tests ─────────────────────────────────────────────────────────

def test_generate_from_dense_words_no_overlaps():
    words = _make_dense_words(30, 150)
    captions = generate_captions([], words, min_dur=700, min_gap=80)
    assert len(captions) > 0
    _assert_sorted(captions)
    _assert_no_overlaps(captions)
    _assert_no_zero_duration(captions)


def test_generate_from_normal_words_no_overlaps():
    words = _make_normal_words()
    captions = generate_captions([], words)
    assert len(captions) > 0
    _assert_sorted(captions)
    _assert_no_overlaps(captions)
    _assert_no_zero_duration(captions)


def test_generate_from_segments_no_overlaps():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello world this is a test."},
        {"start": 2.1, "end": 4.5, "text": "Another segment with more words here."},
        {"start": 4.6, "end": 7.0, "text": "Final segment of the transcription."},
    ]
    captions = generate_captions(segments, [])
    assert len(captions) > 0
    _assert_sorted(captions)
    _assert_no_overlaps(captions)
    _assert_no_zero_duration(captions)


def test_media_duration_clamping():
    words = _make_normal_words()
    media_dur = 3000  # 3 seconds – shorter than total word span
    captions = generate_captions([], words, media_duration_ms=media_dur)
    _assert_within_duration(captions, media_dur)
    _assert_no_overlaps(captions)
    _assert_no_zero_duration(captions)


# ── Normalizer tests ─────────────────────────────────────────────────────────

def test_normalize_captions_no_overlaps():
    """Manually created overlapping captions should be fixed by normalizer."""
    captions = [
        Caption(start_ms=0, end_ms=700, text="First"),
        Caption(start_ms=590, end_ms=1290, text="Second"),
        Caption(start_ms=1085, end_ms=1785, text="Third"),
    ]
    result = normalize_captions(captions)
    _assert_sorted(result)
    _assert_no_overlaps(result)
    _assert_no_zero_duration(result)


def test_normalize_with_media_duration():
    captions = [
        Caption(start_ms=0, end_ms=2000, text="First"),
        Caption(start_ms=2100, end_ms=5000, text="Second"),
    ]
    result = normalize_captions(captions, media_duration_ms=3000)
    _assert_no_overlaps(result)
    _assert_within_duration(result, 3000)
    _assert_no_zero_duration(result)


def test_negative_start_clamped():
    captions = [Caption(start_ms=-200, end_ms=500, text="Test")]
    result = normalize_captions(captions)
    assert result[0].start_ms >= 0


def test_empty_captions():
    assert normalize_captions([]) == []


# ── Zero-duration / media boundary tests ─────────────────────────────────────

def test_caption_entirely_after_media_dropped():
    """A caption entirely after media duration should be dropped or merged."""
    captions = [Caption(start_ms=4000, end_ms=5000, text="after")]
    result = normalize_captions(captions, media_duration_ms=3000)
    # Should either be empty or have no zero-duration
    for cap in result:
        assert cap.end_ms > cap.start_ms


def test_caption_straddling_media_end_clamped():
    """A caption that straddles the media end should be clamped, not zero-duration."""
    captions = [Caption(start_ms=2500, end_ms=4000, text="straddle")]
    result = normalize_captions(captions, media_duration_ms=3000)
    assert len(result) == 1
    assert result[0].end_ms == 3000
    assert result[0].end_ms > result[0].start_ms


def test_multiple_captions_at_media_boundary():
    """Multiple captions clamped at the same media boundary should not produce zero-duration."""
    captions = [
        Caption(start_ms=0, end_ms=1500, text="First"),
        Caption(start_ms=1500, end_ms=3000, text="Second"),
        Caption(start_ms=3000, end_ms=4500, text="Third – after"),
        Caption(start_ms=4500, end_ms=6000, text="Fourth – after"),
    ]
    result = normalize_captions(captions, media_duration_ms=3000)
    _assert_no_overlaps(result)
    _assert_within_duration(result, 3000)
    _assert_no_zero_duration(result)


def test_single_caption_entirely_after_media_returns_empty_or_valid():
    """Repro from review: normalize_captions([Caption(4000, 5000, 'after')], media_duration_ms=3000)
    must NOT return (3000, 3000) zero-duration."""
    result = normalize_captions(
        [Caption(start_ms=4000, end_ms=5000, text="after")],
        media_duration_ms=3000,
    )
    for cap in result:
        assert cap.end_ms > cap.start_ms, (
            f"Zero-duration caption: start={cap.start_ms}, end={cap.end_ms}"
        )


def test_max_chars_per_line():
    """Verify max_chars_per_line wraps text correctly."""
    words = [
        TranscriptWord(start_ms=0, end_ms=200, text="This", confidence=1, idx=0),
        TranscriptWord(start_ms=200, end_ms=400, text="is", confidence=1, idx=1),
        TranscriptWord(start_ms=400, end_ms=600, text="a", confidence=1, idx=2),
        TranscriptWord(start_ms=600, end_ms=800, text="sentence", confidence=1, idx=3),
    ]
    # "This is a sentence" is 18 chars.
    # max_cpl=10 forces a wrap.
    caps_small = generate_captions([], words, max_cpl=10, target_cps_max=100)
    assert "\n" in caps_small[0].text

    # max_cpl=100 keeps it on one line if max_lines allows
    caps_large = generate_captions([], words, max_cpl=100, target_cps_max=100)
    assert "\n" not in caps_large[0].text


def test_max_lines():
    """Verify max_lines forces splitting into separate captions."""
    words = [
        TranscriptWord(start_ms=0, end_ms=200, text="One.", confidence=1, idx=0),
        TranscriptWord(start_ms=200, end_ms=400, text="Two.", confidence=1, idx=1),
        TranscriptWord(start_ms=400, end_ms=600, text="Three.", confidence=1, idx=2),
    ]
    # text is "One. Two. Three." (16 chars)
    # If max_cpl=6, it counts as 16//6 + 1 = 3 lines.
    
    # If max_lines=2, it flushes before "Three." and makes 2 captions.
    caps_small = generate_captions([], words, max_lines=2, max_cpl=6)
    assert len(caps_small) == 2
    
    # If max_lines=3, it can fit it all in 1 caption.
    caps_large = generate_captions([], words, max_lines=3, max_cpl=6)
    assert len(caps_large) == 1

def test_target_cps_splitting():
    """Verify target_cps_min forces early split if duration makes density too low."""
    # To avoid the new 400ms explicit pause rule, keep the gap at 300ms.
    # Stretch Word2 to drop the overall CPS.
    words = [
        TranscriptWord(start_ms=0, end_ms=500, text="Word1", confidence=1, idx=0),
        TranscriptWord(start_ms=800, end_ms=2500, text="Word2", confidence=1, idx=1),
    ]
    # "Word1 Word2" is 11 chars. Total duration = 2500ms = 2.5s.
    # CPS = 11 / 2.5 = 4.4 chars/sec.
    
    # We set max_cpl=5 to allow the CPS split heuristic to trigger, since
    # len("Word1")=5, which > 5 * 0.7.
    
    # If target_cps_min = 2, we tolerate 4.4 cps, no flush.
    caps_tolerate = generate_captions([], words, target_cps_min=2, max_cpl=5, max_lines=4)
    assert len(caps_tolerate) == 1
    
    # If target_cps_min = 10, 4.4 is too low, forces flush before Word2
    caps_split = generate_captions([], words, target_cps_min=10, max_cpl=5, max_lines=4)
    assert len(caps_split) == 2
    
    # Ensure no overlaps were introduced
    for i in range(len(caps_split) - 1):
        assert caps_split[i].end_ms <= caps_split[i+1].start_ms


def test_segment_cps_fallback_splits():
    """Verify segment generation falls back to splitting when CPS bounds are broken."""
    # A single overly dense 2s segment. 84 chars over 2 seconds = 42 chars/sec
    segments = [
        {"start": 0.0, "end": 2.0, "text": "This is a rapidly spoken wall of text designed to force the segment parser to split."},
    ]
    
    # If target_cps_max is 50, 42 cps passes. It should emit 1 caption.
    caps_pass = generate_captions(segments, [], target_cps_max=50, max_lines=4, max_dur=5000, max_cpl=100)
    assert len(caps_pass) == 1
    
    # If target_cps_max is 20, 42 cps is a violation. It should manually chunk it proportionally.
    caps_split = generate_captions(segments, [], target_cps_max=20, max_lines=4, max_dur=5000, max_cpl=100)
    assert len(caps_split) > 1

def test_segment_slow_capping():
    """Verify segment generation truncates end_ms when reading speed drops below target_cps_min."""
    segments = [
        {"start": 0.0, "end": 10.0, "text": "Hello."},
    ]
    # "Hello." is 6 chars. Over 10 seconds, CPS is 0.6. 
    # If target is 10 cps, the ideal duration is 6 / 10 = 0.6 seconds (600ms).
    # Since min_dur=700 defaults, it should cap to 700ms.
    
    caps = generate_captions(segments, [], target_cps_min=10, min_dur=700, max_dur=15000)
    dur = caps[0].end_ms - caps[0].start_ms
    
    # New defaults: lead_in = 150, lead_out = 250
    # start_ms = max(0, 0 - 150) = 0, end_ms = 700 + 250 = 950
    assert dur == 950


@patch("app.services.caption_job.caption_engine.generate_captions")
@patch("app.ui.main_window.QMessageBox.warning")
def test_mainwindow_passes_caption_rules(mock_warning, mock_generate):
    """Verify MainWindow uses settings values during _reflow_captions."""
    app = QApplication.instance()
    if not app:
        app = QApplication([])

    mock_warning.return_value = QMessageBox.Yes
    
    from pathlib import Path
    settings = Settings(Path(".test_tmp/test_mainwindow_settings.json"))
    # Inject deterministic mock settings
    settings.set("max_lines", 3)
    settings.set("max_chars_per_line", 35)
    settings.set("min_caption_ms", 850)
    
    db_mock = MagicMock(spec=ProjectService)
    window = MainWindow(settings, db_mock)
    
    try:
        # Mock some basic state to allow reflow
        window._words = [TranscriptWord(0, 1000, "Mock", 1.0, 0)]
        
        window._reflow_captions()
        
        mock_generate.assert_called_once()
        kwargs = mock_generate.call_args.kwargs
        assert kwargs.get("max_lines") == 3
        assert kwargs.get("max_cpl") == 35
        assert kwargs.get("min_dur") == 850
    finally:
        window.deleteLater()
        app.processEvents()

@patch("app.ui.main_window.normalize_captions")
def test_mainwindow_normalizer_uses_defaults(mock_normalize):
    """Verify MainWindow uses the tuned 100ms gap fallback for normalization."""
    app = QApplication.instance()
    if not app:
        app = QApplication([])
        
    from pathlib import Path
    # Use empty settings to force fallback
    settings_file = Path(".test_tmp/test_normalizer_settings.json")
    if settings_file.exists():
        settings_file.unlink()
    settings = Settings(settings_file)
    
    db_mock = MagicMock(spec=ProjectService)
    window = MainWindow(settings, db_mock)
    
    try:
        window._captions = []
        window._normalize_current_captions()
        
        mock_normalize.assert_called_once()
        kwargs = mock_normalize.call_args.kwargs
        assert kwargs.get("min_gap") == 100
        assert kwargs.get("min_dur") == 700
    finally:
        window.deleteLater()
        app.processEvents()
