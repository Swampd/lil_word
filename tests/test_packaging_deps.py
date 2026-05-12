"""Tests for packaged dependency discovery."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.media_service import _resolve_tool, MediaToolNotFoundError
from tests.test_acceptance import _ensure_test_dir


def test_resolve_tool_fallback_to_path():
    """If not frozen, _resolve_tool should query the system PATH using shutil.which."""
    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/ffmpeg"
        res = _resolve_tool("ffmpeg")
        assert res == "/usr/bin/ffmpeg"


def test_resolve_tool_not_found():
    """If tool is missing everywhere, raise MediaToolNotFoundError with honest message."""
    with patch("shutil.which", return_value=None):
        with pytest.raises(MediaToolNotFoundError, match="Required media tool 'ffmpeg' not found"):
            _resolve_tool("ffmpeg")


def test_resolve_tool_packaged_local():
    """If frozen, check alongside the executable before checking PATH."""
    tmp_dir = _ensure_test_dir() / "pkg_local"
    exe_dir = tmp_dir / "bin"
    exe_dir.mkdir(parents=True, exist_ok=True)
    fake_exe = exe_dir / "lil_word.exe"
    
    # Create the fake tool next to the exe
    tool_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    fake_tool = exe_dir / tool_name
    fake_tool.touch()

    with patch("sys.frozen", True, create=True), \
         patch("sys.executable", str(fake_exe)):
        res = _resolve_tool("ffmpeg")
        assert res == str(fake_tool)


def test_resolve_tool_packaged_meipass():
    """If frozen and local tool missing, check _MEIPASS before PATH."""
    tmp_dir = _ensure_test_dir() / "pkg_meipass"
    exe_dir = tmp_dir / "bin"
    exe_dir.mkdir(parents=True, exist_ok=True)
    fake_exe = exe_dir / "lil_word.exe"
    
    mei_dir = tmp_dir / "_internal"
    mei_dir.mkdir(parents=True, exist_ok=True)
    
    # Create the fake tool inside MEIPASS
    tool_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    fake_tool = mei_dir / tool_name
    fake_tool.touch()

    with patch("sys.frozen", True, create=True), \
         patch("sys.executable", str(fake_exe)), \
         patch("sys._MEIPASS", str(mei_dir), create=True), \
         patch("shutil.which", return_value=None):
        
        res = _resolve_tool("ffmpeg")
        assert res == str(fake_tool)
