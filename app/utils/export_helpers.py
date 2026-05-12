"""Shared pure helpers used by both UI and tests."""

import uuid
from pathlib import Path


def build_export_name(media_path: str, suffix: str) -> str:
    """Build default export filename from media path and suffix.

    Handles both dot-prefixed extensions (.srt, .ass) and stem suffixes
    (_subtitled.mp4).
    """
    if media_path:
        media = Path(media_path)
        if suffix.startswith("."):
            return str(media.with_suffix(suffix))
        # Stem suffix like "_subtitled.mp4"
        return str(media.with_name(f"{media.stem}{suffix}"))
    return f"export{suffix}"


def build_audio_output_path(media_stem: str, work_dir: str) -> str:
    """Build a collision-proof audio output path using uuid4.

    Returns a path like: work_dir/media_stem_<uuid>_audio_16k.wav
    """
    token = uuid.uuid4().hex[:12]
    filename = f"{media_stem}_{token}_audio_16k.wav"
    return str(Path(work_dir) / filename)


def build_proxy_output_path(media_stem: str, work_dir: str) -> str:
    """Build a collision-proof proxy output path using uuid4.

    Returns a path like: work_dir/media_stem_<uuid>_proxy.mp4
    """
    token = uuid.uuid4().hex[:12]
    filename = f"{media_stem}_{token}_proxy.mp4"
    return str(Path(work_dir) / filename)

