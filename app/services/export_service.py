"""Export helpers – SRT, ASS, and burned-in video export."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Callable

from app.models.caption import Caption
from app.utils.timecode import ms_to_srt_time, ms_to_ass_time
from app.services import media_service


def _coerce_export_fps(value, default: int) -> int:
    """Resolve a positive integer frame rate from untrusted input."""
    try:
        fps = int(value)
    except (TypeError, ValueError):
        return default
    return fps if fps > 0 else default


def export_srt(captions: list[Caption], out_path: str) -> str:
    """Write captions to an SRT file."""
    lines: list[str] = []
    for i, cap in enumerate(captions, 1):
        lines.append(str(i))
        lines.append(f"{ms_to_srt_time(cap.start_ms)} --> {ms_to_srt_time(cap.end_ms)}")
        lines.append(cap.text)
        lines.append("")
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    return out_path


def export_ass(captions: list[Caption], out_path: str) -> str:
    r"""
    Export captions to Advanced SubStation Alpha format (.ass).

    WARNING: This export applies `\{` and `\}` escape sequences to user text
    to neutralize override tags while maintaining literal brace fidelity.
    These structural escapes are specific to libass (used by our FFMPEG burned video
    pipeline, VLC, mpv, etc.). Legacy ASS renderers like VSFilter may visually display
    the backslash. This is an explicit support boundary: literal brace fidelity
    is guaranteed only for libass-compatible consumers.
    """
    header = """[Script Info]
Title: Lil Word Export
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,56,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2.5,1,2,60,60,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for cap in captions:
        text = cap.text
        # Neutralize literal backslashes first so they don't form \N or \an8
        text = text.replace("\\", "\\\u200B")
        # Neutralize ASS override blocks while preserving literal visual fidelity
        text = text.replace("{", "\\{").replace("}", "\\}")
        # ASS uses \N for line breaks
        text = text.replace("\n", "\\N")
        events.append(
            f"Dialogue: 0,{ms_to_ass_time(cap.start_ms)},{ms_to_ass_time(cap.end_ms)},"
            f"Default,,0,0,0,,{text}"
        )

    content = header + "\n".join(events) + "\n"
    Path(out_path).write_text(content, encoding="utf-8")
    return out_path


def export_burned_video(
    media_path: str,
    captions: list[Caption],
    out_path: str,
    codec: str = "libx264",
    crf: str = "18",
    cancel_check: Optional[Callable[[], bool]] = None,
) -> str:
    """Export video with burned-in subtitles.

    Writes a temporary ASS file then calls ffmpeg burn.
    """
    # Write temp ASS next to output
    ass_path = str(Path(out_path).with_suffix(".tmp.ass"))
    export_ass(captions, ass_path)
    try:
        media_service.burn_subtitles(media_path, ass_path, out_path, codec, crf, cancel_check=cancel_check)
    except Exception:
        try:
            os.remove(out_path)
        except OSError:
            pass
        raise
    finally:
        try:
            os.remove(ass_path)
        except OSError:
            pass
    return out_path


def export_ttml(captions: list[Caption], out_path: str, settings=None) -> str:
    """Export captions to TTML/DFXP format using the additive Exporter framework."""
    from app.exporters.ttml_dfxp import TTMLExporter
    cues = TTMLExporter.convert_captions(captions, settings=settings)
    content = TTMLExporter().generate(cues)
    Path(out_path).write_text(content, encoding="utf-8")
    return out_path


def export_ebu_tt(captions: list[Caption], out_path: str, settings=None) -> str:
    """Export captions to EBU-TT format using the additive Exporter framework."""
    from app.exporters.ebu_tt import EBUTTExporter
    cues = EBUTTExporter.convert_captions(captions, settings=settings)
    content = EBUTTExporter().generate(cues)
    Path(out_path).write_text(content, encoding="utf-8")
    return out_path


def export_smpte_tt(captions: list[Caption], out_path: str, settings=None) -> str:
    """Export captions to SMPTE-TT format using the additive Exporter framework."""
    from app.exporters.smpte_tt import SMPTETTExporter
    cues = SMPTETTExporter.convert_captions(captions, settings=settings)
    content = SMPTETTExporter().generate(cues)
    Path(out_path).write_text(content, encoding="utf-8")
    return out_path


def export_ebu_stl(
    captions: list[Caption],
    out_path: str,
    settings=None,
    fps: int | None = None,
) -> str:
    """Export captions to EBU STL binary format using the additive Exporter framework."""
    from app.exporters.ebu_stl import EBUSTLExporter
    cues = EBUSTLExporter.convert_captions(captions, settings=settings)
    source_fps = (
        _coerce_export_fps(fps, _coerce_export_fps(settings.get("ebu_stl_fps"), 25))
        if settings is not None else
        _coerce_export_fps(fps, 25)
    )
    content = EBUSTLExporter().generate(cues, fps=source_fps)
    Path(out_path).write_bytes(content)
    return out_path


def export_mcc(
    captions: list[Caption],
    out_path: str,
    settings=None,
    fps: int | None = None,
) -> str:
    """Export captions to MCC format using the additive Exporter framework."""
    from app.exporters.mcc import MCCExporter
    cues = MCCExporter.convert_captions(captions, settings=settings)
    source_fps = (
        _coerce_export_fps(fps, _coerce_export_fps(settings.get("mcc_fps"), 30))
        if settings is not None else
        _coerce_export_fps(fps, 30)
    )
    content = MCCExporter().generate(cues, fps=source_fps)
    Path(out_path).write_text(content, encoding="utf-8")
    return out_path
