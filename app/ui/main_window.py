"""Main window – top-level UI assembling video panel, caption panel, and toolbar."""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, Slot, QObject, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QProgressBar, QFileDialog, QMessageBox,
    QStatusBar, QApplication, QMenu, QSizePolicy, QComboBox,
)
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from app.models.caption import Caption, TranscriptWord
from app.models.project import Project
from app.services import media_service
from app.services.caption_engine import normalize_captions
from app.services.caption_job import (
    export_burned_caption_video,
    generate_caption_blocks,
    prepare_caption_media,
    transcribe_and_generate_captions,
)
from app.ui.caption_rules_dialog import CaptionRulesDialog
from app.ui.export_settings_dialog import ExportSettingsDialog
from app.services.alignment_service import refine_timing
from app.services.export_service import export_srt, export_ass
from app.services.project_service import ProjectService
from app.ui.video_panel import VideoPanel
from app.ui.caption_panel import CaptionPanel
from app.utils.settings import Settings
from app.utils.export_helpers import build_export_name, build_audio_output_path
from app.utils.import_session import ImportSessionGuard
from app.utils.errors import CancelledError, ModelDownloadError

log = logging.getLogger(__name__)

# Build label – bump this on each coding round so the user/review-agent can
# confirm the launched app is running the current source.
_BUILD_LABEL = "r94-2026-05-06"

# Import watchdog timeout (seconds).  If the background import worker has not
# completed within this time, the GUI fires an error and re-enables Import.
_IMPORT_WATCHDOG_SECS = 150


# ── Worker for background media import ───────────────────────────────────────

class _ImportWorker(QObject):
    """Probes media and extracts audio in a background thread."""
    finished = Signal(str, int, bool, str, int, str)  # audio_path, duration_ms, has_video, proxy_path, media_fps, token
    error = Signal(str, str)
    progress = Signal(str)
    cancelled = Signal(str)

    def __init__(self, media_path: str, audio_out_path: str, token: str):
        super().__init__()
        self._media_path = media_path
        self._audio_out_path = audio_out_path
        self._token = token
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    @Slot()
    def run(self):
        try:
            log.info("[import] worker started  media=%s  audio_out=%s",
                     self._media_path, self._audio_out_path)
            info = prepare_caption_media(
                self._media_path,
                audio_path=self._audio_out_path,
                work_dir=str(Path(self._audio_out_path).parent),
                progress_callback=lambda progress: self.progress.emit(progress.message),
                cancel_check=lambda: self._is_cancelled,
            )
            log.info("[import] worker finished successfully")
            self.finished.emit(
                info.audio_path,
                info.media_duration_ms,
                info.has_video,
                info.proxy_path,
                info.media_fps if info.media_fps is not None else 0,
                self._token,
            )
        except CancelledError:
            log.info("[import] worker cancelled")
            self.cancelled.emit(self._token)
        except media_service.MediaToolNotFoundError as exc:
            log.error("[import] worker exception: %s", exc)
            self.error.emit(str(exc), self._token)
        except Exception as exc:
            log.error("[import] worker exception: %s", exc, exc_info=True)
            self.error.emit(f"{exc}\n{traceback.format_exc()}", self._token)


# ── Worker for background transcription ──────────────────────────────────────

class _TranscribeWorker(QObject):
    """Runs transcription + caption generation in a background thread."""
    finished = Signal(list, list, list)  # segments, words, captions
    error = Signal(str)
    progress = Signal(str)
    cancelled = Signal()

    def __init__(self, audio_path: str, settings: Settings, media_duration_ms: int = 0):
        super().__init__()
        self._audio_path = audio_path
        self._settings = settings
        self._media_duration_ms = media_duration_ms
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    @Slot()
    def run(self):
        try:
            segments, words, captions = transcribe_and_generate_captions(
                self._audio_path,
                self._settings,
                media_duration_ms=self._media_duration_ms,
                progress_callback=lambda progress: self.progress.emit(progress.message),
                cancel_check=lambda: self._is_cancelled,
            )
            self.finished.emit(segments, words, captions)
        except CancelledError:
            self.cancelled.emit()
        except media_service.MediaToolNotFoundError as exc:
            log.error("Transcribe worker missing tool: %s", exc)
            self.error.emit(str(exc))
        except ModelDownloadError as exc:
            log.error("Model download error", exc_info=True)
            self.error.emit(str(exc))
        except Exception as exc:
            log.error("Transcribe worker error", exc_info=True)
            self.error.emit(f"{exc}\n{traceback.format_exc()}")


class _ExportWorker(QObject):
    """Runs burned-in video export in a background thread."""
    finished = Signal(str)
    error = Signal(str)
    cancelled = Signal()

    def __init__(self, media_path: str, captions: list[Caption], out_path: str):
        super().__init__()
        self._media_path = media_path
        self._captions = captions
        self._out_path = out_path
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    @Slot()
    def run(self):
        try:
            export_burned_caption_video(
                self._media_path,
                self._captions,
                self._out_path,
                cancel_check=lambda: self._is_cancelled,
            )
            self.finished.emit(self._out_path)
        except CancelledError:
            self.cancelled.emit()
        except media_service.MediaToolNotFoundError as exc:
            log.error("Export worker missing tool: %s", exc)
            self.error.emit(str(exc))
        except Exception as exc:
            log.error("Export worker error", exc_info=True)
            self.error.emit(f"{exc}\n{traceback.format_exc()}")


# ── Main Window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """Lil Word main application window."""

    def __init__(self, settings: Settings, project_svc: ProjectService):
        super().__init__()
        self._settings = settings
        self._project_svc = project_svc
        self._project: Optional[Project] = None
        self._captions: list[Caption] = []
        self._words: list[TranscriptWord] = []
        self._segments: list[dict] = []
        self._worker_thread: Optional[QThread] = None
        self._media_duration_ms: int = 0
        self._media_fps: int | None = None
        self._import_guard = ImportSessionGuard()

        self.setWindowTitle(f"Lil Word  [{_BUILD_LABEL}]")
        self.setMinimumSize(960, 600)
        self.setAcceptDrops(True)

        self._build_ui()
        self._connect_signals()
        self._set_status(f"Ready – drop a media file or click Import  (build {_BUILD_LABEL})")

        # Import watchdog timer — fires if the import worker exceeds the timeout
        self._import_watchdog = QTimer(self)
        self._import_watchdog.setSingleShot(True)
        self._import_watchdog.timeout.connect(self._on_import_watchdog)

        log.info("MainWindow created  build=%s  python=%s  source=%s",
                 _BUILD_LABEL, sys.executable, Path(__file__).resolve())

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        # ── Row 1: Workflow actions (compact labels for 960px) ───────────
        workflow_row = QHBoxLayout()
        workflow_row.setSpacing(4)

        self._btn_import = QPushButton("📂 Import")
        self._btn_reopen = QPushButton("📂 Reopen")
        self._btn_reopen.setToolTip("Reopen the most recently saved project.")
        self._btn_recent = QPushButton("📂 Recent")
        self._btn_recent.setToolTip("Browse and open a recent project.")
        self._recent_menu = QMenu(self)
        self._btn_recent.setMenu(self._recent_menu)

        sep1 = QLabel("│")
        sep1.setStyleSheet("color: #888; margin: 0 2px;")

        self._btn_transcribe = QPushButton("🎙 Transcribe")
        self._btn_reflow = QPushButton("🔄 Regen")
        self._btn_reflow.setToolTip("Rebuild caption grouping/timing from the original transcript data using current rules.")

        sep2 = QLabel("│")
        sep2.setStyleSheet("color: #888; margin: 0 2px;")

        self._btn_rules = QPushButton("⚙️ Rules")
        self._btn_rules.setToolTip("Caption timing rules with named presets. Load a preset, fine-tune, save your own.")
        self._btn_settings = QPushButton("🎨 Styles")
        self._btn_settings.setToolTip("Design caption looks, save style presets with live preview, and configure Whisper settings. Note: Styles dictate exported metadata; final visual fidelity depends on downstream importer (e.g. Premiere Pro).")

        for btn in [self._btn_import, self._btn_reopen, self._btn_recent,
                     self._btn_transcribe, self._btn_reflow,
                     self._btn_rules, self._btn_settings]:
            btn.setFixedHeight(32)
            btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        for widget in [self._btn_import, self._btn_reopen, self._btn_recent,
                        sep1,
                        self._btn_transcribe, self._btn_reflow,
                        sep2,
                        self._btn_rules, self._btn_settings]:
            workflow_row.addWidget(widget)
        workflow_row.addStretch()

        # ── Row 2: Export actions ────────────────────────────────────────
        export_row = QHBoxLayout()
        export_row.setSpacing(4)
        
        self._cmb_export_format = QComboBox()
        self._cmb_export_format.addItem("Select export format...", "")
        self._cmb_export_format.addItem("🎬 Video (Hardsubs)", "video")
        self._cmb_export_format.addItem("TTML (Rich style)", "ttml")
        self._cmb_export_format.addItem("EBU-TT (Rich style)", "ebu_tt")
        self._cmb_export_format.addItem("SMPTE-TT (Rich style)", "smpte_tt")
        self._cmb_export_format.addItem("SRT (Text only)", "srt")
        self._cmb_export_format.addItem("ASS (libass-safe text)", "ass")
        self._cmb_export_format.setItemData(
            self._cmb_export_format.count() - 1,
            "Note: Literal {} braces require a libass-compatible player (e.g. VLC, mpv, or burned video) to render correctly.",
            Qt.ToolTipRole
        )
        self._cmb_export_format.addItem("EBU STL (Limited style)", "ebu_stl")
        self._cmb_export_format.addItem("MCC (Limited style)", "mcc")
        self._cmb_export_format.setFixedHeight(28)

        self._btn_export = QPushButton("Export")
        self._btn_export.setFixedHeight(28)
        self._btn_export.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        export_label = QLabel("Export:")
        export_label.setStyleSheet("font-weight: bold; margin-right: 2px;")
        export_row.addWidget(export_label)
        export_row.addWidget(self._cmb_export_format)
        export_row.addWidget(self._btn_export)
        export_row.addStretch()

        # Initially disable actions until media is loaded
        self._btn_transcribe.setEnabled(False)
        self._btn_reflow.setEnabled(False)
        self._cmb_export_format.setEnabled(False)
        self._btn_export.setEnabled(False)

        # Enable reopen only if a previous project exists
        self._refresh_reopen_button()

        # Main split: video (left) | captions (right)
        self._splitter = QSplitter(Qt.Horizontal)
        self._video_panel = VideoPanel()
        self._video_panel.set_style_settings(self._settings)
        self._caption_panel = CaptionPanel()
        self._splitter.addWidget(self._video_panel)
        self._splitter.addWidget(self._caption_panel)
        self._splitter.setSizes([550, 400])

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setVisible(False)
        self._progress.setFixedHeight(18)

        self._status_label = QLabel("")

        self._btn_cancel_job = QPushButton("Cancel")
        self._btn_cancel_job.setVisible(False)
        self._btn_cancel_job.setFixedHeight(22)

        # Persistent autosave indicator — always visible in the status bar
        self._autosave_label = QLabel("💾 Projects autosave  •  Use Reopen / Recent to resume")
        self._autosave_label.setStyleSheet(
            "color: #888; font-size: 11px; padding-left: 8px;"
        )

        bottom = QHBoxLayout()
        bottom.addWidget(self._status_label, 1)
        bottom.addWidget(self._progress)
        bottom.addWidget(self._btn_cancel_job)
        bottom.addWidget(self._autosave_label)

        layout = QVBoxLayout(central)
        layout.addLayout(workflow_row)
        layout.addLayout(export_row)
        layout.addWidget(self._splitter, 1)
        layout.addLayout(bottom)

        # Catch drops that would otherwise be consumed by child widgets.
        # The DropZoneWidget handles its own drops directly; these filters
        # cover the rest of the window surface (splitter, caption side, etc.).
        targets = [central, self._splitter]
        targets.extend(self._caption_panel.get_drop_targets())
        for t in targets:
            t.setAcceptDrops(True)
            t.installEventFilter(self)

    def _connect_signals(self):
        self._btn_import.clicked.connect(self._import_media)
        self._btn_reopen.clicked.connect(self._reopen_last_project)
        self._btn_transcribe.clicked.connect(self._run_transcribe)
        self._btn_reflow.clicked.connect(self._reflow_captions)
        self._btn_rules.clicked.connect(self._open_rules)
        self._btn_settings.clicked.connect(self._open_settings)
        self._cmb_export_format.currentIndexChanged.connect(self._on_export_combo_changed)
        self._btn_export.clicked.connect(self._do_export)
        self._btn_cancel_job.clicked.connect(self._on_cancel_job)

        self._caption_panel.caption_clicked.connect(self._video_panel.seek_to)
        self._video_panel.position_changed.connect(self._caption_panel.set_playhead)
        self._caption_panel.captions_changed.connect(self._on_captions_edited)
        self._caption_panel.split_feedback.connect(self._on_split_feedback)
        self._caption_panel.merge_feedback.connect(self._on_merge_feedback)
        self._caption_panel.reflow_selected_requested.connect(self._reflow_selected)

        # Connect the drop-zone signal from the video panel
        self._video_panel.file_dropped.connect(self._on_drop_zone_file)

    # ── Drag & drop ──────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        self._handle_drop_event(event)

    def eventFilter(self, obj, event):
        """Intercept drag/drop events that child widgets might consume."""
        if event.type() == event.Type.DragEnter:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return True
        elif event.type() == event.Type.Drop:
            self._handle_drop_event(event)
            return True
        return super().eventFilter(obj, event)

    def _handle_drop_event(self, event: QDropEvent):
        if self._import_guard.is_active:
            self._set_status("Import already in progress, drop ignored.")
            return
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                log.info("[drop] file dropped via event filter: %s", path)
                self._load_media(path)

    @Slot(str)
    def _on_drop_zone_file(self, path: str):
        """Handle a file dropped directly on the DropZoneWidget."""
        if self._import_guard.is_active:
            self._set_status("Import already in progress, drop ignored.")
            return
        log.info("[drop] file dropped on DropZoneWidget: %s", path)
        self._load_media(path)

    # ── Import (background worker) ───────────────────────────────────────

    @Slot()
    def _import_media(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Media",
            "",
            "Media Files (*.mp4 *.mkv *.mov *.avi *.webm *.mp3 *.wav *.flac *.ogg *.m4a);;All Files (*)",
        )
        if path:
            self._load_media(path)

    @Slot()
    def _reopen_last_project(self):
        """Reopen the most recently saved project from the database."""
        project = self._project_svc.get_latest_project()
        if not project:
            QMessageBox.information(self, "No Projects", "No saved projects found.")
            return
        self._open_project_by_id(project.id)

    def _open_project_by_id(self, project_id: int):
        """Open a specific project by its database ID."""
        self._flush_caption_save()
        project = self._project_svc.load_project(project_id)
        if not project:
            QMessageBox.warning(self, "Not Found", "The selected project was not found.")
            return

        # Verify the media file still exists
        media_path = Path(project.media_path)
        if not media_path.exists():
            QMessageBox.warning(
                self, "Media Not Found",
                f"The media file no longer exists:\n{project.media_path}\n\n"
                "The project cannot be reopened."
            )
            return

        log.info("[reopen] restoring project id=%s title=%s", project.id, project.title)

        # Reset export buttons before restoring state
        self._cmb_export_format.setEnabled(False)
        self._btn_export.setEnabled(False)
        self._btn_reflow.setEnabled(False)

        # Restore project state
        self._project = project
        self._media_duration_ms = project.media_duration_ms
        self._media_fps = None
        self._media_fps = self._resolve_media_fps()
        self._captions = self._project_svc.load_captions(project.id)
        self._words = self._project_svc.load_words(project.id)
        self._segments = self._project_svc.load_segments(project.id)

        # Load media into video panel using persisted proxy or original path
        preview_path = project.proxy_path if project.proxy_path else project.media_path
        self._video_panel.load_media(preview_path, has_video=project.has_video)

        # Populate caption panel
        self._caption_panel.set_captions(self._captions)
        self._video_panel.set_captions(self._captions)

        # Enable workflow buttons
        self._btn_transcribe.setEnabled(True)
        if self._words:
            self._btn_reflow.setEnabled(True)
        if self._captions:
            self._cmb_export_format.setEnabled(True)
            self._on_export_combo_changed()

        caption_count = len(self._captions)
        self._set_status(
            f"Reopened: {project.title}  –  "
            f"{caption_count} caption{'s' if caption_count != 1 else ''}  "
            f"(autosaved)"
        )

    def _load_media(self, path: str):
        self._flush_caption_save()
        # Guard against reentrant imports
        token = self._import_guard.start_import(path)
        if token is None:
            self._set_status("Import already in progress")
            return

        log.info("[import] _load_media called  path=%s  token=%s", path, token)

        # Reset all state before importing new media
        self._captions = []
        self._words = []
        self._segments = []
        self._media_duration_ms = 0
        self._media_fps = None
        self._caption_panel.set_captions([])
        self._video_panel.set_captions([])
        self._video_panel.reset_to_empty()

        self._set_status(f"Loading media: {Path(path).name}")
        self._progress.setVisible(True)
        self._btn_cancel_job.setVisible(True)
        self._btn_cancel_job.setEnabled(True)
        self._btn_import.setEnabled(False)
        self._btn_transcribe.setEnabled(False)
        self._btn_reflow.setEnabled(False)
        self._cmb_export_format.setEnabled(False)
        self._btn_export.setEnabled(False)

        # Create project shell
        self._project = Project(
            title=Path(path).stem,
            media_path=path,
        )

        # Work dir for extracted assets – collision-proof via uuid
        work_dir = Path(path).parent / ".lil_word"
        work_dir.mkdir(exist_ok=True)
        audio_out_path = build_audio_output_path(Path(path).stem, str(work_dir))

        log.info("[import] audio_out_path=%s  work_dir=%s", audio_out_path, work_dir)

        worker = _ImportWorker(path, audio_out_path, token)
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._set_status)
        worker.finished.connect(self._on_import_done)
        worker.error.connect(self._on_import_error)
        worker.cancelled.connect(self._on_import_cancelled)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)

        self._import_thread = thread
        self._import_worker_ref = worker
        thread.start()

        # Start the watchdog timer
        self._import_watchdog.start(_IMPORT_WATCHDOG_SECS * 1000)
        log.info("[import] watchdog started  timeout=%ds", _IMPORT_WATCHDOG_SECS)

    def _on_import_done(
        self,
        audio_path: str,
        duration_ms: int,
        has_video: bool,
        proxy_path: str,
        media_fps: int,
        token: str,
    ):
        # Ignore stale completions from a superseded import
        if not self._import_guard.accept_done(token):
            log.warning("Ignoring stale import completion (token mismatch)")
            return

        self._import_watchdog.stop()

        self._progress.setVisible(False)
        self._btn_cancel_job.setVisible(False)
        self._btn_import.setEnabled(True)

        self._project.audio_path = audio_path
        self._project.proxy_path = proxy_path
        self._project.media_duration_ms = duration_ms
        self._project.has_video = has_video
        self._media_duration_ms = duration_ms
        self._media_fps = media_fps if media_fps > 0 else None

        preview_path = proxy_path if proxy_path else self._project.media_path
        self._video_panel.load_media(preview_path, has_video=has_video)

        # Save project to DB
        self._project = self._project_svc.create_project(self._project)
        self._refresh_reopen_button()

        self._btn_transcribe.setEnabled(True)
        self._set_status(
            f"Media loaded: {Path(self._project.media_path).name} "
            f"({duration_ms // 1000}s) – click Transcribe"
        )
        log.info("[import] done  audio=%s  duration_ms=%d  has_video=%s",
                 audio_path, duration_ms, has_video)

    def _on_import_error(self, msg: str, token: str):
        # Ignore stale errors from a superseded import
        if not self._import_guard.accept_error(token):
            return

        self._import_watchdog.stop()

        self._progress.setVisible(False)
        self._btn_cancel_job.setVisible(False)
        self._btn_import.setEnabled(True)
        # Restore safe empty state
        self._project = None
        self._captions = []
        self._words = []
        self._segments = []
        self._media_duration_ms = 0
        self._media_fps = None
        self._caption_panel.set_captions([])
        self._video_panel.set_captions([])
        self._video_panel.reset_to_empty()
        self._set_status(f"Import error: {msg.splitlines()[0]}")
        log.error("Import error:\n%s", msg)
        QMessageBox.critical(self, "Import Error", msg)

    @Slot(str)
    def _on_import_cancelled(self, token: str):
        if not self._import_guard.accept_error(token):
            return
        
        self._import_watchdog.stop()
        self._progress.setVisible(False)
        self._btn_cancel_job.setVisible(False)
        self._btn_import.setEnabled(True)
        
        self._project = None
        self._captions = []
        self._words = []
        self._segments = []
        self._media_duration_ms = 0
        self._media_fps = None
        self._caption_panel.set_captions([])
        self._video_panel.set_captions([])
        self._video_panel.reset_to_empty()
        
        self._set_status("Import cancelled.")

    @Slot()
    def _on_import_watchdog(self):
        """Fired when the import worker exceeds the watchdog timeout."""
        log.error("[import] WATCHDOG fired after %ds – treating import as failed",
                  _IMPORT_WATCHDOG_SECS)

        self._shutdown_import_worker(timeout_ms=1200)

        # Force-clear the guard so a new import can start
        current_token = self._import_guard.token
        if current_token:
            self._import_guard.accept_error(current_token)

        self._progress.setVisible(False)
        self._btn_cancel_job.setVisible(False)
        self._btn_import.setEnabled(True)

        # Restore safe empty state
        self._project = None
        self._captions = []
        self._words = []
        self._segments = []
        self._media_duration_ms = 0
        self._media_fps = None
        self._caption_panel.set_captions([])
        self._video_panel.set_captions([])
        self._video_panel.reset_to_empty()

        self._set_status(
            f"Import timed out after {_IMPORT_WATCHDOG_SECS}s – see log for details"
        )
        QMessageBox.critical(
            self,
            "Import Timeout",
            f"The import worker did not complete within {_IMPORT_WATCHDOG_SECS} seconds.\n\n"
            "This may indicate that ffmpeg is hanging on this file.\n"
            "Check the application log for diagnostic timestamps.",
        )

    # ── Transcription ────────────────────────────────────────────────────

    @Slot()
    def _run_transcribe(self):
        if not self._project or not self._project.audio_path:
            return

        self._btn_transcribe.setEnabled(False)
        self._progress.setVisible(True)
        self._btn_cancel_job.setVisible(True)
        self._btn_cancel_job.setEnabled(True)
        self._set_status("Starting transcription…")

        worker = _TranscribeWorker(
            self._project.audio_path, self._settings,
            media_duration_ms=self._media_duration_ms,
        )
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._set_status)
        worker.finished.connect(self._on_transcribe_done)
        worker.error.connect(self._on_transcribe_error)
        worker.cancelled.connect(self._on_job_cancelled)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)

        self._worker_thread = thread
        self._worker_ref = worker  # prevent GC
        thread.start()

    def _on_transcribe_done(self, segments, words, captions):
        self._segments = segments
        self._words = words
        self._captions = captions
        self._caption_panel.set_captions(self._captions)
        self._video_panel.set_captions(self._captions)

        # Persist
        if self._project and self._project.id:
            self._project_svc.save_captions(self._project.id, self._captions)
            self._project_svc.save_words(self._project.id, self._words)
            self._project_svc.save_segments(self._project.id, self._segments)

        self._btn_transcribe.setEnabled(True)
        self._btn_reflow.setEnabled(True)
        self._cmb_export_format.setEnabled(True)
        self._on_export_combo_changed()

        self._progress.setVisible(False)
        self._btn_cancel_job.setVisible(False)
        self._set_status(f"Done – {len(captions)} captions generated (autosaved)")

    def _on_transcribe_error(self, msg):
        self._progress.setVisible(False)
        self._btn_cancel_job.setVisible(False)
        self._btn_transcribe.setEnabled(True)
        self._set_status(f"Transcription error: {msg.splitlines()[0]}")
        log.error("Transcription error:\n%s", msg)
        QMessageBox.critical(self, "Transcription Error", msg)

    # ── Reflow ───────────────────────────────────────────────────────────

    @Slot()
    def _reflow_captions(self):
        """Re-run caption generation from stored words (full project, with overwrite warning)."""
        if not self._words and not self._segments:
            self._set_status("No transcript data available for reflow")
            return

        if self._captions:
            ans = QMessageBox.warning(
                self,
                "Regenerate Captions",
                "Regenerate captions? This will overwrite any manual text or timing edits.",
                QMessageBox.Yes | QMessageBox.Cancel
            )
            if ans != QMessageBox.Yes:
                return

        new_captions = self._run_reflow_core(self._words)
        self._captions = new_captions
        self._caption_panel.set_captions(self._captions)
        self._video_panel.set_captions(self._captions)
        self._save_captions()
        self._set_status(f"Reflowed – {len(self._captions)} captions")

    def _reflow_captions_direct(self):
        """Re-run caption generation without overwrite warning.

        Used by the post-rules prompt path where the user has already confirmed.
        """
        if not self._words and not self._segments:
            self._set_status("No transcript data available for reflow")
            return

        new_captions = self._run_reflow_core(self._words)
        self._captions = new_captions
        self._caption_panel.set_captions(self._captions)
        self._video_panel.set_captions(self._captions)
        self._save_captions()
        self._set_status(f"Reflowed – {len(self._captions)} captions")

    def _reflow_selected(self):
        """Regenerate only the selected contiguous captions using current rules.

        Requires a contiguous selection. Finds transcript data within the
        selected time range, regenerates captions for that range, and splices
        them back in — surrounding captions stay intact.
        """
        if not self._words and not self._segments:
            self._set_status("✂️ No transcript data available for selected reflow")
            return

        sel = self._caption_panel.selected_indices()
        if not sel:
            self._set_status("✂️ Select at least one caption to regen")
            return

        # Require contiguous selection to prevent overwriting unselected rows
        if sel[-1] - sel[0] != len(sel) - 1:
            self._set_status(
                "✂️ Regen Sel requires a contiguous selection "
                "(no gaps between selected rows)."
            )
            return

        # Determine the time range of the selected captions
        range_start = self._captions[sel[0]].start_ms
        range_end = self._captions[sel[-1]].end_ms

        # Find words that overlap the selected range (±200ms tolerance)
        range_words = [
            w for w in self._words
            if w.start_ms >= range_start - 200
            and w.end_ms <= range_end + 200
        ]

        # Find segments that overlap the selected range
        range_segments = [
            s for s in self._segments
            if int(s["start"] * 1000) >= range_start - 200
            and int(s["end"] * 1000) <= range_end + 200
        ] if self._segments else []

        if not range_words and not range_segments:
            self._set_status(
                "✂️ No transcript data found in the selected time range"
            )
            return

        # Generate new captions for just the selected range
        new_captions = self._run_reflow_core(range_words, segments=range_segments)

        # Splice: replace the contiguous selected range with new captions
        self._captions[sel[0]:sel[-1] + 1] = new_captions
        self._caption_panel.set_captions(self._captions)
        self._video_panel.set_captions(self._captions)
        self._save_captions()
        self._set_status(
            f"Reflowed {len(sel)} → {len(new_captions)} captions "
            f"({range_start}–{range_end} ms)"
        )

    def _run_reflow_core(self, words: list, segments: list[dict] | None = None) -> list:
        """Shared reflow engine: generate + refine captions from words (with segment fallback).

        Parameters
        ----------
        words : list[TranscriptWord]
            Word-level transcript data.
        segments : list[dict] | None
            Raw transcript segments (start/end in seconds, text). Passed to
            generate_captions for segment-level fallback when word data is
            insufficient. Defaults to self._segments if not provided.

        Returns the new caption list. Does NOT update panels or save — callers
        handle that so they can choose full-replace vs. splice semantics.
        """
        if segments is None:
            segments = self._segments
        captions = generate_caption_blocks(
            segments,
            words,
            self._settings,
            media_duration_ms=self._media_duration_ms,
        )
        if self._project and self._project.audio_path:
            captions = refine_timing(
                captions, self._project.audio_path,
                media_duration_ms=self._media_duration_ms,
            )
        return captions

    @Slot()
    def _open_rules(self):
        """Open caption rules configuration dialog."""
        from app.ui.caption_rules_dialog import _TIMING_KEYS

        # Snapshot timing values before the dialog
        before = {k: self._settings.get(k) for k in _TIMING_KEYS}

        dlg = CaptionRulesDialog(self._settings, self)
        result = dlg.exec()

        if result != CaptionRulesDialog.Accepted:
            return

        # Compare after — did anything actually change?
        after = {k: self._settings.get(k) for k in _TIMING_KEYS}
        if before == after:
            # No timing change — no prompt needed
            return

        if not self._captions:
            # No captions to regen — nothing to prompt about
            return

        if not self._words and not self._segments:
            # Changed timing but transcript data unavailable — can't regen
            self._set_status(
                "⚙️ Timing rules updated. Regen is not available "
                "(no transcript data). Re-transcribe to apply new timing."
            )
            return

        # Real change + captions + transcript data → offer regen
        reply = QMessageBox.question(
            self,
            "Apply Timing Changes",
            "Timing rules changed. Regenerate captions now with the\n"
            "new timing? This will overwrite any manual edits.\n\n"
            "Choose No to keep current captions and apply on next Regen.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._reflow_captions_direct()
        else:
            self._set_status(
                "⚙️ Timing rules updated — use Regen to apply to current captions."
            )

    @Slot()
    def _open_settings(self):
        """Open export and model settings dialog."""
        dlg = ExportSettingsDialog(self._settings, self)
        dlg.exec()
        self._video_panel.set_style_settings(self._settings)

    # ── Export ───────────────────────────────────────────────────────────

    @Slot()
    def _on_export_combo_changed(self):
        format_id = self._cmb_export_format.currentData()
        has_valid_format = bool(format_id)
        has_captions = bool(self._captions)
        
        can_export = has_valid_format and has_captions
        
        if format_id == "video" and self._project:
            can_export = can_export and self._project.has_video
            
        self._btn_export.setEnabled(can_export)

    @Slot()
    def _do_export(self):
        format_id = self._cmb_export_format.currentData()
        if not format_id:
            return
            
        if format_id == "srt":
            self._do_export_srt()
        elif format_id == "ass":
            self._do_export_ass()
        elif format_id == "ttml":
            self._do_export_ttml()
        elif format_id == "ebu_tt":
            self._do_export_ebu_tt()
        elif format_id == "smpte_tt":
            self._do_export_smpte_tt()
        elif format_id == "ebu_stl":
            self._do_export_ebu_stl()
        elif format_id == "mcc":
            self._do_export_mcc()
        elif format_id == "video":
            self._do_export_video()

    @Slot()
    def _do_export_srt(self):
        if not self._captions:
            return
        # Normalize before export
        self._normalize_current_captions()
        default_name = self._default_export_name(".srt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SRT", default_name, "SRT Files (*.srt)")
        if path:
            export_srt(self._captions, path)
            self._set_status(f"Exported SRT → {Path(path).name}")

    @Slot()
    def _do_export_ass(self):
        if not self._captions:
            return
        # Normalize before export
        self._normalize_current_captions()
        default_name = self._default_export_name(".ass")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export ASS", default_name, "ASS Files (*.ass)")
        if path:
            export_ass(self._captions, path)
            self._set_status(f"Exported ASS → {Path(path).name}")

    @Slot()
    def _do_export_ttml(self):
        if not self._captions:
            return
        # Normalize before export
        self._normalize_current_captions()
        default_name = self._default_export_name("_ttml.xml")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export TTML", default_name, "TTML Files (*.xml *.ttml)")
        if path:
            from app.services.export_service import export_ttml
            export_ttml(self._captions, path, settings=self._settings)
            self._set_status(f"Exported TTML → {Path(path).name}")

    @Slot()
    def _do_export_ebu_tt(self):
        if not self._captions:
            return
        # Normalize before export
        self._normalize_current_captions()
        default_name = self._default_export_name("_ebu_tt.xml")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export EBU-TT", default_name, "EBU-TT Files (*.xml)")
        if path:
            from app.services.export_service import export_ebu_tt
            export_ebu_tt(self._captions, path, settings=self._settings)
            self._set_status(f"Exported EBU-TT → {Path(path).name}")

    @Slot()
    def _do_export_smpte_tt(self):
        if not self._captions:
            return
        # Normalize before export
        self._normalize_current_captions()
        default_name = self._default_export_name("_smpte_tt.xml")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SMPTE-TT", default_name, "SMPTE-TT Files (*.xml)")
        if path:
            from app.services.export_service import export_smpte_tt
            export_smpte_tt(self._captions, path, settings=self._settings)
            self._set_status(f"Exported SMPTE-TT → {Path(path).name}")

    @Slot()
    def _do_export_ebu_stl(self):
        if not self._captions:
            return
        # Normalize before export
        self._normalize_current_captions()
        default_name = self._default_export_name("_ebu.stl")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export EBU STL", default_name, "EBU STL Files (*.stl)")
        if path:
            from app.services.export_service import export_ebu_stl
            export_fps = self._resolve_media_fps()
            export_ebu_stl(
                self._captions,
                path,
                settings=self._settings,
                fps=export_fps,
            )
            self._set_status(f"Exported EBU STL → {Path(path).name}")

    @Slot()
    def _do_export_mcc(self):
        if not self._captions:
            return
        # Normalize before export
        self._normalize_current_captions()
        default_name = self._default_export_name(".mcc")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export MCC", default_name, "MCC Files (*.mcc)")
        if path:
            from app.services.export_service import export_mcc
            export_fps = self._resolve_media_fps()
            export_mcc(
                self._captions,
                path,
                settings=self._settings,
                fps=export_fps,
            )
            self._set_status(f"Exported MCC → {Path(path).name}")

    @Slot()
    def _do_export_video(self):
        if not self._captions or not self._project:
            return
        # Normalize before export
        self._normalize_current_captions()
        default_name = self._default_export_name("_subtitled.mp4")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Burned-In Video", default_name, "MP4 Files (*.mp4)")
        if not path:
            return

        self._progress.setVisible(True)
        self._btn_cancel_job.setVisible(True)
        self._btn_cancel_job.setEnabled(True)
        self._set_status("Burning subtitles into video…")
        self._cmb_export_format.setEnabled(False)
        self._btn_export.setEnabled(False)

        worker = _ExportWorker(self._project.media_path, self._captions, path)
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_export_done)
        worker.error.connect(self._on_export_error)
        worker.cancelled.connect(self._on_job_cancelled)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)

        self._export_thread = thread
        self._export_worker_ref = worker
        thread.start()

    def _on_export_done(self, path):
        self._progress.setVisible(False)
        self._btn_cancel_job.setVisible(False)
        self._cmb_export_format.setEnabled(True)
        self._on_export_combo_changed()
        self._set_status(f"Exported video → {Path(path).name}")

    def _on_export_error(self, msg):
        self._progress.setVisible(False)
        self._btn_cancel_job.setVisible(False)
        self._cmb_export_format.setEnabled(True)
        self._on_export_combo_changed()
        self._set_status(f"Export error: {msg.splitlines()[0]}")
        QMessageBox.critical(self, "Export Error", msg)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _shutdown_import_worker(self, timeout_ms: int = 1000) -> None:
        """Stop the active import worker thread and wait briefly before returning."""
        worker = getattr(self, "_import_worker_ref", None)
        thread = getattr(self, "_import_thread", None)

        if worker is not None and not getattr(worker, "_is_cancelled", False):
            worker.cancel()

        if thread is None:
            return

        # Ask the thread to stop quickly; bound the wait so UI remains responsive.
        thread.requestInterruption()
        if thread.isRunning():
            thread.quit()
            if not thread.wait(timeout_ms):
                log.warning(
                    "[import] Import thread did not stop within %dms; terminating.",
                    timeout_ms,
                )
                thread.terminate()
                if not thread.wait(max(timeout_ms, 1000)):
                    log.warning("[import] Import thread failed to terminate.")
        else:
            # No longer running, but ensure any pending event loop wakeups are flushed.
            thread.requestInterruption()
            thread.quit()

        self._import_thread = None
        self._import_worker_ref = None

    def _on_captions_edited(self):
        """Called when captions change in the editor – normalize and persist."""
        self._captions = self._caption_panel.get_captions()
        self._normalize_current_captions()
        self._caption_panel.set_captions(self._captions)
        self._video_panel.set_captions(self._captions)
        self._schedule_caption_save()

    def _schedule_caption_save(self):
        """Coalesce rapid caption edits into one persistence operation."""
        if not hasattr(self, "_caption_save_timer"):
            self._caption_save_timer = QTimer(self)
            self._caption_save_timer.setSingleShot(True)
            self._caption_save_timer.timeout.connect(self._flush_caption_save)
        self._caption_save_timer.start(500)

    def _flush_caption_save(self):
        """Persist pending caption edits immediately at a commit boundary."""
        timer = getattr(self, "_caption_save_timer", None)
        if timer is not None:
            timer.stop()
        self._save_captions()

    def _on_split_feedback(self, reason: str):
        """Show a visible status message when Split cannot act."""
        self._set_status(f"✂️ {reason}")

    @Slot()
    def _on_cancel_job(self):
        self._set_status("Cancelling job…")
        self._btn_cancel_job.setEnabled(False)
        self._shutdown_import_worker()
        if getattr(self, '_worker_ref', None) and not self._worker_ref._is_cancelled:
            self._worker_ref.cancel()
        if getattr(self, '_export_worker_ref', None) and not self._export_worker_ref._is_cancelled:
            self._export_worker_ref.cancel()

    @Slot()
    def _on_job_cancelled(self):
        self._progress.setVisible(False)
        self._btn_cancel_job.setVisible(False)
        self._btn_cancel_job.setEnabled(True)
        self._btn_import.setEnabled(True)
        self._btn_transcribe.setEnabled(True)
        if self._words:
            self._btn_reflow.setEnabled(True)
        if self._captions:
            self._cmb_export_format.setEnabled(True)
            self._on_export_combo_changed()
        self._set_status("Operation cancelled.")

    def _on_merge_feedback(self, reason: str):
        """Show a visible status message when Merge cannot act."""
        self._set_status(f"🔗 {reason}")

    def _normalize_current_captions(self):
        """Run the shared normalizer over current captions."""
        self._captions = normalize_captions(
            self._captions,
            min_dur=self._settings.get("min_caption_ms", 700),
            min_gap=self._settings.get("min_gap_ms", 100),
            media_duration_ms=self._media_duration_ms,
        )

    def _save_captions(self):
        if self._project and self._project.id:
            self._project_svc.save_captions(self._project.id, self._captions)

    def _refresh_reopen_button(self):
        """Update the Reopen Last button and Recent Projects menu from the DB."""
        latest = self._project_svc.get_latest_project()
        self._btn_reopen.setEnabled(latest is not None)
        if latest:
            self._btn_reopen.setToolTip(f"Reopen: {latest.title}")
        else:
            self._btn_reopen.setToolTip("Reopen the most recently saved project.")

        # Rebuild recent-projects menu
        self._recent_menu.clear()
        recent = self._project_svc.list_recent_projects(limit=10)
        if not recent:
            empty_action = self._recent_menu.addAction("(no saved projects)")
            empty_action.setEnabled(False)
        else:
            for proj in recent:
                action = self._recent_menu.addAction(f"{proj.title}  ({proj.media_path})")
                # Capture proj.id in the lambda default to avoid late-binding
                action.triggered.connect(
                    lambda checked=False, pid=proj.id: self._open_project_by_id(pid)
                )

    def _set_status(self, msg: str):
        self._status_label.setText(msg)
        log.info(msg)

    def _default_export_name(self, suffix: str) -> str:
        """Build default export filename. Handles both .ext and _stem.ext suffixes."""
        media_path = self._project.media_path if self._project else ""
        return build_export_name(media_path, suffix)

    def _resolve_media_fps(self) -> int | None:
        """Return cached FPS from current media if available, else probe media once."""
        if self._media_fps and self._media_fps > 0:
            return self._media_fps

        if not self._project or not self._project.media_path:
            return None

        try:
            fps = media_service.get_video_fps(self._project.media_path)
        except Exception as exc:
            log.warning("Unable to probe media FPS from %s: %s", self._project.media_path, exc)
            return None

        self._media_fps = fps
        return fps

    def closeEvent(self, event):
        self._flush_caption_save()
        self._project_svc.close()
        super().closeEvent(event)
