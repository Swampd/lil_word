import sys
import pytest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEvent, QObject, Qt, Signal

from app.ui import main_window
from app.ui.main_window import MainWindow
from app.utils.settings import Settings
from app.services.project_service import ProjectService
from tests.test_acceptance import _ensure_test_dir, _generate_synthetic_mp4, _generate_synthetic_mp3, skip_no_ffmpeg

def _ensure_app():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    return app


def test_terminal_worker_signals_schedule_worker_deletion():
    """Each terminal outcome should release the worker QObject via Qt."""
    _ensure_app()

    class Worker(QObject):
        finished = Signal(str)
        error = Signal(str)
        cancelled = Signal()

    for signal_name, args in (
        ("finished", ("done",)),
        ("error", ("failed",)),
        ("cancelled", ()),
    ):
        worker = Worker()
        destroyed = []
        worker.destroyed.connect(lambda: destroyed.append(True))

        main_window._connect_worker_lifecycle(worker)
        getattr(worker, signal_name).emit(*args)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        assert destroyed == [True]

@skip_no_ffmpeg
@patch("app.ui.main_window.QMessageBox.critical")
def test_gui_worker_import_success(mock_msgbox):
    """Verify MainWindow._load_media completes via real worker thread without SQLite thread-affinity crash."""
    app = _ensure_app()

    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_import.db"
    db_path.unlink(missing_ok=True)

    mp4 = str(test_dir / "gui_import_input.mp4")
    try:
        _generate_synthetic_mp4(mp4, 2.0)
        
        settings = Settings()
        project_svc = ProjectService(db_path)
        window = MainWindow(settings, project_svc)
        
        # Start import
        window._load_media(mp4)
        
        # Wait for the worker thread to finish
        import_finished = False
        import_error = False
        
        def on_done():
            nonlocal import_finished
            import_finished = True
            
        def on_error(msg):
            nonlocal import_finished, import_error
            import_finished = True
            import_error = True

        assert hasattr(window, "_import_worker_ref")
        window._import_worker_ref.finished.connect(on_done)
        window._import_worker_ref.error.connect(lambda msg, token: on_error(msg))
        
        assert hasattr(window, "_import_thread")
        thread_ref = window._import_thread
        
        timer = QElapsedTimer()
        timer.start()
        
        while not import_finished and timer.elapsed() < 15000:
            app.processEvents()
            
        assert import_finished, "Import worker did not finish within timeout"
        assert not import_error, "Import worker emitted an error"
        
        # Ensure the thread is safely shut down before we assert and exit test
        while thread_ref.isRunning() and timer.elapsed() < 18000:
            app.processEvents()
        
        # The cross-thread SQLite crash would hit in _on_import_done and skip the rest of the lines
        # So we assert the UI state mutations that happen after SQLite insertion
        assert not window._import_guard.is_active
        assert window._project is not None
        assert window._project.id is not None
        assert Path(window._project.audio_path).exists()
        assert window._btn_transcribe.isEnabled()
        assert window._status_label.text().startswith("Media loaded")
        assert window._media_duration_ms > 0
        
        # Ensure MessageBox was not called due to unexpected threading bugs catching
        mock_msgbox.assert_not_called()
        
        project_svc.close()
        
    finally:
        if 'window' in locals():
            window._video_panel.reset_to_empty()
            app.processEvents()
        Path(mp4).unlink(missing_ok=True)
        db_path.unlink(missing_ok=True)


@skip_no_ffmpeg
@patch("app.ui.main_window.QMessageBox.critical")
def test_gui_audio_only_import_success(mock_msgbox):
    """Verify MainWindow._load_media completes audio-only MP3 and correctly toggles video-panel state."""
    app = _ensure_app()

    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_audio_only.db"
    db_path.unlink(missing_ok=True)

    mp3 = str(test_dir / "gui_import_input.mp3")
    try:
        _generate_synthetic_mp3(mp3, 2.0)
        
        settings = Settings()
        project_svc = ProjectService(db_path)
        window = MainWindow(settings, project_svc)
        
        # Start import
        window._load_media(mp3)
        
        import_finished = False
        import_error = False
        
        def on_done():
            nonlocal import_finished
            import_finished = True
            
        def on_error(msg):
            nonlocal import_finished, import_error
            import_finished = True
            import_error = True

        window._import_worker_ref.finished.connect(on_done)
        window._import_worker_ref.error.connect(lambda msg, token: on_error(msg))
        
        thread_ref = window._import_thread
        
        timer = QElapsedTimer()
        timer.start()
        
        while not import_finished and timer.elapsed() < 15000:
            app.processEvents()
            
        assert import_finished, "Import worker did not finish within timeout"
        assert not import_error, "Import worker emitted an error"
        
        while thread_ref.isRunning() and timer.elapsed() < 18000:
            app.processEvents()
        
        # Verify stack index swapped to Audio Label (2) and DropZone (0) is hidden
        stack = window._video_panel._stack
        assert stack.currentIndex() == 2
        
        # Verify Audio loaded text
        audio_file = window._video_panel._audio_canvas._filename
        assert "gui_import_input.mp3" == audio_file
        
        assert window._btn_transcribe.isEnabled()
        
        project_svc.close()
        
    finally:
        if 'window' in locals():
            window._video_panel.reset_to_empty()
            app.processEvents()
        Path(mp3).unlink(missing_ok=True)
        db_path.unlink(missing_ok=True)

@patch("app.ui.main_window.QThread.start")
def test_ttml_button_lifecycle(mock_thread_start):
    """Verify TTML, EBU-TT, SMPTE-TT, EBU STL, and MCC export button states during launch, transcription, and reset events."""
    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_ttml_buttons.db"
    db_path.unlink(missing_ok=True)
    
    settings = Settings()
    project_svc = ProjectService(db_path)
    
    try:
        window = MainWindow(settings, project_svc)
        
        # 1. Starts disabled
        assert not window._cmb_export_format.isEnabled()
        assert not window._btn_export.isEnabled()
        
        # 2. Becomes enabled after successful transcription
        from app.models.caption import Caption
        window._on_transcribe_done([], [], [Caption(0, 1000, "Mock")])
        assert window._cmb_export_format.isEnabled()
        # button is not enabled until format is selected
        assert not window._btn_export.isEnabled()
        window._cmb_export_format.setCurrentIndex(window._cmb_export_format.findData("ttml"))
        assert window._btn_export.isEnabled()
        
        # 3. Returns to safe disabled on fresh import
        window._load_media("mock_file.mp4")
        assert not window._cmb_export_format.isEnabled()
        assert not window._btn_export.isEnabled()
        
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)


def test_settings_button_exists():
    """Verify the Styles button exists and is always enabled."""
    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_settings.db"
    db_path.unlink(missing_ok=True)
    
    settings = Settings()
    project_svc = ProjectService(db_path)
    
    try:
        window = MainWindow(settings, project_svc)
        
        # Styles button should exist and always be enabled
        assert hasattr(window, '_btn_settings')
        assert window._btn_settings.isEnabled()
        assert "Styles" in window._btn_settings.text()
        
        # Tooltip should clarify export metadata vs downstream rendering
        tooltip = window._btn_settings.toolTip()
        assert "metadata" in tooltip.lower()
        assert "downstream importer" in tooltip.lower()
        assert "Premiere Pro" in tooltip
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)


def test_toolbar_two_row_layout():
    """Verify toolbar is split into workflow and export rows."""
    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_toolbar.db"
    db_path.unlink(missing_ok=True)

    settings = Settings()
    project_svc = ProjectService(db_path)

    try:
        window = MainWindow(settings, project_svc)

        # Workflow row buttons exist
        assert hasattr(window, '_btn_import')
        assert hasattr(window, '_btn_reopen')
        assert hasattr(window, '_btn_recent')
        assert hasattr(window, '_btn_transcribe')
        assert hasattr(window, '_btn_reflow')
        assert hasattr(window, '_btn_rules')
        assert hasattr(window, '_btn_settings')

        assert hasattr(window, '_cmb_export_format')
        assert hasattr(window, '_btn_export')

        # Compact labels — short enough not to clip at 960px
        assert "Import" in window._btn_import.text()
        assert "Reopen" in window._btn_reopen.text()
        assert "Recent" in window._btn_recent.text()
        assert "Regen" in window._btn_reflow.text()
        assert "Styles" in window._btn_settings.text()

        # Export row buttons have short labels (no emoji prefix)
        # Export combo has items
        assert window._cmb_export_format.count() > 3

        # Autosave indicator is visible in bottom bar
        assert hasattr(window, '_autosave_label')
        assert "autosave" in window._autosave_label.text().lower()
        assert "Reopen" in window._autosave_label.text()
        assert "Recent" in window._autosave_label.text()
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)


def test_reopen_button_disabled_no_projects():
    """Verify Reopen is disabled when no projects exist."""
    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_reopen_empty.db"
    db_path.unlink(missing_ok=True)

    settings = Settings()
    project_svc = ProjectService(db_path)

    try:
        window = MainWindow(settings, project_svc)
        assert hasattr(window, '_btn_reopen')
        assert not window._btn_reopen.isEnabled()
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)


def test_reopen_button_enabled_with_project():
    """Verify Reopen is enabled when a saved project exists."""
    from app.models.project import Project

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_reopen_exists.db"
    db_path.unlink(missing_ok=True)

    settings = Settings()
    project_svc = ProjectService(db_path)

    try:
        # Create a project in the DB first
        project = Project(title="Test", media_path="fake.mp4")
        project_svc.create_project(project)

        # Now create the window — reopen should be enabled
        window = MainWindow(settings, project_svc)
        assert window._btn_reopen.isEnabled()
        assert "Test" in window._btn_reopen.toolTip()
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)


def test_reopen_restores_captions_from_db():
    """Verify reopen loads captions from DB and enables export buttons."""
    from app.models.project import Project
    from app.models.caption import Caption
    from unittest.mock import patch

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_reopen_captions.db"
    db_path.unlink(missing_ok=True)

    # Create a dummy media file so reopen does not reject it
    dummy_media = test_dir / "reopen_test.mp4"
    dummy_media.write_bytes(b"\x00" * 64)

    settings = Settings()
    project_svc = ProjectService(db_path)

    try:
        # Seed a project with captions
        project = Project(title="Reopen Test", media_path=str(dummy_media))
        project = project_svc.create_project(project)
        project_svc.save_captions(project.id, [
            Caption(start_ms=0, end_ms=1000, text="Hello"),
            Caption(start_ms=1000, end_ms=2000, text="World"),
        ])

        window = MainWindow(settings, project_svc)

        # Patch video panel to avoid real media loading
        with patch.object(window._video_panel, 'load_media'):
            window._reopen_last_project()

        assert len(window._captions) == 2
        assert window._captions[0].text == "Hello"
        assert window._captions[1].text == "World"
        assert window._cmb_export_format.isEnabled()
        window._cmb_export_format.setCurrentIndex(window._cmb_export_format.findData("srt"))
        assert window._btn_export.isEnabled()
        assert "Reopened" in window._status_label.text()
        assert "autosaved" in window._status_label.text()
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)
        dummy_media.unlink(missing_ok=True)


def test_list_recent_projects():
    """Verify list_recent_projects returns saved projects in order."""
    from app.models.project import Project
    import time

    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_list_recent.db"
    db_path.unlink(missing_ok=True)

    project_svc = ProjectService(db_path)

    try:
        p1 = project_svc.create_project(Project(title="First", media_path="a.mp4"))
        time.sleep(0.05)
        p2 = project_svc.create_project(Project(title="Second", media_path="b.mp4"))

        recent = project_svc.list_recent_projects(limit=5)
        assert len(recent) == 2
        assert recent[0].title == "Second"  # newest first
        assert recent[1].title == "First"
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)


def test_reopen_audio_only_no_export_video():
    """Verify reopen of audio-only project does not enable Export Video."""
    from app.models.project import Project
    from app.models.caption import Caption
    from unittest.mock import patch

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_audio_reopen.db"
    db_path.unlink(missing_ok=True)

    dummy_media = test_dir / "audio_only.mp3"
    dummy_media.write_bytes(b"\x00" * 64)

    settings = Settings()
    project_svc = ProjectService(db_path)

    try:
        # Seed an audio-only project (has_video=False)
        project = Project(title="Audio Only", media_path=str(dummy_media), has_video=False)
        project = project_svc.create_project(project)
        project_svc.save_captions(project.id, [
            Caption(start_ms=0, end_ms=1000, text="Test"),
        ])

        window = MainWindow(settings, project_svc)

        with patch.object(window._video_panel, 'load_media'):
            window._reopen_last_project()

        # Text export buttons should be enabled
        assert window._cmb_export_format.isEnabled()
        window._cmb_export_format.setCurrentIndex(window._cmb_export_format.findData("srt"))
        assert window._btn_export.isEnabled()
        # Export Video must NOT be enabled for audio-only
        window._cmb_export_format.setCurrentIndex(window._cmb_export_format.findData("video"))
        assert not window._btn_export.isEnabled()
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)
        dummy_media.unlink(missing_ok=True)


def test_reopen_video_project_enables_export_video():
    """Verify reopen of video project enables Export Video."""
    from app.models.project import Project
    from app.models.caption import Caption
    from unittest.mock import patch

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_video_reopen.db"
    db_path.unlink(missing_ok=True)

    dummy_media = test_dir / "video_file.mp4"
    dummy_media.write_bytes(b"\x00" * 64)

    settings = Settings()
    project_svc = ProjectService(db_path)

    try:
        # Seed a video project (has_video=True)
        project = Project(title="Video Project", media_path=str(dummy_media), has_video=True)
        project = project_svc.create_project(project)
        project_svc.save_captions(project.id, [
            Caption(start_ms=0, end_ms=1000, text="Test"),
        ])

        window = MainWindow(settings, project_svc)

        with patch.object(window._video_panel, 'load_media'):
            window._reopen_last_project()

        # Export Video should be enabled for video projects
        window._cmb_export_format.setCurrentIndex(window._cmb_export_format.findData("video"))
        assert window._btn_export.isEnabled()
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)
        dummy_media.unlink(missing_ok=True)


def test_has_video_persisted_in_db():
    """Verify has_video flag is correctly persisted and loaded."""
    from app.models.project import Project

    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_has_video_persist.db"
    db_path.unlink(missing_ok=True)

    project_svc = ProjectService(db_path)

    try:
        # Create video project
        p_video = project_svc.create_project(
            Project(title="Vid", media_path="v.mp4", has_video=True)
        )
        # Create audio project
        p_audio = project_svc.create_project(
            Project(title="Aud", media_path="a.mp3", has_video=False)
        )

        loaded_video = project_svc.load_project(p_video.id)
        loaded_audio = project_svc.load_project(p_audio.id)

        assert loaded_video.has_video is True
        assert loaded_audio.has_video is False
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)


def test_save_captions_updates_recency():
    """Verify save_captions touches updated_at for project recency."""
    from app.models.project import Project
    from app.models.caption import Caption
    import time

    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_recency.db"
    db_path.unlink(missing_ok=True)

    project_svc = ProjectService(db_path)

    try:
        p1 = project_svc.create_project(Project(title="Older", media_path="a.mp4"))
        time.sleep(0.05)
        p2 = project_svc.create_project(Project(title="Newer", media_path="b.mp4"))

        # p2 is latest
        assert project_svc.get_latest_project().id == p2.id

        # Save captions on p1 — should make p1 the latest
        time.sleep(0.05)
        project_svc.save_captions(p1.id, [Caption(0, 1000, "update")])

        latest = project_svc.get_latest_project()
        assert latest.id == p1.id
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)


def test_reopen_button_refreshes_after_import_done():
    """Verify Reopen becomes enabled after a project is created in-session."""
    from app.models.project import Project
    from unittest.mock import patch

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_refresh.db"
    db_path.unlink(missing_ok=True)

    settings = Settings()
    project_svc = ProjectService(db_path)

    try:
        window = MainWindow(settings, project_svc)

        # Initially disabled — no projects
        assert not window._btn_reopen.isEnabled()

        # Simulate what _on_import_done does: create a project and refresh
        window._project = Project(title="Fresh Import", media_path="test.mp4")
        window._project.has_video = True
        window._project = project_svc.create_project(window._project)
        window._refresh_reopen_button()

        # Now reopen should be enabled with the new project title
        assert window._btn_reopen.isEnabled()
        assert "Fresh Import" in window._btn_reopen.toolTip()
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)


def test_recent_projects_menu_exists():
    """Verify Recent button and menu exist."""
    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_recent_menu.db"
    db_path.unlink(missing_ok=True)

    settings = Settings()
    project_svc = ProjectService(db_path)

    try:
        window = MainWindow(settings, project_svc)
        assert hasattr(window, '_btn_recent')
        assert hasattr(window, '_recent_menu')
        # With no projects, menu should have a disabled placeholder
        actions = window._recent_menu.actions()
        assert len(actions) == 1
        assert not actions[0].isEnabled()
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)


def test_recent_projects_menu_populated():
    """Verify Recent menu lists saved projects."""
    from app.models.project import Project
    import time

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_recent_pop.db"
    db_path.unlink(missing_ok=True)

    settings = Settings()
    project_svc = ProjectService(db_path)

    try:
        project_svc.create_project(Project(title="Alpha", media_path="a.mp4"))
        time.sleep(0.05)
        project_svc.create_project(Project(title="Beta", media_path="b.mp4"))

        window = MainWindow(settings, project_svc)

        actions = window._recent_menu.actions()
        assert len(actions) == 2
        # Most recent first
        assert "Beta" in actions[0].text()
        assert "Alpha" in actions[1].text()
        # All should be enabled
        assert actions[0].isEnabled()
        assert actions[1].isEnabled()
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)


def test_open_project_by_id():
    """Verify _open_project_by_id restores the correct project."""
    from app.models.project import Project
    from app.models.caption import Caption
    from unittest.mock import patch

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_open_by_id.db"
    db_path.unlink(missing_ok=True)

    dummy_a = test_dir / "project_a.mp4"
    dummy_b = test_dir / "project_b.mp4"
    dummy_a.write_bytes(b"\x00" * 64)
    dummy_b.write_bytes(b"\x00" * 64)

    settings = Settings()
    project_svc = ProjectService(db_path)

    try:
        p_a = project_svc.create_project(
            Project(title="ProjectA", media_path=str(dummy_a), has_video=True)
        )
        project_svc.save_captions(p_a.id, [Caption(0, 1000, "A caption")])

        p_b = project_svc.create_project(
            Project(title="ProjectB", media_path=str(dummy_b), has_video=False)
        )
        project_svc.save_captions(p_b.id, [Caption(0, 2000, "B caption")])

        window = MainWindow(settings, project_svc)

        # Open the older project (A) by ID, not the latest (B)
        with patch.object(window._video_panel, 'load_media'):
            window._open_project_by_id(p_a.id)

        assert window._project.title == "ProjectA"
        assert len(window._captions) == 1
        assert window._captions[0].text == "A caption"
        window._cmb_export_format.setCurrentIndex(window._cmb_export_format.findData("video"))
        assert window._btn_export.isEnabled()  # has_video=True

        # Now open project B
        with patch.object(window._video_panel, 'load_media'):
            window._open_project_by_id(p_b.id)

        assert window._project.title == "ProjectB"
        assert window._captions[0].text == "B caption"
        # has_video=False — Export Video must be disabled after switching
        window._cmb_export_format.setCurrentIndex(window._cmb_export_format.findData("video"))
        assert not window._btn_export.isEnabled()
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)
        dummy_a.unlink(missing_ok=True)
        dummy_b.unlink(missing_ok=True)


def test_video_export_handler_live_widgets():
    """Verify _do_export_video does not reference dead widgets and correctly cycles live ones."""
    from app.models.project import Project
    from app.models.caption import Caption
    from unittest.mock import patch

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_export_video.db"
    db_path.unlink(missing_ok=True)

    dummy_media = test_dir / "export_test.mp4"
    dummy_media.write_bytes(b"\x00" * 64)

    settings = Settings()
    project_svc = ProjectService(db_path)

    try:
        project = project_svc.create_project(
            Project(title="ExportTest", media_path=str(dummy_media), has_video=True)
        )
        project_svc.save_captions(project.id, [Caption(0, 1000, "Caption")])

        window = MainWindow(settings, project_svc)
        with patch.object(window._video_panel, 'load_media'):
            window._open_project_by_id(project.id)

        # Mock QFileDialog, QThread, and Worker to test the UI flow securely
        with patch("app.ui.main_window.QFileDialog.getSaveFileName", return_value=(str(test_dir / "out.mp4"), "MP4 Files (*.mp4)")), \
             patch("app.ui.main_window._ExportWorker"), \
             patch("app.ui.main_window.QThread"), \
             patch("app.ui.main_window.QMessageBox.critical"):
            
            # Select video format
            window._cmb_export_format.setCurrentIndex(window._cmb_export_format.findData("video"))
            assert window._btn_export.isEnabled()
            
            # Fire the handler
            window._do_export()
            
            # Handlers should disable the combo and export button
            assert not window._cmb_export_format.isEnabled()
            assert not window._btn_export.isEnabled()
            
            # Simulate completion
            window._on_export_done(str(test_dir / "out.mp4"))
            
            # Must re-enable
            assert window._cmb_export_format.isEnabled()
            assert window._btn_export.isEnabled()
            
            # Simulate error (disable first to prove it changes)
            window._cmb_export_format.setEnabled(False)
            window._btn_export.setEnabled(False)
            window._on_export_error("Test Error")
            
            assert window._cmb_export_format.isEnabled()
            assert window._btn_export.isEnabled()

    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)
        dummy_media.unlink(missing_ok=True)


def test_cancel_transcription_restores_ui():
    """Verify cancelling transcription restores workflow UI."""
    from app.models.project import Project
    from unittest.mock import patch

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_cancel_transcribe.db"
    db_path.unlink(missing_ok=True)
    dummy_media = test_dir / "transcribe_cancel.mp4"
    dummy_media.write_bytes(b"\x00" * 64)
    settings = Settings()
    project_svc = ProjectService(db_path)
    try:
        project = project_svc.create_project(
            Project(title="TTest", media_path=str(dummy_media), audio_path=str(dummy_media))
        )
        window = MainWindow(settings, project_svc)
        with patch.object(window._video_panel, 'load_media'):
            window._open_project_by_id(project.id)

        with patch("app.ui.main_window._TranscribeWorker"), \
             patch("app.ui.main_window.QThread"):
            window._run_transcribe()
            assert not window._btn_transcribe.isEnabled()
            assert not window._btn_cancel_job.isHidden()

            # Click cancel
            window._btn_cancel_job.click()

            # Simulate worker acknowledging cancel
            window._on_job_cancelled()

            assert window._btn_cancel_job.isHidden()
            assert window._btn_transcribe.isEnabled()
            assert "cancelled" in window._status_label.text().lower()
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)
        dummy_media.unlink(missing_ok=True)


def test_cancel_export_restores_ui():
    """Verify cancelling video export restores workflow UI."""
    from app.models.project import Project
    from app.models.caption import Caption
    from unittest.mock import patch

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_cancel_export.db"
    db_path.unlink(missing_ok=True)
    dummy_media = test_dir / "export_cancel.mp4"
    dummy_media.write_bytes(b"\x00" * 64)
    settings = Settings()
    project_svc = ProjectService(db_path)
    try:
        project = project_svc.create_project(
            Project(title="ETest", media_path=str(dummy_media), has_video=True)
        )
        project_svc.save_captions(project.id, [Caption(0, 1000, "C")])

        window = MainWindow(settings, project_svc)
        with patch.object(window._video_panel, 'load_media'):
            window._open_project_by_id(project.id)

        with patch("app.ui.main_window.QFileDialog.getSaveFileName", return_value=(str(test_dir / "out.mp4"), "MP4")), \
             patch("app.ui.main_window._ExportWorker"), \
             patch("app.ui.main_window.QThread"):
            
            window._cmb_export_format.setCurrentIndex(window._cmb_export_format.findData("video"))
            window._do_export()
            
            assert not window._cmb_export_format.isEnabled()
            assert not window._btn_export.isEnabled()
            assert not window._btn_cancel_job.isHidden()

            # Click cancel
            window._btn_cancel_job.click()

            # Simulate worker acknowledging cancel
            window._on_job_cancelled()

            assert window._btn_cancel_job.isHidden()
            assert window._cmb_export_format.isEnabled()
            assert window._btn_export.isEnabled()
            assert "cancelled" in window._status_label.text().lower()
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)
        dummy_media.unlink(missing_ok=True)


def test_cancel_import_restores_ui():
    """Verify cancelling import restores workflow UI."""
    from app.models.project import Project
    from unittest.mock import patch

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_cancel_import.db"
    db_path.unlink(missing_ok=True)
    dummy_media = test_dir / "import_cancel.mp4"
    dummy_media.write_bytes(b"\x00" * 64)
    settings = Settings()
    project_svc = ProjectService(db_path)
    try:
        window = MainWindow(settings, project_svc)
        
        with patch("app.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(dummy_media), "")), \
             patch("app.ui.main_window._ImportWorker"), \
             patch("app.ui.main_window.QThread"):
            
            window._import_media()
            assert not window._btn_import.isEnabled()
            assert not window._progress.isHidden()
            assert not window._btn_cancel_job.isHidden()
            
            # Click cancel
            window._btn_cancel_job.click()
            
            # Simulate worker acknowledging cancel
            token = window._import_guard.token
            window._on_import_cancelled(token)
            
            assert window._progress.isHidden()
            assert window._btn_cancel_job.isHidden()
            assert window._btn_import.isEnabled()
            assert window._project is None
            assert not window._import_watchdog.isActive()
            assert "cancelled" in window._status_label.text().lower()
            
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)
        dummy_media.unlink(missing_ok=True)


def test_cancel_import_during_probe_restores_ui():
    """Verify cancelling import during the probe phase restores workflow UI."""
    from app.utils.errors import CancelledError
    from unittest.mock import patch
    import time

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_cancel_probe.db"
    db_path.unlink(missing_ok=True)
    dummy_media = test_dir / "import_probe_cancel.mp4"
    dummy_media.write_bytes(b"\x00" * 64)
    settings = Settings()
    project_svc = ProjectService(db_path)
    try:
        window = MainWindow(settings, project_svc)
        
        # Simulate one slow ffprobe call that periodically checks cancellation.
        def mock_probe_media(path, cancel_check=None):
            # Simulate a slow probe that eventually checks cancel_check
            for _ in range(50):
                if cancel_check and cancel_check():
                    raise CancelledError("Import cancelled.")
                time.sleep(0.01)
            return {"format": {"duration": "1.0"}, "streams": []}

        with patch("app.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(dummy_media), "")), \
             patch("app.ui.main_window.media_service.probe_media", side_effect=mock_probe_media), \
             patch("app.ui.main_window.media_service.extract_audio_wav") as mock_extract:
            
            # Use real QThread and Worker to prove real signaling
            window._import_media()
            assert not window._btn_import.isEnabled()
            assert not window._btn_cancel_job.isHidden()
            
            # Give the thread a moment to start the mock probe
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            time.sleep(0.05)

            # Click cancel while the worker is in the mock probe phase
            thread_ref = window._import_thread
            window._btn_cancel_job.click()
            
            # Wait for worker thread to finish processing the cancellation
            for _ in range(50):
                QApplication.processEvents()
                if not thread_ref.isRunning():
                    break
                time.sleep(0.05)
                
            # Verify extract was never called because it cancelled during probe
            mock_extract.assert_not_called()
            
            # Verify UI restored properly
            assert window._progress.isHidden()
            assert window._btn_cancel_job.isHidden()
            assert window._btn_import.isEnabled()
            assert window._project is None
            assert not window._import_watchdog.isActive()
            assert "cancelled" in window._status_label.text().lower()
            
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)
        dummy_media.unlink(missing_ok=True)


def test_transcribe_offline_model_download_failure():
    """Verify that a model download failure is caught and presented as a clean error."""
    from app.models.project import Project
    from unittest.mock import patch
    import time

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_model_fail.db"
    db_path.unlink(missing_ok=True)
    dummy_media = test_dir / "transcribe_model_fail.mp4"
    dummy_media.write_bytes(b"\x00" * 64)
    settings = Settings()
    project_svc = ProjectService(db_path)
    try:
        project = project_svc.create_project(
            Project(title="FailTest", media_path=str(dummy_media), audio_path=str(dummy_media))
        )
        window = MainWindow(settings, project_svc)
        with patch.object(window._video_panel, 'load_media'):
            window._open_project_by_id(project.id)

        # Mock WhisperModel to raise a simulated offline error
        def mock_whisper_model(*args, **kwargs):
            raise Exception("huggingface_hub.utils.LocalEntryNotFoundError: connection failed")

        with patch("app.services.transcription_service.WhisperModel", side_effect=mock_whisper_model), \
             patch("app.ui.main_window.QMessageBox.critical") as mock_msg:
             
            # Use real QThread to exercise the error propagation path
            window._run_transcribe()
            
            # Wait for thread to finish
            from PySide6.QtWidgets import QApplication
            for _ in range(50):
                QApplication.processEvents()
                if hasattr(window, "_transcribe_worker_ref") and hasattr(window, "_transcribe_thread") and not window._transcribe_thread.isRunning():
                    break
                time.sleep(0.05)
                
            QApplication.processEvents()
            
            # Ensure the messagebox fired
            mock_msg.assert_called_once()
            args, kwargs = mock_msg.call_args
            # args[2] is the message
            msg = args[2]
            
            # Assert it's the friendly error, not a traceback
            assert "Failed to download or locate" in msg
            assert "Traceback" not in msg
            
            # UI should be restored to idle
            assert window._progress.isHidden()
            assert window._btn_cancel_job.isHidden()
            assert window._btn_transcribe.isEnabled()
            assert "error" in window._status_label.text().lower()

    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)
        dummy_media.unlink(missing_ok=True)


def test_model_cache_respects_full_config():
    """Verify that the transcription model cache invalidates when device or compute_type changes."""
    from unittest.mock import patch, MagicMock
    from app.services import transcription_service

    # Clean the global cache state before we begin
    transcription_service._model = None
    transcription_service._model_config = None

    mock_whisper = MagicMock()

    try:
        with patch("app.services.transcription_service.WhisperModel", new=mock_whisper):
            # Call 1: New configuration
            transcription_service._get_model("base", "auto", "int8")
            assert mock_whisper.call_count == 1
            
            # Call 2: Same configuration -> should hit cache and not instantiate
            transcription_service._get_model("base", "auto", "int8")
            assert mock_whisper.call_count == 1
            
            # Call 3: Change device -> should invalidate cache and instantiate
            transcription_service._get_model("base", "cpu", "int8")
            assert mock_whisper.call_count == 2
            
            # Call 4: Change compute_type -> should invalidate cache and instantiate
            transcription_service._get_model("base", "cpu", "float16")
            assert mock_whisper.call_count == 3
            
            # Call 5: Same configuration again -> should hit cache
            transcription_service._get_model("base", "cpu", "float16")
            assert mock_whisper.call_count == 3
            
    finally:
        # Clean up to prevent side effects on other tests
        transcription_service._model = None
        transcription_service._model_config = None


def test_import_proxy_fallback_generation():
    """Verify that unsupported media triggers proxy generation and playback fallback."""
    from app.models.project import Project
    from unittest.mock import patch, MagicMock
    from tests.test_gui_import import _generate_synthetic_mp4
    import time

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_proxy.db"
    db_path.unlink(missing_ok=True)
    
    dummy_media = test_dir / "bad_codec.mp4"
    _generate_synthetic_mp4(str(dummy_media), 1.0)

    settings = Settings()
    project_svc = ProjectService(db_path)

    try:
        window = MainWindow(settings, project_svc)
        
        def mock_generate_proxy(media_path, proxy_path, width=640, cancel_check=None):
            pass

        probe_info = {
            "format": {"duration": "5.0"},
            "streams": [{
                "codec_type": "video",
                "codec_name": "prores",
                "avg_frame_rate": "30/1",
            }],
        }

        with patch("app.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(dummy_media), "")), \
             patch("app.services.media_service.probe_media", return_value=probe_info), \
             patch("app.services.media_service.generate_proxy", side_effect=mock_generate_proxy) as mock_gen_proxy, \
             patch("app.services.media_service.extract_audio_wav"), \
             patch.object(window._video_panel, 'load_media') as mock_load_media:
             
            window._import_media()
            
            # Wait for thread to finish robustly
            from PySide6.QtCore import QElapsedTimer
            
            import_finished = False
            import_error = False
            
            def on_done(*args):
                nonlocal import_finished
                import_finished = True
                
            def on_error(msg, token):
                nonlocal import_finished, import_error
                import_finished = True
                import_error = True
                print("Worker error:", msg)

            window._import_worker_ref.finished.connect(on_done)
            window._import_worker_ref.error.connect(on_error)
            thread_ref = window._import_thread
            
            from PySide6.QtWidgets import QApplication
            timer = QElapsedTimer()
            timer.start()
            
            while not import_finished and timer.elapsed() < 15000:
                QApplication.processEvents()
                
            assert import_finished, "Import worker did not finish within timeout"
            assert not import_error, "Import worker emitted an error"
            
            while thread_ref.isRunning() and timer.elapsed() < 18000:
                QApplication.processEvents()
            
            # Assert proxy generation was called
            mock_gen_proxy.assert_called_once()
            args, _ = mock_gen_proxy.call_args
            assert args[0] == str(dummy_media)
            proxy_out_path = args[1]
            assert "proxy.mp4" in proxy_out_path
            
            # Assert video panel was loaded with the proxy path, not the original
            mock_load_media.assert_called_once()
            load_args, load_kwargs = mock_load_media.call_args
            assert load_args[0] == proxy_out_path
            assert load_kwargs["has_video"] is True
            
            # Assert project database saved the proxy path
            project = window._project
            assert project is not None
            assert project.proxy_path == proxy_out_path

    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)
        dummy_media.unlink(missing_ok=True)


def test_cancel_during_proxy_generation_restores_ui():
    """Verify cancelling import during proxy generation restores workflow UI."""
    from app.utils.errors import CancelledError
    from unittest.mock import patch
    from tests.test_gui_import import _generate_synthetic_mp4
    from PySide6.QtCore import QElapsedTimer
    from PySide6.QtWidgets import QApplication
    import time

    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_cancel_proxy.db"
    db_path.unlink(missing_ok=True)
    dummy_media = test_dir / "import_proxy_cancel.mp4"
    _generate_synthetic_mp4(str(dummy_media), 1.0)
    
    settings = Settings()
    project_svc = ProjectService(db_path)
    
    try:
        window = MainWindow(settings, project_svc)
        
        def mock_generate_proxy(media_path, proxy_path, width=640, cancel_check=None):
            # Simulate a slow generation that periodically checks cancel_check
            for _ in range(50):
                if cancel_check and cancel_check():
                    raise CancelledError("Import cancelled.")
                time.sleep(0.01)

        probe_info = {
            "format": {"duration": "1.0"},
            "streams": [{
                "codec_type": "video",
                "codec_name": "prores",
                "avg_frame_rate": "30/1",
            }],
        }

        with patch("app.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(dummy_media), "")), \
             patch("app.ui.main_window.media_service.probe_media", return_value=probe_info), \
             patch("app.ui.main_window.media_service.generate_proxy", side_effect=mock_generate_proxy) as mock_gen_proxy, \
             patch("app.ui.main_window.media_service.extract_audio_wav") as mock_extract:
            
            # Start import
            window._import_media()
            assert not window._btn_import.isEnabled()
            assert not window._btn_cancel_job.isHidden()
            
            # Give the thread a moment to start the mock proxy generation
            QApplication.processEvents()
            time.sleep(0.05)

            # Click cancel while the worker is inside mock_generate_proxy
            thread_ref = window._import_thread
            window._btn_cancel_job.click()

            # Wait for worker thread to finish
            timer = QElapsedTimer()
            timer.start()
            
            while thread_ref.isRunning() and timer.elapsed() < 10000:
                QApplication.processEvents()

            assert not thread_ref.isRunning(), "Import thread did not terminate within timeout"
            QApplication.processEvents()

            # Verify generate_proxy was called but extract_audio_wav was NOT
            mock_gen_proxy.assert_called_once()
            mock_extract.assert_not_called()
            
            # Verify UI restored properly
            assert window._btn_import.isEnabled()
            assert window._btn_cancel_job.isHidden()
            assert window._progress.isHidden()
            assert not window._import_guard.is_active

    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)
        dummy_media.unlink(missing_ok=True)


def test_gui_export_ass_format_label():
    """Verify ASS export combobox accurately exposes the libass-specific warning."""
    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_ass_label.db"
    db_path.unlink(missing_ok=True)
        
    try:
        settings = Settings(str(db_path))
        project_svc = ProjectService(str(db_path))
        window = MainWindow(settings, project_svc)
        
        # Verify the combobox has the ASS option
        ass_idx = window._cmb_export_format.findData("ass")
        assert ass_idx >= 0
        
        # Verify the label is correct
        label = window._cmb_export_format.itemText(ass_idx)
        assert label == "ASS (libass-safe text)"
        
        # Verify the tooltip is correct
        tooltip = window._cmb_export_format.itemData(ass_idx, Qt.ToolTipRole)
        assert tooltip and "Literal {} braces require a libass-compatible player" in tooltip
    finally:
        project_svc.close()
        db_path.unlink(missing_ok=True)


@patch("app.ui.main_window.QMessageBox.critical")
@patch("app.services.media_service._resolve_tool")
def test_gui_import_missing_media_tool(mock_resolve, mock_msgbox):
    """Verify that a missing media tool during import triggers a friendly user-facing error."""
    from app.services.media_service import MediaToolNotFoundError
    
    # Force _resolve_tool to fail explicitly
    mock_resolve.side_effect = MediaToolNotFoundError(
        "Required media tool 'ffmpeg' not found.\n\n"
        "If you are using the packaged application, please download ffmpeg "
        "and place 'ffmpeg.exe' in the same folder as the Lil Word app, "
        "or ensure it is available on your system PATH."
    )
    
    app = _ensure_app()
    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_missing_tool.db"
    db_path.unlink(missing_ok=True)
    mp4 = str(test_dir / "gui_import_missing.mp4")
    
    try:
        _generate_synthetic_mp4(mp4, 1.0)
        
        settings = Settings()
        project_svc = ProjectService(db_path)
        window = MainWindow(settings, project_svc)
        
        # Start import
        window._load_media(mp4)
        
        # Wait for the worker thread to finish
        import_finished = False
        
        def on_done(*args):
            nonlocal import_finished
            import_finished = True
            
        def on_error(*args):
            nonlocal import_finished
            import_finished = True

        window._import_worker_ref.finished.connect(on_done)
        window._import_worker_ref.error.connect(on_error)
        
        timer = QElapsedTimer()
        timer.start()
        
        while not import_finished and timer.elapsed() < 5000:
            app.processEvents()
            
        assert import_finished, "Import worker did not finish within timeout"
        
        # Wait for thread shutdown
        while window._import_thread.isRunning() and timer.elapsed() < 8000:
            app.processEvents()
            
        # Assert the GUI raised the clean error
        assert mock_msgbox.call_count == 1
        msg_args = mock_msgbox.call_args[0]
        assert msg_args[1] == "Import Error"
        assert "Required media tool 'ffmpeg' not found." in msg_args[2]
        assert "traceback" not in msg_args[2].lower(), "Error should not contain a raw stack trace."
        
        project_svc.close()
        
    finally:
        if 'window' in locals():
            window._video_panel.reset_to_empty()
            app.processEvents()
        Path(mp4).unlink(missing_ok=True)
        db_path.unlink(missing_ok=True)
