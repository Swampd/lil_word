"""Transcription service – faster-whisper model loading and transcription."""

from __future__ import annotations

import logging
from typing import Optional, Callable

from faster_whisper import WhisperModel
from app.utils.errors import CancelledError, ModelDownloadError

from app.models.caption import TranscriptWord

log = logging.getLogger(__name__)

# Module-level model cache so we avoid reloading on every clip.
_model: Optional[WhisperModel] = None
_model_config: Optional[tuple[str, str, str]] = None


def _get_model(
    model_size: str = "base",
    device: str = "auto",
    compute_type: str = "int8",
) -> WhisperModel:
    """Return (possibly cached) WhisperModel."""
    global _model, _model_config
    current_config = (model_size, device, compute_type)
    if _model is not None and _model_config == current_config:
        return _model
    log.info("Loading whisper model '%s' (device=%s, compute=%s)…",
             model_size, device, compute_type)
    try:
        _model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as exc:
        exc_str = str(exc).lower()
        exc_name = type(exc).__name__.lower()
        if "localentrynotfounderror" in exc_name or "localentrynotfounderror" in exc_str or \
           "connectionerror" in exc_name or "connectionerror" in exc_str or \
           "maxretryerror" in exc_name or "maxretryerror" in exc_str or \
           "offline" in exc_str:
            raise ModelDownloadError(
                "Failed to download or locate the Whisper transcription model.\n\n"
                "If this is your first time transcribing, the application needs to "
                "download the model from the internet. Please check your network connection "
                "or firewall settings and try again."
            ) from exc
        raise
    _model_config = current_config
    return _model


def transcribe(
    audio_path: str,
    model_size: str = "base",
    device: str = "auto",
    compute_type: str = "int8",
    language: str | None = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> tuple[list[dict], list[TranscriptWord]]:
    """Run transcription on a 16kHz mono WAV.

    Returns
    -------
    segments : list[dict]
        Each dict has keys: start, end, text
    words : list[TranscriptWord]
        Word-level timing (may be empty if model does not provide it).
    """
    model = _get_model(model_size, device, compute_type)
    seg_gen, info = model.transcribe(
        audio_path,
        beam_size=5,
        word_timestamps=True,
        language=language,
    )
    segments: list[dict] = []
    words: list[TranscriptWord] = []
    word_idx = 0

    for seg in seg_gen:
        if cancel_check and cancel_check():
            raise CancelledError("Transcription cancelled by user.")
        segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
        })
        if seg.words:
            for w in seg.words:
                words.append(TranscriptWord(
                    start_ms=int(w.start * 1000),
                    end_ms=int(w.end * 1000),
                    text=w.word.strip(),
                    confidence=round(w.probability, 4) if w.probability else 1.0,
                    idx=word_idx,
                ))
                word_idx += 1

    log.info("Transcription complete: %d segments, %d words", len(segments), len(words))
    return segments, words
