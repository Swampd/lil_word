"""Caption Styles and Export Settings dialog with preset management and live preview.

Surfaces the export style defaults and Whisper model/device settings from the
JSON settings store into a user-facing style design dialog. Includes named
style presets (built-in + user-saved) for quick style switching, and a live
caption style preview that updates as fields change.
"""

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QDialogButtonBox,
    QComboBox, QLineEdit, QGroupBox, QLabel, QMessageBox,
    QHBoxLayout, QPushButton, QInputDialog, QWidget, QSplitter,
    QFontComboBox, QColorDialog,
)
from app.utils.settings import Settings, BUILTIN_PRESETS
from app.validation.export_style_validators import (
    validate_font_size, validate_fill_color, validate_background_color,
    validate_region_origin, validate_region_extent,
)


_WHISPER_MODELS = ["tiny", "base", "small", "medium", "large"]
_WHISPER_DEVICES = ["auto", "cpu", "cuda"]
_WHISPER_COMPUTE_TYPES = ["int8", "float16", "float32"]
_TEXT_ALIGNS = ["center", "left", "right"]

_PRESET_SEPARATOR = "──────────"

_SAMPLE_LINES = ["Sample caption text", "for style preview"]


class StylePreviewWidget(QWidget):
    """Paints a simulated video frame with sample caption text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        # Style state — set from dialog fields
        self._font_family = "Arial"
        self._font_size_px = 16
        self._fill_color = "#FFFFFF"
        self._bg_color = "#00000000"
        self._text_align = "center"
        self._region_origin = (0.10, 0.80)  # (x_frac, y_frac)
        self._region_extent = (0.80, 0.15)  # (w_frac, h_frac)

    def set_style(self, font_family: str, font_size_str: str,
                  fill_color: str, bg_color: str, text_align: str,
                  region_origin: str, region_extent: str):
        """Update preview style from raw field values."""
        self._font_family = font_family or "Arial"
        self._font_size_px = self._parse_font_size(font_size_str)
        self._fill_color = fill_color if self._is_valid_color(fill_color) else "#FFFFFF"
        self._bg_color = bg_color if self._is_valid_color(bg_color) else "#00000000"
        self._text_align = text_align or "center"
        self._region_origin = self._parse_region(region_origin, (0.10, 0.80))
        self._region_extent = self._parse_region(region_extent, (0.80, 0.15))
        self.update()

    @staticmethod
    def _parse_font_size(s: str) -> int:
        """Convert CSS-style font size to approximate pixel size for preview."""
        s = (s or "").strip()
        if not s:
            return 16
        m = re.match(r"^(\d+(?:\.\d+)?)\s*(%|px|pt|em)$", s, re.IGNORECASE)
        if not m:
            return 16
        val, unit = float(m.group(1)), m.group(2).lower()
        if unit == "%":
            return max(8, int(val * 16 / 100))
        elif unit == "px":
            return max(8, int(val))
        elif unit == "pt":
            return max(8, int(val * 4 / 3))
        elif unit == "em":
            return max(8, int(val * 16))
        return 16

    @staticmethod
    def _is_valid_color(s: str) -> bool:
        return bool(s and re.match(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$", s))

    @staticmethod
    def _parse_region(s: str, default: tuple) -> tuple:
        """Parse 'X% Y%' into (x_frac, y_frac)."""
        m = re.match(r"^(\d+(?:\.\d+)?)\s*%\s+(\d+(?:\.\d+)?)\s*%$", (s or "").strip())
        if not m:
            return default
        return (float(m.group(1)) / 100.0, float(m.group(2)) / 100.0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Dark "video frame" background
        p.fillRect(0, 0, w, h, QColor(30, 30, 30))

        # Simulated frame border
        p.setPen(QPen(QColor(60, 60, 60), 1))
        p.drawRect(0, 0, w - 1, h - 1)

        # Caption region
        ox, oy = self._region_origin
        ew, eh = self._region_extent
        rx = int(ox * w)
        ry = int(oy * h)
        rw = int(ew * w)
        rh = int(eh * h)

        # Clamp region to widget bounds
        rx = max(0, min(rx, w - 10))
        ry = max(0, min(ry, h - 10))
        rw = max(20, min(rw, w - rx))
        rh = max(20, min(rh, h - ry))

        # Caption background
        bg = QColor(self._bg_color)
        if bg.alpha() > 0:
            p.fillRect(rx, ry, rw, rh, bg)

        # Region outline (always visible, subtle)
        p.setPen(QPen(QColor(100, 100, 100, 120), 1, Qt.DashLine))
        p.drawRect(rx, ry, rw, rh)

        # Caption text
        font = QFont(self._font_family, self._font_size_px)
        p.setFont(font)
        p.setPen(QColor(self._fill_color))

        align_map = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}
        h_align = align_map.get(self._text_align, Qt.AlignHCenter)
        text_flags = h_align | Qt.AlignVCenter | Qt.TextWordWrap

        from PySide6.QtCore import QRect
        text_rect = QRect(rx + 4, ry + 2, rw - 8, rh - 4)
        p.drawText(text_rect, text_flags, "\n".join(_SAMPLE_LINES))

        # "Preview" label
        p.setPen(QColor(80, 80, 80))
        p.setFont(QFont("Arial", 9))
        p.drawText(6, 14, "Preview")

        p.end()


class ExportSettingsDialog(QDialog):
    """Settings dialog for caption style design and Whisper model configuration."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Caption Styles & Export Settings")
        self.setMinimumWidth(720)
        self._settings = settings

        layout = QVBoxLayout(self)

        # ── Explanatory header ───────────────────────────────────────────
        header = QLabel(
            "Design your caption look and save it as a Style Preset.\n"
            "Style rules apply globally on export. Note: Whisper model settings are configured below."
        )
        header.setWordWrap(True)
        header.setStyleSheet("font-size: 12px; margin-bottom: 6px;")
        layout.addWidget(header)

        # ── Style Presets section ────────────────────────────────────────
        preset_group = QGroupBox("Style Presets")
        preset_layout = QVBoxLayout()

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self._cmb_preset = QComboBox()
        self._cmb_preset.setMinimumWidth(200)
        preset_row.addWidget(self._cmb_preset, 1)

        self._btn_save_preset = QPushButton("Save As…")
        self._btn_save_preset.setToolTip("Save the current style fields as a new named preset.")
        self._btn_delete_preset = QPushButton("Delete")
        self._btn_delete_preset.setToolTip("Delete the selected user preset.")
        preset_row.addWidget(self._btn_save_preset)
        preset_row.addWidget(self._btn_delete_preset)
        preset_layout.addLayout(preset_row)

        preset_note = QLabel(
            "Built-in presets are read-only. Your saved presets are stored in the settings file."
        )
        preset_note.setStyleSheet("color: gray; font-size: 10px;")
        preset_layout.addWidget(preset_note)

        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)

        self._btn_save_preset.clicked.connect(self._save_preset)
        self._btn_delete_preset.clicked.connect(self._delete_preset)
        self._cmb_preset.currentIndexChanged.connect(self._on_preset_changed)

        # ── Main content: fields (left) + preview (right) ───────────────
        content_splitter = QSplitter(Qt.Horizontal)

        # Left side: all form groups
        forms_widget = QWidget()
        forms_layout = QVBoxLayout(forms_widget)
        forms_layout.setContentsMargins(0, 0, 0, 0)

        # ── Caption Appearance group ──────────────────────────────────
        style_group = QGroupBox("Caption Appearance")
        style_form = QFormLayout()

        self._txt_font_family = QFontComboBox()
        self._txt_font_family.setCurrentFont(QFont(self._settings.get("export_font_family", "Arial")))
        style_form.addRow("Font Family:", self._txt_font_family)

        self._txt_font_size = QLineEdit()
        self._txt_font_size.setText(self._settings.get("export_font_size", "100%"))
        self._txt_font_size.setPlaceholderText("e.g. 100%, 24px, 12pt, 1.2em")
        style_form.addRow("Font Size:", self._txt_font_size)

        def add_color_row(label, line_edit, default_val, placeholder):
            line_edit.setText(self._settings.get(default_val[0], default_val[1]))
            line_edit.setPlaceholderText(placeholder)
            btn = QPushButton("🎨")
            btn.setFixedWidth(28)
            btn.clicked.connect(lambda: self._pick_color(line_edit))
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(line_edit)
            row_layout.addWidget(btn)
            style_form.addRow(label, row_layout)

        self._txt_fill_color = QLineEdit()
        add_color_row("Text Color:", self._txt_fill_color, ("export_fill_color", "#FFFFFF"), "e.g. #FFFFFF, #FF0000")

        self._txt_bg_color = QLineEdit()
        add_color_row("Background Color:", self._txt_bg_color, ("export_background_color", "#00000000"), "e.g. #00000000, #000000CC")

        self._cmb_text_align = QComboBox()
        self._cmb_text_align.addItems(_TEXT_ALIGNS)
        self._cmb_text_align.setCurrentText(self._settings.get("export_text_align", "center"))
        style_form.addRow("Text Align:", self._cmb_text_align)

        style_group.setLayout(style_form)
        forms_layout.addWidget(style_group)

        # ── Caption Placement group ──────────────────────────────────────
        placement_group = QGroupBox("Caption Placement (TTML-family only)")
        placement_form = QFormLayout()

        self._txt_region_origin = QLineEdit()
        self._txt_region_origin.setText(self._settings.get("export_region_origin", "10% 80%"))
        self._txt_region_origin.setPlaceholderText("e.g. 10% 80%")
        self._txt_region_origin.setToolTip("X and Y coordinates as percentages, e.g. 10% 80%")
        placement_form.addRow("Origin (X% Y%):", self._txt_region_origin)

        self._txt_region_extent = QLineEdit()
        self._txt_region_extent.setText(self._settings.get("export_region_extent", "80% 15%"))
        self._txt_region_extent.setPlaceholderText("e.g. 80% 15%")
        self._txt_region_extent.setToolTip("Width and Height as percentages, e.g. 80% 15%")
        placement_form.addRow("Extent (W% H%):", self._txt_region_extent)

        placement_group.setLayout(placement_form)
        forms_layout.addWidget(placement_group)

        # ── Whisper / Model group ────────────────────────────────────────
        model_group = QGroupBox("Whisper Model")
        model_form = QFormLayout()

        self._cmb_model = QComboBox()
        self._cmb_model.addItems(_WHISPER_MODELS)
        self._cmb_model.setCurrentText(self._settings.get("whisper_model", "base"))
        model_form.addRow("Model:", self._cmb_model)

        self._cmb_device = QComboBox()
        self._cmb_device.addItems(_WHISPER_DEVICES)
        self._cmb_device.setCurrentText(self._settings.get("whisper_device", "auto"))
        model_form.addRow("Device:", self._cmb_device)

        self._cmb_compute = QComboBox()
        self._cmb_compute.addItems(_WHISPER_COMPUTE_TYPES)
        self._cmb_compute.setCurrentText(self._settings.get("whisper_compute_type", "int8"))
        model_form.addRow("Compute Type:", self._cmb_compute)

        model_group.setLayout(model_form)
        forms_layout.addWidget(model_group)

        # ── Note ─────────────────────────────────────────────────────────
        note = QLabel(
            "TTML / EBU-TT / SMPTE-TT: all style and placement defaults apply.\n"
            "EBU STL: only Text Align is used.\n"
            "MCC: only Text Color is mapped (to CEA-608 color codes).\n"
            "Note: These settings dictate exported metadata. Final visual fidelity depends on the downstream importer (e.g. Premiere Pro).\n"
            "Whisper settings take effect on the next transcription."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px; margin-top: 4px;")
        forms_layout.addWidget(note)

        forms_layout.addStretch()

        # Right side: live preview
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        preview_label = QLabel("Style Design Preview")
        preview_label.setStyleSheet("font-weight: bold; font-size: 12px; margin-bottom: 4px;")
        preview_layout.addWidget(preview_label)

        self._preview = StylePreviewWidget()
        preview_layout.addWidget(self._preview, 1)

        preview_hint = QLabel(
            "Shows how captions will appear with the current style.\n"
            "Dashed box = caption region position and size."
        )
        preview_hint.setWordWrap(True)
        preview_hint.setStyleSheet("color: gray; font-size: 10px; margin-top: 4px;")
        preview_layout.addWidget(preview_hint)

        content_splitter.addWidget(forms_widget)
        content_splitter.addWidget(preview_container)
        content_splitter.setSizes([400, 320])

        layout.addWidget(content_splitter, 1)

        # ── Buttons ──────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Wire live preview updates from all style fields
        self._txt_font_family.currentFontChanged.connect(lambda: self._update_preview())
        self._txt_font_size.textChanged.connect(lambda: self._update_preview())
        self._txt_fill_color.textChanged.connect(lambda: self._update_preview())
        self._txt_bg_color.textChanged.connect(lambda: self._update_preview())
        self._cmb_text_align.currentTextChanged.connect(lambda: self._update_preview())
        self._txt_region_origin.textChanged.connect(lambda: self._update_preview())
        self._txt_region_extent.textChanged.connect(lambda: self._update_preview())

        # Populate preset combo and initial preview
        self._refresh_presets()
        self._update_preview()

    # ── Preview ──────────────────────────────────────────────────────────

    def _update_preview(self):
        """Push current style field values to the preview widget."""
        self._preview.set_style(
            font_family=self._txt_font_family.currentFont().family(),
            font_size_str=self._txt_font_size.text().strip(),
            fill_color=self._txt_fill_color.text().strip(),
            bg_color=self._txt_bg_color.text().strip(),
            text_align=self._cmb_text_align.currentText(),
            region_origin=self._txt_region_origin.text().strip(),
            region_extent=self._txt_region_extent.text().strip(),
        )

    def _pick_color(self, line_edit: QLineEdit):
        current = line_edit.text().strip()
        initial_color = QColor(current) if QColor.isValidColorName(current) else Qt.white
        
        color = QColorDialog.getColor(initial_color, self, "Pick Color", QColorDialog.ShowAlphaChannel)
        if color.isValid():
            if color.alpha() < 255:
                line_edit.setText(color.name(QColor.HexArgb))
            else:
                line_edit.setText(color.name())

    # ── Preset management ────────────────────────────────────────────────

    def _refresh_presets(self):
        """Rebuild the preset combo from built-in + user presets."""
        self._cmb_preset.clear()
        self._cmb_preset.addItem("(current settings)")

        # Built-in presets
        for name in sorted(BUILTIN_PRESETS):
            self._cmb_preset.addItem(f"📦 {name}")

        # User presets (if any)
        user_presets = self._settings.get_style_presets()
        if user_presets:
            self._cmb_preset.addItem(_PRESET_SEPARATOR)
            # Make separator unselectable
            idx = self._cmb_preset.count() - 1
            self._cmb_preset.model().item(idx).setEnabled(False)
            for name in sorted(user_presets):
                self._cmb_preset.addItem(f"💾 {name}")

        self._update_delete_button()

    def _get_selected_preset_name(self) -> tuple[str | None, bool]:
        """Return (preset_name, is_builtin) or (None, False) if none selected."""
        text = self._cmb_preset.currentText()
        if text.startswith("📦 "):
            return text[2:].strip(), True
        if text.startswith("💾 "):
            return text[2:].strip(), False
        return None, False

    def _update_delete_button(self):
        """Enable Delete only for user presets."""
        name, is_builtin = self._get_selected_preset_name()
        self._btn_delete_preset.setEnabled(name is not None and not is_builtin)

    def _on_preset_changed(self, idx=0):
        """Update delete button state and auto-load preset."""
        self._update_delete_button()
        self._load_preset()

    def _load_preset(self):
        """Load the selected preset into the style fields."""
        name, is_builtin = self._get_selected_preset_name()
        if name is None:
            return

        if is_builtin:
            style = BUILTIN_PRESETS.get(name, {})
        else:
            user_presets = self._settings.get_style_presets()
            style = user_presets.get(name, {})

        if not style:
            return

        self._txt_font_family.setCurrentFont(QFont(style.get("export_font_family", "Arial")))
        self._txt_font_size.setText(style.get("export_font_size", "100%"))
        self._txt_fill_color.setText(style.get("export_fill_color", "#FFFFFF"))
        self._txt_bg_color.setText(style.get("export_background_color", "#00000000"))
        self._txt_region_origin.setText(style.get("export_region_origin", "10% 80%"))
        self._txt_region_extent.setText(style.get("export_region_extent", "80% 15%"))

        align = style.get("export_text_align", "center")
        idx = self._cmb_text_align.findText(align)
        if idx >= 0:
            self._cmb_text_align.setCurrentIndex(idx)

        # Preview auto-updates via textChanged signals

    def _save_preset(self):
        """Save current style fields as a new named preset."""
        name, ok = QInputDialog.getText(
            self, "Save Style Preset",
            "Enter a name for this style preset:",
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        # Don't allow overwriting built-in preset names
        if name in BUILTIN_PRESETS:
            QMessageBox.warning(
                self, "Reserved Name",
                f'"{name}" is a built-in preset name and cannot be overwritten.'
            )
            return

        style = self._read_style_fields()
        self._settings.save_style_preset(name, style)
        self._refresh_presets()

        # Select the newly saved preset and update Delete button state
        for i in range(self._cmb_preset.count()):
            if self._cmb_preset.itemText(i) == f"💾 {name}":
                self._cmb_preset.setCurrentIndex(i)
                break
        self._update_delete_button()

    def _delete_preset(self):
        """Delete the selected user preset."""
        name, is_builtin = self._get_selected_preset_name()
        if name is None or is_builtin:
            return

        reply = QMessageBox.question(
            self, "Delete Preset",
            f'Delete the style preset "{name}"?',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._settings.delete_style_preset(name)
            self._refresh_presets()

    def _read_style_fields(self) -> dict:
        """Read current values from the style form fields."""
        return {
            "export_font_family": self._txt_font_family.currentFont().family() or "Arial",
            "export_font_size": self._txt_font_size.text().strip() or "100%",
            "export_fill_color": self._txt_fill_color.text().strip() or "#FFFFFF",
            "export_background_color": self._txt_bg_color.text().strip() or "#00000000",
            "export_text_align": self._cmb_text_align.currentText(),
            "export_region_origin": self._txt_region_origin.text().strip() or "10% 80%",
            "export_region_extent": self._txt_region_extent.text().strip() or "80% 15%",
        }

    def accept(self):
        # Whisper settings
        self._settings.set("whisper_model", self._cmb_model.currentText())
        self._settings.set("whisper_device", self._cmb_device.currentText())
        self._settings.set("whisper_compute_type", self._cmb_compute.currentText())

        # Export style defaults — validate freeform fields
        font_family = self._txt_font_family.currentFont().family() or "Arial"

        raw_font_size = self._txt_font_size.text().strip()
        font_size = validate_font_size(raw_font_size)

        raw_fill_color = self._txt_fill_color.text().strip()
        fill_color = validate_fill_color(raw_fill_color)

        raw_bg_color = self._txt_bg_color.text().strip()
        bg_color = validate_background_color(raw_bg_color)

        # Collect normalization warnings
        warnings = []
        if raw_font_size and font_size != raw_font_size:
            warnings.append(f"Font Size '{raw_font_size}' is not a valid CSS size "
                            f"(e.g. 100%, 24px, 12pt, 1.2em). Reset to '{font_size}'.")
        if raw_fill_color and fill_color != raw_fill_color and fill_color != raw_fill_color.upper():
            warnings.append(f"Text Color '{raw_fill_color}' is not a valid hex color "
                            f"(e.g. #FFFFFF, #FF0000). Reset to '{fill_color}'.")
        if raw_bg_color and bg_color != raw_bg_color and bg_color != raw_bg_color.upper():
            warnings.append(f"Background Color '{raw_bg_color}' is not a valid hex color "
                            f"(e.g. #00000000, #000000CC). Reset to '{bg_color}'.")

        raw_origin = self._txt_region_origin.text().strip()
        region_origin = validate_region_origin(raw_origin)
        if raw_origin and region_origin != raw_origin:
            warnings.append(f"Region Origin '{raw_origin}' is not a valid placement "
                            f"(expected X% Y%, e.g. 10% 80%). Reset to '{region_origin}'.")

        raw_extent = self._txt_region_extent.text().strip()
        region_extent = validate_region_extent(raw_extent)
        if raw_extent and region_extent != raw_extent:
            warnings.append(f"Region Extent '{raw_extent}' is not a valid placement "
                            f"(expected W% H%, e.g. 80% 15%). Reset to '{region_extent}'.")

        if warnings:
            QMessageBox.warning(self, "Settings Normalized", "\n".join(warnings))
            # Update the text fields to show the normalized values
            self._txt_font_size.setText(font_size)
            self._txt_fill_color.setText(fill_color)
            self._txt_bg_color.setText(bg_color)
            self._txt_region_origin.setText(region_origin)
            self._txt_region_extent.setText(region_extent)

        self._settings.set("export_font_family", font_family)
        self._settings.set("export_font_size", font_size)
        self._settings.set("export_fill_color", fill_color)
        self._settings.set("export_background_color", bg_color)
        self._settings.set("export_text_align", self._cmb_text_align.currentText())
        self._settings.set("export_region_origin", region_origin)
        self._settings.set("export_region_extent", region_extent)

        self._settings.save()
        super().accept()
