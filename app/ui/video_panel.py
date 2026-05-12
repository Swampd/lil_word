"""Video preview panel – media playback with subtitle overlay."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, Slot, QSize, QMimeData, QRect
from PySide6.QtGui import QFont, QPainter, QColor, QPen, QFontMetrics, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSizePolicy, QStyle, QStackedWidget,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from app.models.caption import Caption
from app.utils.timecode import ms_to_display
from app.utils.settings import Settings


class SubtitleOverlay(QWidget):
    """Transparent overlay that draws the current subtitle over the media, using export style settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Default style state
        self._font_family = "Arial"
        self._font_size_px = 16
        self._fill_color = "#FFFFFF"
        self._bg_color = "#00000000"
        self._text_align = "center"
        self._region_origin = (0.10, 0.80)
        self._region_extent = (0.80, 0.15)

    def set_subtitle(self, text: str):
        self._text = text
        self.update()

    def set_style_settings(self, settings: Settings):
        """Update style properties from the global settings."""
        self._font_family = settings.get("export_font_family", "Arial")
        self._font_size_px = self._parse_font_size(settings.get("export_font_size", "100%"))
        
        fill_color = settings.get("export_fill_color", "#FFFFFF")
        self._fill_color = fill_color if self._is_valid_color(fill_color) else "#FFFFFF"
        
        bg_color = settings.get("export_background_color", "#00000000")
        self._bg_color = bg_color if self._is_valid_color(bg_color) else "#00000000"
        
        self._text_align = settings.get("export_text_align", "center")
        self._region_origin = self._parse_region(settings.get("export_region_origin", "10% 80%"), (0.10, 0.80))
        self._region_extent = self._parse_region(settings.get("export_region_extent", "80% 15%"), (0.80, 0.15))
        self.update()

    @staticmethod
    def _parse_font_size(s: str) -> int:
        s = (s or "").strip()
        if not s: return 16
        m = re.match(r"^(\d+(?:\.\d+)?)\s*(%|px|pt|em)$", s, re.IGNORECASE)
        if not m: return 16
        val, unit = float(m.group(1)), m.group(2).lower()
        if unit == "%": return max(8, int(val * 16 / 100))
        if unit == "px": return max(8, int(val))
        if unit == "pt": return max(8, int(val * 4 / 3))
        if unit == "em": return max(8, int(val * 16))
        return 16

    @staticmethod
    def _is_valid_color(s: str) -> bool:
        return bool(s and re.match(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$", s))

    @staticmethod
    def _parse_region(s: str, default: tuple) -> tuple:
        m = re.match(r"^(\d+(?:\.\d+)?)\s*%\s+(\d+(?:\.\d+)?)\s*%$", (s or "").strip())
        if not m: return default
        return (float(m.group(1)) / 100.0, float(m.group(2)) / 100.0)

    def paintEvent(self, event):
        if not self._text:
            return
            
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Calculate 16:9 letterbox frame
        target_w = w
        target_h = int(w * 9 / 16)
        if target_h > h:
            target_h = h
            target_w = int(h * 16 / 9)
        lx = (w - target_w) // 2
        ly = (h - target_h) // 2

        # Caption region relative to letterbox
        ox, oy = self._region_origin
        ew, eh = self._region_extent
        rx = lx + int(ox * target_w)
        ry = ly + int(oy * target_h)
        rw = int(ew * target_w)
        rh = int(eh * target_h)

        # Clamp region to widget bounds
        rx = max(lx, min(rx, lx + target_w - 10))
        ry = max(ly, min(ry, ly + target_h - 10))
        rw = max(20, min(rw, lx + target_w - rx))
        rh = max(20, min(rh, ly + target_h - ry))

        # Caption background
        bg = QColor(self._bg_color)
        if bg.alpha() > 0:
            p.fillRect(rx, ry, rw, rh, bg)

        # Caption text
        font = QFont(self._font_family, self._font_size_px)
        p.setFont(font)
        p.setPen(QColor(self._fill_color))

        align_map = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}
        h_align = align_map.get(self._text_align, Qt.AlignHCenter)
        text_flags = h_align | Qt.AlignVCenter | Qt.TextWordWrap

        text_rect = QRect(rx + 4, ry + 2, rw - 8, rh - 4)
        p.drawText(text_rect, text_flags, self._text)
        p.end()

class AudioCanvasWidget(QWidget):
    """16:9 blank canvas for audio-only preview."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filename = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_filename(self, filename: str):
        self._filename = filename
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()

        # Fill background with black (letterboxing bars)
        p.fillRect(0, 0, w, h, Qt.black)

        # Calculate 16:9 canvas
        target_w = w
        target_h = int(w * 9 / 16)
        if target_h > h:
            target_h = h
            target_w = int(h * 16 / 9)
        lx = (w - target_w) // 2
        ly = (h - target_h) // 2

        # Draw the 16:9 canvas area
        p.fillRect(lx, ly, target_w, target_h, QColor(20, 20, 20))
        
        if self._filename:
            p.setPen(QColor(100, 100, 100))
            p.setFont(QFont("Arial", 12))
            p.drawText(lx, ly, target_w, 40, Qt.AlignCenter, f"🎧 Audio loaded: {self._filename}")
        p.end()


class DropZoneWidget(QWidget):
    """Visible, interactive drop zone that directly handles drag-and-drop.

    This widget does NOT use WA_TransparentForMouseEvents.  It accepts
    drops itself and emits ``file_dropped`` when a media file is dropped.
    """

    file_dropped = Signal(str)  # emits the local file path

    _MEDIA_EXTS = {
        ".mp4", ".mkv", ".mov", ".avi", ".webm",
        ".mp3", ".wav", ".flac", ".ogg", ".m4a",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        self._icon_label = QLabel("📂")
        self._icon_label.setAlignment(Qt.AlignCenter)
        self._icon_label.setStyleSheet("QLabel { font-size: 48px; background: transparent; }")
        self._icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._text_label = QLabel("Drop media here\nor click Import Media")
        self._text_label.setAlignment(Qt.AlignCenter)
        self._text_label.setWordWrap(True)
        self._text_label.setStyleSheet(
            "QLabel {"
            "  color: #a0a0a0;"
            "  font-size: 22px;"
            "  font-weight: bold;"
            "  background: transparent;"
            "}"
        )
        self._text_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        layout.addStretch(1)
        layout.addWidget(self._icon_label)
        layout.addWidget(self._text_label)
        layout.addStretch(1)

        self.setStyleSheet(
            "DropZoneWidget {"
            "  background: #1e1e1e;"
            "  border: 2px dashed #555;"
            "  border-radius: 12px;"
            "}"
            "DropZoneWidget:hover {"
            "  border-color: #4183c4;"
            "}"
        )

    # ── Drag / drop ──────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            # Accept if at least one URL looks like a media file
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path and Path(path).suffix.lower() in self._MEDIA_EXTS:
                    event.acceptProposedAction()
                    self.setStyleSheet(
                        "DropZoneWidget {"
                        "  background: #252530;"
                        "  border: 2px dashed #4183c4;"
                        "  border-radius: 12px;"
                        "}"
                    )
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        # Restore normal style
        self.setStyleSheet(
            "DropZoneWidget {"
            "  background: #1e1e1e;"
            "  border: 2px dashed #555;"
            "  border-radius: 12px;"
            "}"
            "DropZoneWidget:hover {"
            "  border-color: #4183c4;"
            "}"
        )

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.file_dropped.emit(path)
        # Restore style
        self.dragLeaveEvent(event)


class VideoPanel(QWidget):
    """Video preview panel with playback controls and subtitle overlay."""

    position_changed = Signal(int)  # emits current position in ms
    file_dropped = Signal(str)      # forwarded from the drop zone

    def __init__(self, parent=None):
        super().__init__(parent)
        self._captions: list[Caption] = []
        self._duration_ms: int = 0
        self._media_loaded = False

        # --- Media player ---
        self._player = QMediaPlayer()
        self._audio = QAudioOutput()
        self._player.setAudioOutput(self._audio)

        self._video_widget = QVideoWidget()
        self._video_widget.setMinimumSize(400, 260)
        self._video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._player.setVideoOutput(self._video_widget)

        # Subtitle overlay (re-parented to VideoPanel so it floats above the stack)
        self._overlay = SubtitleOverlay(self)

        # --- Drop zone (empty state) ---
        self._drop_zone = DropZoneWidget()
        self._drop_zone.file_dropped.connect(self.file_dropped)

        # --- Audio-only state ---
        self._audio_canvas = AudioCanvasWidget()

        # --- Stacked widget: 0=drop zone, 1=video, 2=audio ---
        self._stack = QStackedWidget()
        self._stack.addWidget(self._drop_zone)   # index 0
        self._stack.addWidget(self._video_widget) # index 1
        self._stack.addWidget(self._audio_canvas) # index 2
        self._stack.setCurrentIndex(0)

        # --- Transport controls ---
        self._btn_play = QPushButton("▶")
        self._btn_play.setFixedWidth(40)
        self._btn_play.clicked.connect(self._toggle_play)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.sliderMoved.connect(self._seek)

        self._lbl_time = QLabel("00:00.0 / 00:00.0")
        self._lbl_time.setFixedWidth(140)

        transport = QHBoxLayout()
        transport.addWidget(self._btn_play)
        transport.addWidget(self._slider, 1)
        transport.addWidget(self._lbl_time)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack, 1)
        layout.addLayout(transport)

        # --- Signals ---
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)

        # Subtitle update timer
        self._sub_timer = QTimer(self)
        self._sub_timer.setInterval(50)
        self._sub_timer.timeout.connect(self._update_subtitle)

    # ── Public API ───────────────────────────────────────────────────────

    def get_drop_targets(self) -> list[QWidget]:
        """Return widgets that should accept drops (for MainWindow event filter)."""
        return [self, self._drop_zone]

    def load_media(self, path: str, has_video: bool = True):
        self._media_loaded = True
        if has_video:
            self._stack.setCurrentIndex(1)
        else:
            filename = Path(path).name
            self._audio_canvas.set_filename(filename)
            self._stack.setCurrentIndex(2)

        self._update_overlay_geometry()

        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.pause()  # Load but don't auto-play

    def set_captions(self, captions: list[Caption]):
        self._captions = captions

    def seek_to(self, ms: int):
        self._player.setPosition(ms)

    def get_position_ms(self) -> int:
        return self._player.position()

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlayingState

    def reset_to_empty(self):
        """Return to the empty drop-zone state."""
        self._media_loaded = False
        self._stack.setCurrentIndex(0)
        self._player.stop()
        self._player.setSource(QUrl())
        self._captions = []
        self._duration_ms = 0
        self._slider.setRange(0, 0)
        self._lbl_time.setText("00:00.0 / 00:00.0")

    # ── Slots ────────────────────────────────────────────────────────────

    @Slot()
    def _toggle_play(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()
            self._sub_timer.start()

    @Slot(int)
    def _seek(self, pos):
        self._player.setPosition(pos)

    @Slot(int)
    def _on_position(self, pos):
        if not self._slider.isSliderDown():
            self._slider.setValue(pos)
        self._lbl_time.setText(
            f"{ms_to_display(pos)} / {ms_to_display(self._duration_ms)}"
        )
        self.position_changed.emit(pos)

    @Slot(int)
    def _on_duration(self, dur):
        self._duration_ms = dur
        self._slider.setRange(0, dur)

    @Slot()
    def _on_state(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._btn_play.setText("⏸")
            self._sub_timer.start()
        else:
            self._btn_play.setText("▶")
            self._sub_timer.stop()

    @Slot()
    def _update_subtitle(self):
        pos = self._player.position()
        text = ""
        for cap in self._captions:
            if cap.start_ms <= pos <= cap.end_ms:
                text = cap.text
                break
        self._overlay.set_subtitle(text)

    def set_style_settings(self, settings: Settings):
        self._overlay.set_style_settings(settings)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_overlay_geometry()

    def _update_overlay_geometry(self):
        # Keep subtitle overlay sized to match the active stacked widget
        if self._media_loaded:
            self._overlay.setGeometry(self._stack.currentWidget().geometry())
            self._overlay.raise_()
