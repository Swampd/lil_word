"""Media service – ffprobe, audio extraction, proxy generation, burned-in export."""

import json
import os
import subprocess
import tempfile
import time
import shutil
import sys
from pathlib import Path
from typing import Optional, Callable
from app.utils.errors import CancelledError


class MediaToolNotFoundError(Exception):
    """Raised when required media binaries (like ffmpeg/ffprobe) cannot be found."""
    pass


def _resolve_tool(tool_name: str) -> str:
    """Resolve the path to ffmpeg or ffprobe, searching local packaged directories first."""
    # 1. If running as a packaged app, check alongside the executable
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        local_tool = exe_dir / f"{tool_name}.exe" if os.name == "nt" else exe_dir / tool_name
        if local_tool.exists():
            return str(local_tool)
            
        # Also check inside the extracted _MEIPASS folder (if bundled using --onefile)
        meipass = getattr(sys, '_MEIPASS', '')
        if meipass:
            mei_tool = Path(meipass) / f"{tool_name}.exe" if os.name == "nt" else Path(meipass) / tool_name
            if mei_tool.exists():
                return str(mei_tool)

    # 2. Check system PATH
    path_tool = shutil.which(tool_name)
    if path_tool:
        return path_tool

    # 3. Fail explicitly with user-facing message
    exe_name = f"{tool_name}.exe" if os.name == "nt" else tool_name
    raise MediaToolNotFoundError(
        f"Required media tool '{tool_name}' not found.\n\n"
        f"If you are using the packaged application, please download {tool_name} "
        f"and place '{exe_name}' in the same folder as the Lil Word app, "
        f"or ensure it is available on your system PATH."
    )


def _get_ffmpeg() -> str:
    return _resolve_tool("ffmpeg")


def _get_ffprobe() -> str:
    return _resolve_tool("ffprobe")


def _parse_fps_value(value) -> float | None:
    """Parse a ffprobe frame-rate value into a float."""
    if value in (None, "", "0", "0/0", "unknown"):
        return None
    if isinstance(value, (int, float)):
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        return num if num > 0 else None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    if "/" in text:
        try:
            num_s, den_s = text.split("/", 1)
            num = float(num_s)
            den = float(den_s)
        except (TypeError, ValueError):
            return None
        if den <= 0:
            return None
        if num <= 0:
            return None
        return num / den

    try:
        num = float(text)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def get_video_fps(path: str) -> int | None:
    """Return integer FPS for the first video stream, or None when unavailable."""
    info = probe_media(path)
    for s in info.get("streams", []):
        if s.get("codec_type") != "video":
            continue
        for key in ("avg_frame_rate", "r_frame_rate", "time_base"):
            fps = _parse_fps_value(s.get(key))
            if fps is None:
                continue
            # Prefer sane, positive integer conversion for framecode output.
            fps_int = int(round(fps))
            if fps_int > 0:
                return fps_int
    return None


def _run(
    cmd: list[str],
    check: bool = True,
    timeout: Optional[float] = None,
    cancel_check: Optional[Callable[[], bool]] = None
) -> subprocess.CompletedProcess:
    """Run a subprocess hiding the console window on Windows."""
    si = None
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        if cancel_check is None:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                startupinfo=si,
                check=check,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        else:
            start_time = time.time()
            with tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='replace') as out_f, \
                 tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='replace') as err_f:
                proc = subprocess.Popen(
                    cmd,
                    stdout=out_f,
                    stderr=err_f,
                    text=True,
                    startupinfo=si,
                    stdin=subprocess.DEVNULL,
                )
                while proc.poll() is None:
                    if cancel_check():
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                        raise CancelledError("Operation cancelled by user.")
                    if timeout and (time.time() - start_time) > timeout:
                        proc.kill()
                        proc.wait()
                        raise subprocess.TimeoutExpired(cmd, timeout)
                    time.sleep(0.1)
                
                out_f.seek(0)
                err_f.seek(0)
                stdout = out_f.read()
                stderr = err_f.read()
                
                if check and proc.returncode != 0:
                    raise subprocess.CalledProcessError(proc.returncode, cmd, stdout, stderr)
                
                return subprocess.CompletedProcess(args=cmd, returncode=proc.returncode, stdout=stdout, stderr=stderr)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(cmd)}\nStderr: {exc.stderr}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Command failed with exit code {exc.returncode}: {' '.join(cmd)}\nStderr: {exc.stderr}") from exc


# ── Probe ────────────────────────────────────────────────────────────────────

def probe_media(path: str, cancel_check: Optional[Callable[[], bool]] = None) -> dict:
    """Return ffprobe JSON for a media file."""
    r = _run([
        _get_ffprobe(), "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ], timeout=30.0, cancel_check=cancel_check)
    return json.loads(r.stdout)


def get_duration_ms(path: str, cancel_check: Optional[Callable[[], bool]] = None) -> int:
    """Return media duration in ms."""
    info = probe_media(path, cancel_check=cancel_check)
    dur = float(info.get("format", {}).get("duration", 0))
    return int(dur * 1000)


def has_video_stream(path: str, cancel_check: Optional[Callable[[], bool]] = None) -> bool:
    """Check if the file contains a video stream."""
    info = probe_media(path, cancel_check=cancel_check)
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            return True
    return False


def needs_proxy(path: str, cancel_check: Optional[Callable[[], bool]] = None) -> bool:
    """Return True if the video codec is not optimal for native playback (e.g., anything but h264)."""
    info = probe_media(path, cancel_check=cancel_check)
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            codec = s.get("codec_name", "")
            if codec not in ["h264"]:
                return True
    return False


# ── Audio extraction ─────────────────────────────────────────────────────────

def extract_audio_wav(
    media_path: str,
    out_path: str,
    cancel_check: Optional[Callable[[], bool]] = None
) -> str:
    """Extract mono 16kHz WAV from media file."""
    try:
        _run([
            _get_ffmpeg(), "-y", "-i", str(media_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            str(out_path),
        ], timeout=120.0, cancel_check=cancel_check)
    except Exception:
        try:
            os.remove(out_path)
        except OSError:
            pass
        raise
    return out_path


# ── Proxy ────────────────────────────────────────────────────────────────────

def generate_proxy(
    media_path: str,
    out_path: str,
    width: int = 640,
    cancel_check: Optional[Callable[[], bool]] = None
) -> str:
    """Generate a low-resolution proxy video for preview."""
    try:
        _run([
            _get_ffmpeg(), "-y", "-i", str(media_path),
            "-vf", f"scale={width}:-2",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "28", "-an",
            str(out_path),
        ], timeout=300.0, cancel_check=cancel_check)
    except Exception:
        try:
            os.remove(out_path)
        except OSError:
            pass
        raise
    return out_path


# ── Export burned-in ─────────────────────────────────────────────────────────

def escape_for_ffmpeg_filter(text: str) -> str:
    """Double escape path for FFMPEG filtergraph and filter parsers.
    
    FFMPEG evaluates unquoted string literals across two parsing layers:
    1. Filter parser (splits by : and =)
    2. Filtergraph parser (splits by , and ; and unescapes further)
    """
    s = str(text).replace("\\", "/")
    
    level1 = ""
    for c in s:
        if c in "=:'\\":
            level1 += "\\" + c
        else:
            level1 += c
            
    level2 = ""
    for c in level1:
        if c in ",;\\'[]":
            level2 += "\\" + c
        else:
            level2 += c
            
    return level2

def burn_subtitles(
    media_path: str,
    ass_path: str,
    out_path: str,
    codec: str = "libx264",
    crf: str = "18",
    cancel_check: Optional[Callable[[], bool]] = None,
) -> str:
    """Burn ASS subtitles into a video file.

    Uses the subtitles filter which handles ASS natively.
    The ASS path is meticulously double-escaped for Windows compatibility.
    """
    safe_ass = escape_for_ffmpeg_filter(ass_path)
    vf = f"subtitles={safe_ass}"
    _run([
        _get_ffmpeg(), "-y", "-i", str(media_path),
        "-vf", vf,
        "-c:v", codec, "-crf", crf,
        "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ], timeout=600.0, cancel_check=cancel_check)
    return out_path
