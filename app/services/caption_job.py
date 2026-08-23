"""Headless caption job orchestration for desktop and Premiere workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from app.models.caption import Caption, TranscriptWord
from app.services import alignment_service, caption_engine, export_service, media_service, transcription_service
from app.utils.errors import CancelledError
from app.utils.export_helpers import build_audio_output_path, build_proxy_output_path

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[["CaptionJobProgress"], None]


@dataclass
class CaptionJobRequest:
    input_path: str
    output_dir: str | None = None
    outputs: list[str] = field(default_factory=lambda: ["ttml", "srt"])
    settings: Mapping[str, Any] | Any | None = None
    persist_project: bool = False
    source_context: dict[str, Any] | None = None
    work_dir: str | None = None
    audio_path: str | None = None
    make_proxy: bool = True


@dataclass
class CaptionJobOutput:
    format: str
    path: str


@dataclass
class CaptionJobProgress:
    phase: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaptionJobError:
    phase: str
    message: str
    exception_type: str


@dataclass
class CaptionJobResult:
    status: str
    input_path: str
    audio_path: str | None = None
    proxy_path: str | None = None
    media_duration_ms: int = 0
    has_video: bool = False
    captions: list[Caption] = field(default_factory=list)
    transcript_segments: list[dict] = field(default_factory=list)
    transcript_words: list[TranscriptWord] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    output_items: list[CaptionJobOutput] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: CaptionJobError | None = None


@dataclass
class CaptionMediaInfo:
    input_path: str
    audio_path: str
    proxy_path: str
    media_duration_ms: int
    has_video: bool
    media_fps: int | None = None


def run_caption_job(
    request: CaptionJobRequest,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> CaptionJobResult:
    """Run a full headless caption job and return structured results."""
    phase = "starting"
    outputs: dict[str, str] = {}
    output_items: list[CaptionJobOutput] = []
    media_info: CaptionMediaInfo | None = None
    segments: list[dict] = []
    words: list[TranscriptWord] = []
    captions: list[Caption] = []

    try:
        _emit(progress_callback, phase, "Starting caption job")
        _raise_if_cancelled(cancel_check)

        media_info = prepare_caption_media(
            request.input_path,
            audio_path=request.audio_path,
            work_dir=request.work_dir,
            make_proxy=request.make_proxy,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

        segments, words, captions = transcribe_and_generate_captions(
            media_info.audio_path,
            request.settings,
            media_duration_ms=media_info.media_duration_ms,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

        outputs, output_items = export_caption_outputs(
            captions,
            request.input_path,
            output_dir=request.output_dir,
            outputs=request.outputs,
            settings=request.settings,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

        _emit(progress_callback, "complete", "Caption job complete", {"outputs": dict(outputs)})
        return CaptionJobResult(
            status="ok",
            input_path=request.input_path,
            audio_path=media_info.audio_path,
            proxy_path=media_info.proxy_path,
            media_duration_ms=media_info.media_duration_ms,
            has_video=media_info.has_video,
            captions=captions,
            transcript_segments=segments,
            transcript_words=words,
            outputs=outputs,
            output_items=output_items,
            diagnostics=_diagnostics(request, captions),
        )
    except CancelledError as exc:
        _emit(progress_callback, "cancelled", "Caption job cancelled")
        return CaptionJobResult(
            status="cancelled",
            input_path=request.input_path,
            audio_path=media_info.audio_path if media_info else request.audio_path,
            proxy_path=media_info.proxy_path if media_info else None,
            media_duration_ms=media_info.media_duration_ms if media_info else 0,
            has_video=media_info.has_video if media_info else False,
            captions=captions,
            transcript_segments=segments,
            transcript_words=words,
            outputs=outputs,
            output_items=output_items,
            diagnostics=_diagnostics(request, captions),
            error=CaptionJobError("cancelled", str(exc), type(exc).__name__),
        )
    except Exception as exc:
        _emit(progress_callback, "error", str(exc), {"exception_type": type(exc).__name__})
        return CaptionJobResult(
            status="error",
            input_path=request.input_path,
            audio_path=media_info.audio_path if media_info else request.audio_path,
            proxy_path=media_info.proxy_path if media_info else None,
            media_duration_ms=media_info.media_duration_ms if media_info else 0,
            has_video=media_info.has_video if media_info else False,
            captions=captions,
            transcript_segments=segments,
            transcript_words=words,
            outputs=outputs,
            output_items=output_items,
            diagnostics=_diagnostics(request, captions),
            error=CaptionJobError("error", str(exc), type(exc).__name__),
        )


def prepare_caption_media(
    input_path: str,
    audio_path: str | None = None,
    work_dir: str | None = None,
    make_proxy: bool = True,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> CaptionMediaInfo:
    """Probe media, optionally create a proxy, and extract 16 kHz mono audio."""
    media = Path(input_path)
    if work_dir is None:
        work_dir_path = media.parent / ".lil_word"
    else:
        work_dir_path = Path(work_dir)
    work_dir_path.mkdir(parents=True, exist_ok=True)

    if audio_path is None:
        audio_path = build_audio_output_path(media.stem, str(work_dir_path))

    _raise_if_cancelled(cancel_check)
    _emit(progress_callback, "probing_media", "Probing media")
    duration_ms = media_service.get_duration_ms(input_path, cancel_check=cancel_check)
    media_fps = media_service.get_video_fps(input_path)

    _raise_if_cancelled(cancel_check)
    has_video = media_service.has_video_stream(input_path, cancel_check=cancel_check)

    proxy_path = ""
    if has_video and make_proxy:
        _emit(progress_callback, "probing_media", "Checking video compatibility")
        if media_service.needs_proxy(input_path, cancel_check=cancel_check):
            _raise_if_cancelled(cancel_check)
            _emit(progress_callback, "probing_media", "Generating proxy video")
            proxy_path = build_proxy_output_path(media.stem, str(work_dir_path))
            media_service.generate_proxy(input_path, proxy_path, cancel_check=cancel_check)

    _raise_if_cancelled(cancel_check)
    _emit(progress_callback, "extracting_audio", "Extracting audio")
    media_service.extract_audio_wav(input_path, audio_path, cancel_check=cancel_check)

    return CaptionMediaInfo(
        input_path=input_path,
        audio_path=audio_path,
        proxy_path=proxy_path,
        media_duration_ms=duration_ms,
        has_video=has_video,
        media_fps=media_fps,
    )


def transcribe_and_generate_captions(
    audio_path: str,
    settings: Mapping[str, Any] | Any | None,
    media_duration_ms: int = 0,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> tuple[list[dict], list[TranscriptWord], list[Caption]]:
    """Transcribe audio, build caption blocks, and refine timing."""
    _raise_if_cancelled(cancel_check)
    _emit(progress_callback, "loading_model", "Loading whisper model")
    _emit(progress_callback, "transcribing", "Transcribing audio")
    segments, words = transcription_service.transcribe(
        audio_path,
        model_size=_setting(settings, "whisper_model", "base"),
        device=_setting(settings, "whisper_device", "auto"),
        compute_type=_setting(settings, "whisper_compute_type", "int8"),
        cancel_check=cancel_check,
    )

    captions = generate_caption_blocks(
        segments,
        words,
        settings,
        media_duration_ms=media_duration_ms,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )

    _raise_if_cancelled(cancel_check)
    _emit(progress_callback, "refining_timing", "Refining timing with silence detection")
    captions = alignment_service.refine_timing(
        captions,
        audio_path,
        media_duration_ms=media_duration_ms,
    )
    return segments, words, captions


def generate_caption_blocks(
    segments: list[dict],
    words: list[TranscriptWord],
    settings: Mapping[str, Any] | Any | None,
    media_duration_ms: int = 0,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> list[Caption]:
    """Generate caption blocks from transcript data using shared timing settings."""
    _raise_if_cancelled(cancel_check)
    _emit(progress_callback, "generating_captions", "Generating caption blocks")
    return caption_engine.generate_captions(
        segments,
        words,
        lead_in=_setting(settings, "lead_in_ms", 150),
        lead_out=_setting(settings, "lead_out_ms", 250),
        min_dur=_setting(settings, "min_caption_ms", 700),
        max_dur=_setting(settings, "max_caption_ms", 3500),
        min_gap=_setting(settings, "min_gap_ms", 100),
        max_lines=_setting(settings, "max_lines", 2),
        max_cpl=_setting(settings, "max_chars_per_line", 42),
        target_cps_min=_setting(settings, "target_cps_min", 12),
        target_cps_max=_setting(settings, "target_cps_max", 20),
        media_duration_ms=media_duration_ms,
    )


def export_caption_outputs(
    captions: list[Caption],
    input_path: str,
    output_dir: str | None,
    outputs: list[str],
    settings: Mapping[str, Any] | Any | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> tuple[dict[str, str], list[CaptionJobOutput]]:
    """Write requested standalone caption artifacts."""
    if output_dir is None:
        output_dir_path = Path(input_path).parent
    else:
        output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    written: dict[str, str] = {}
    items: list[CaptionJobOutput] = []
    for output in outputs:
        output_id = output.lower().strip()
        _raise_if_cancelled(cancel_check)
        phase = f"exporting_{output_id}"
        _emit(progress_callback, phase, f"Exporting {output_id.upper()}")

        if output_id == "srt":
            path = _unique_output_path(output_dir_path, input_path, "_lilword.srt")
            export_service.export_srt(captions, str(path))
        elif output_id in {"ttml", "dfxp"}:
            path = _unique_output_path(output_dir_path, input_path, "_lilword.ttml")
            export_service.export_ttml(captions, str(path), settings=settings)
            output_id = "ttml"
        else:
            raise ValueError(f"Unsupported caption job output: {output}")

        written[output_id] = str(path)
        items.append(CaptionJobOutput(output_id, str(path)))

    return written, items


def export_burned_caption_video(
    media_path: str,
    captions: list[Caption],
    out_path: str,
    settings: Mapping[str, Any] | Any | None = None,
    cancel_check: CancelCheck | None = None,
) -> str:
    """Export a burned-in video while keeping worker orchestration outside Qt."""
    _raise_if_cancelled(cancel_check)
    return export_service.export_burned_video(
        media_path,
        captions,
        out_path,
        codec=_setting(settings, "export_video_codec", "libx264"),
        crf=_setting(settings, "export_video_crf", "18"),
        cancel_check=cancel_check,
    )


def _emit(
    progress_callback: ProgressCallback | None,
    phase: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> None:
    if progress_callback is not None:
        progress_callback(CaptionJobProgress(phase=phase, message=message, detail=detail or {}))


def _raise_if_cancelled(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise CancelledError("Caption job cancelled.")


def _setting(settings: Mapping[str, Any] | Any | None, key: str, default: Any) -> Any:
    if settings is None:
        return default
    getter = getattr(settings, "get", None)
    if callable(getter):
        return getter(key, default)
    if isinstance(settings, Mapping):
        return settings.get(key, default)
    return default


def _unique_output_path(output_dir: Path, input_path: str, suffix: str) -> Path:
    stem = Path(input_path).stem or "caption_job"
    candidate = output_dir / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate

    suffix_path = Path(suffix)
    base_suffix_stem = suffix_path.stem
    extension = suffix_path.suffix
    for index in range(2, 10000):
        candidate = output_dir / f"{stem}{base_suffix_stem}_{index}{extension}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate unique output path in {output_dir}")


def _diagnostics(request: CaptionJobRequest, captions: list[Caption]) -> dict[str, Any]:
    return {
        "caption_count": len(captions),
        "requested_outputs": list(request.outputs),
        "persist_project": request.persist_project,
        "source_context": dict(request.source_context or {}),
    }
