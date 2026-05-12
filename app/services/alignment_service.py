"""Alignment service – refine caption timing using silence/pause detection.

Uses webrtcvad (via the webrtcvad-wheels package) to detect silence regions
in the extracted 16kHz mono WAV, then snaps caption boundaries toward
nearby silence to produce more natural-feeling timing.
"""

from __future__ import annotations

import logging
import wave
from typing import Optional

from app.models.caption import Caption

log = logging.getLogger(__name__)

try:
    import webrtcvad
    _HAS_VAD = True
except ImportError:
    _HAS_VAD = False


# ── Silence detection ────────────────────────────────────────────────────────

def detect_silence_regions(
    wav_path: str,
    aggressiveness: int = 2,
    frame_ms: int = 30,
) -> list[tuple[int, int]]:
    """Return list of (start_ms, end_ms) silence regions in a 16kHz mono WAV.

    Uses webrtcvad to classify each frame as speech or non-speech, then
    merges consecutive non-speech frames into silence regions.

    Returns empty list and logs a warning if the WAV format is unsupported.
    """
    if not _HAS_VAD:
        return []

    vad = webrtcvad.Vad(aggressiveness)

    try:
        with wave.open(wav_path, "rb") as wf:
            channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            if channels != 1:
                log.warning(
                    "VAD requires mono audio, got %d channels – skipping silence detection",
                    channels,
                )
                return []
            if sample_rate not in (8000, 16000, 32000, 48000):
                log.warning(
                    "VAD requires 8/16/32/48 kHz, got %d Hz – skipping silence detection",
                    sample_rate,
                )
                return []
            n_frames = wf.getnframes()
            pcm = wf.readframes(n_frames)
    except Exception as exc:
        log.warning("Could not read WAV for silence detection: %s", exc)
        return []

    frame_size = int(sample_rate * frame_ms / 1000)  # samples per frame
    frame_bytes = frame_size * 2  # 16-bit PCM

    silences: list[tuple[int, int]] = []
    silence_start: Optional[int] = None

    offset = 0
    time_ms = 0
    while offset + frame_bytes <= len(pcm):
        chunk = pcm[offset:offset + frame_bytes]
        is_speech = vad.is_speech(chunk, sample_rate)

        if not is_speech:
            if silence_start is None:
                silence_start = time_ms
        else:
            if silence_start is not None:
                silences.append((silence_start, time_ms))
                silence_start = None

        offset += frame_bytes
        time_ms += frame_ms

    # Close trailing silence
    if silence_start is not None:
        silences.append((silence_start, time_ms))

    return silences


# ── Alignment refinement ─────────────────────────────────────────────────────

def refine_timing(
    captions: list[Caption],
    wav_path: str,
    snap_range_ms: int = 200,
    min_gap_ms: int = 80,
    media_duration_ms: int = 0,
) -> list[Caption]:
    """Refine caption timing by snapping boundaries toward nearby silence.

    For each caption start/end, if there is a silence boundary within
    snap_range_ms, shift the caption boundary to align with it.
    Delegates final normalization to the shared normalizer.
    """
    from app.services.caption_engine import normalize_captions

    silences = detect_silence_regions(wav_path)
    if not silences:
        return normalize_captions(
            captions, min_gap=min_gap_ms,
            media_duration_ms=media_duration_ms,
        )

    # Build sorted list of silence boundaries (both starts and ends)
    boundaries: list[int] = []
    for s_start, s_end in silences:
        boundaries.append(s_start)
        boundaries.append(s_end)
    boundaries.sort()

    for cap in captions:
        # Snap start toward nearest silence boundary
        nearest_start = _find_nearest(boundaries, cap.start_ms)
        if nearest_start is not None and abs(nearest_start - cap.start_ms) <= snap_range_ms:
            cap.start_ms = nearest_start

        # Snap end toward nearest silence boundary
        nearest_end = _find_nearest(boundaries, cap.end_ms)
        if nearest_end is not None and abs(nearest_end - cap.end_ms) <= snap_range_ms:
            cap.end_ms = nearest_end

    # Delegate final cleanup to shared normalizer
    return normalize_captions(
        captions, min_gap=min_gap_ms,
        media_duration_ms=media_duration_ms,
    )


def _find_nearest(sorted_vals: list[int], target: int) -> Optional[int]:
    """Binary search for the nearest value in a sorted list."""
    if not sorted_vals:
        return None
    lo, hi = 0, len(sorted_vals) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_vals[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    # Check neighbours
    best = sorted_vals[lo]
    if lo > 0 and abs(sorted_vals[lo - 1] - target) < abs(best - target):
        best = sorted_vals[lo - 1]
    return best
