from unittest.mock import Mock, patch
from app.ui.main_window import MainWindow
from app.ui.video_panel import DropZoneWidget
from app.utils.settings import Settings

from PySide6.QtWidgets import QApplication
import sys


def _ensure_app():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    return app


def _make_window():
    _ensure_app()
    settings = Settings()
    svc = Mock()
    svc.get_latest_project.return_value = None
    svc.list_recent_projects.return_value = []
    return MainWindow(settings, svc)


def test_drop_targets_accept_drops():
    window = _make_window()

    # The central widget
    central = window.centralWidget()
    assert central.acceptDrops() is True

    # The splitter
    assert window._splitter.acceptDrops() is True

    # The caption panel widgets
    for t in window._caption_panel.get_drop_targets():
        assert t.acceptDrops() is True

    # The DropZoneWidget inside the video panel must accept drops directly
    drop_zone = window._video_panel._drop_zone
    assert isinstance(drop_zone, DropZoneWidget)
    assert drop_zone.acceptDrops() is True


def test_drop_zone_is_visible_on_startup():
    """The drop zone must be the visible widget when no media is loaded."""
    window = _make_window()

    # Stack should show drop zone (index 0) on startup
    stack = window._video_panel._stack
    assert stack.currentIndex() == 0
    assert stack.currentWidget() is window._video_panel._drop_zone


# ── Watchdog regression tests ────────────────────────────────────────────────

@patch("app.ui.main_window.QMessageBox")
def test_watchdog_clears_guard_and_restores_ui(mock_msgbox):
    """_on_import_watchdog must clear the import guard, hide progress,
    re-enable Import, and reset project/captions/words without crashing."""
    window = _make_window()

    # Simulate an active import session
    token = window._import_guard.start_import("/fake/media.mp3")
    assert token is not None
    assert window._import_guard.is_active

    # Simulate UI state during import
    window._progress.setVisible(True)
    window._btn_import.setEnabled(False)
    window._project = Mock()
    window._captions = [Mock()]
    window._words = [Mock()]
    window._media_duration_ms = 5000

    # Fire the watchdog — must not raise AttributeError
    window._on_import_watchdog()

    # Guard must be cleared
    assert not window._import_guard.is_active
    assert window._import_guard.token is None

    # UI must be restored
    assert window._btn_import.isEnabled()
    assert not window._progress.isVisible()

    # State must be reset
    assert window._project is None
    assert window._captions == []
    assert window._words == []
    assert window._media_duration_ms == 0

    # QMessageBox.critical must have been called
    mock_msgbox.critical.assert_called_once()


@patch("app.ui.main_window.QMessageBox")
def test_watchdog_cancels_worker_before_clearing_ui_state(mock_msgbox):
    """Watchdog cancellation must reach the active worker before UI state is reset."""
    window = _make_window()

    token = window._import_guard.start_import("/fake/media.mp3")
    assert token is not None
    window._progress.setVisible(True)
    window._btn_import.setEnabled(False)
    window._project = Mock()
    window._captions = [Mock()]
    window._words = [Mock()]
    window._segments = [{"start": 0, "end": 1, "text": "before reset"}]
    window._media_duration_ms = 5000

    worker = Mock()
    worker._is_cancelled = False

    def cancel():
        assert window._import_guard.is_active
        assert window._project is not None
        assert window._captions
        assert window._words
        assert window._segments
        worker._is_cancelled = True

    worker.cancel.side_effect = cancel
    window._import_worker_ref = worker

    window._on_import_watchdog()

    worker.cancel.assert_called_once_with()
    assert not window._import_guard.is_active
    assert window._project is None


@patch("app.ui.main_window.QMessageBox")
def test_watchdog_allows_new_import_after_recovery(mock_msgbox):
    """After watchdog fires, a new import must be startable."""
    window = _make_window()

    # Start and watchdog-kill an import
    token = window._import_guard.start_import("/fake/first.mp3")
    window._on_import_watchdog()

    # A new import must now be accepted
    new_token = window._import_guard.start_import("/fake/second.mp3")
    assert new_token is not None
    assert window._import_guard.is_active


@patch("app.ui.main_window.QMessageBox")
def test_stale_done_does_not_stop_watchdog(mock_msgbox):
    """A stale completion callback must not stop the watchdog timer."""
    window = _make_window()

    # Start import A
    token_a = window._import_guard.start_import("/fake/a.mp3")

    # Simulate: import A completed and guard cleared
    window._import_guard.accept_done(token_a)

    # Start import B
    token_b = window._import_guard.start_import("/fake/b.mp3")
    window._import_watchdog.start(150_000)

    # A stale completion from import A arrives
    window._on_import_done("/fake/audio.wav", 1000, False, "", 0, token_a)

    # Watchdog must still be running for import B
    assert window._import_watchdog.isActive()

    # Clean up
    window._import_watchdog.stop()
