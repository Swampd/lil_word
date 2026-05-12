"""Timecode formatting utilities for SRT and ASS formats."""


def ms_to_srt_time(ms: int) -> str:
    """Convert milliseconds to SRT time format HH:MM:SS,mmm"""
    if ms < 0:
        ms = 0
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1_000
    millis = ms % 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def ms_to_ass_time(ms: int) -> str:
    """Convert milliseconds to ASS time format H:MM:SS.cc (centiseconds)."""
    if ms < 0:
        ms = 0
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1_000
    centis = (ms % 1_000) // 10
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def srt_time_to_ms(s: str) -> int:
    """Parse SRT time string HH:MM:SS,mmm to ms."""
    s = s.strip()
    parts = s.replace(",", ":").split(":")
    h, m, sec, millis = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return h * 3_600_000 + m * 60_000 + sec * 1_000 + millis


def ms_to_display(ms: int) -> str:
    """Convert ms to a simple MM:SS.m display string."""
    if ms < 0:
        ms = 0
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1_000
    tenths = (ms % 1_000) // 100
    return f"{minutes:02d}:{seconds:02d}.{tenths}"
