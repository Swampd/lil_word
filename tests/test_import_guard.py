"""Tests for the production ImportSessionGuard and audio path helpers.

These tests exercise the actual production state machine from
app.utils.import_session, which MainWindow uses for import reentrancy
and stale-callback protection.
"""

from app.utils.import_session import ImportSessionGuard
from app.utils.export_helpers import build_audio_output_path


# ── Import session guard tests ───────────────────────────────────────────────

def test_second_import_rejected_while_first_active():
    """A second import request must be rejected while an import is in progress."""
    guard = ImportSessionGuard()

    token1 = guard.start_import("/path/to/video1.mp4")
    assert token1 is not None
    assert guard.is_active
    assert guard.token == token1
    assert guard.media_path == "/path/to/video1.mp4"

    # Second import while first is still active
    token2 = guard.start_import("/path/to/video2.mp4")
    assert token2 is None
    # Original token and media path unchanged
    assert guard.token == token1
    assert guard.media_path == "/path/to/video1.mp4"


def test_stale_completion_ignored():
    """A completion callback with a non-matching token must be ignored."""
    guard = ImportSessionGuard()

    token1 = guard.start_import("/path/to/video1.mp4")
    assert token1 is not None

    # Simulate stale completion from some other import
    stale_token = "stale_fake_token_12345"
    accepted = guard.accept_done(stale_token)
    assert accepted is False
    # Guard should still be active with the original token
    assert guard.is_active
    assert guard.token == token1


def test_stale_error_ignored():
    """A stale error callback must not clear the active import."""
    guard = ImportSessionGuard()

    token1 = guard.start_import("/path/to/video1.mp4")
    stale_token = "stale_fake_token_12345"

    accepted = guard.accept_error(stale_token)
    assert accepted is False
    assert guard.is_active
    assert guard.token == token1
    assert guard.media_path == "/path/to/video1.mp4"


def test_token_cleared_on_success():
    """Import token must be cleared after successful completion."""
    guard = ImportSessionGuard()

    token = guard.start_import("/path/to/video.mp4")
    accepted = guard.accept_done(token)
    assert accepted is True
    assert not guard.is_active
    assert guard.token is None
    # Media path is intentionally preserved after success
    assert guard.media_path == "/path/to/video.mp4"

    # Can start a new import now
    token2 = guard.start_import("/path/to/video2.mp4")
    assert token2 is not None


def test_token_cleared_on_error():
    """Import token and media path must be cleared after error."""
    guard = ImportSessionGuard()

    token = guard.start_import("/path/to/video.mp4")
    accepted = guard.accept_error(token)
    assert accepted is True
    assert not guard.is_active
    assert guard.token is None
    assert guard.media_path is None

    # Can start a new import now
    token2 = guard.start_import("/path/to/video2.mp4")
    assert token2 is not None


def test_correct_completion_after_rejected_second_import():
    """After rejecting a second import, the first import's completion must still work."""
    guard = ImportSessionGuard()

    token1 = guard.start_import("/path/to/video1.mp4")
    # Second import rejected
    rejected = guard.start_import("/path/to/video2.mp4")
    assert rejected is None
    # First import completes successfully
    accepted = guard.accept_done(token1)
    assert accepted is True
    assert not guard.is_active


def test_new_import_after_error_recovery():
    """A new import must succeed after a prior import errored out."""
    guard = ImportSessionGuard()

    token1 = guard.start_import("/path/to/video1.mp4")
    guard.accept_error(token1)
    assert not guard.is_active

    token2 = guard.start_import("/path/to/video2.mp4")
    assert token2 is not None
    assert guard.media_path == "/path/to/video2.mp4"

    accepted = guard.accept_done(token2)
    assert accepted is True
    assert not guard.is_active


# ── Audio path uniqueness ────────────────────────────────────────────────────

def test_audio_paths_never_collide():
    """100 audio path generations for the same stem must all be unique."""
    paths = set()
    for _ in range(100):
        p = build_audio_output_path("same_video", "/work/dir")
        assert p not in paths, f"Collision: {p}"
        paths.add(p)
