"""Tests for timecode utilities."""

from app.utils.timecode import ms_to_srt_time, ms_to_ass_time, srt_time_to_ms, ms_to_display


def test_ms_to_srt_zero():
    assert ms_to_srt_time(0) == "00:00:00,000"


def test_ms_to_srt_typical():
    assert ms_to_srt_time(3661234) == "01:01:01,234"


def test_ms_to_srt_negative_clamps():
    assert ms_to_srt_time(-100) == "00:00:00,000"


def test_ms_to_ass_time_typical():
    assert ms_to_ass_time(3661230) == "1:01:01.23"


def test_ms_to_ass_time_zero():
    assert ms_to_ass_time(0) == "0:00:00.00"


def test_srt_roundtrip():
    for ms in [0, 500, 1000, 12345, 3661234]:
        srt = ms_to_srt_time(ms)
        back = srt_time_to_ms(srt)
        assert back == ms, f"Roundtrip failed for {ms}: {srt} -> {back}"


def test_display_format():
    assert ms_to_display(0) == "00:00.0"
    assert ms_to_display(62500) == "01:02.5"
