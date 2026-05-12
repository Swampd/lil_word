"""Caption rules dialog with timing presets for configuring extraction settings.

Exposes timing parameters (lead-in, lead-out, duration limits, gap, CPS,
line/character limits) with named timing presets for quick iteration on
caption feel without manually tuning each knob.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QDialogButtonBox, QSpinBox,
    QGroupBox, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QInputDialog, QMessageBox,
)
from app.utils.settings import Settings


# Keys that make up a timing preset
_TIMING_KEYS = [
    "lead_in_ms", "lead_out_ms", "min_caption_ms", "max_caption_ms",
    "min_gap_ms", "target_cps_min", "target_cps_max",
    "max_chars_per_line", "max_lines",
]

# Built-in timing presets
BUILTIN_TIMING_PRESETS = {
    "Broadcast Standard": {
        "lead_in_ms": 150, "lead_out_ms": 250,
        "min_caption_ms": 700, "max_caption_ms": 3500,
        "min_gap_ms": 100, "target_cps_min": 12, "target_cps_max": 20,
        "max_chars_per_line": 42, "max_lines": 2,
    },
    "Relaxed Reading": {
        "lead_in_ms": 150, "lead_out_ms": 250,
        "min_caption_ms": 1000, "max_caption_ms": 5000,
        "min_gap_ms": 120, "target_cps_min": 10, "target_cps_max": 15,
        "max_chars_per_line": 38, "max_lines": 2,
    },
    "Fast Pacing": {
        "lead_in_ms": 50, "lead_out_ms": 80,
        "min_caption_ms": 500, "max_caption_ms": 3000,
        "min_gap_ms": 40, "target_cps_min": 15, "target_cps_max": 22,
        "max_chars_per_line": 42, "max_lines": 2,
    },
    "Tight Voiceover": {
        "lead_in_ms": 80, "lead_out_ms": 100,
        "min_caption_ms": 600, "max_caption_ms": 3500,
        "min_gap_ms": 60, "target_cps_min": 14, "target_cps_max": 20,
        "max_chars_per_line": 40, "max_lines": 2,
    },
}

_PRESET_SEPARATOR = "──────────"


class CaptionRulesDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Caption Rules")
        self._settings = settings

        layout = QVBoxLayout(self)

        # ── Header ───────────────────────────────────────────────────────
        header = QLabel(
            "Timing presets let you quickly try different caption feels.\n"
            "Load a preset, fine-tune the knobs below, then save your own."
        )
        header.setWordWrap(True)
        header.setStyleSheet("font-size: 12px; margin-bottom: 6px;")
        layout.addWidget(header)

        # ── Timing Presets group ─────────────────────────────────────────
        preset_group = QGroupBox("Timing Presets")
        preset_layout = QVBoxLayout()

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self._cmb_preset = QComboBox()
        self._cmb_preset.setMinimumWidth(180)
        preset_row.addWidget(self._cmb_preset, 1)

        self._btn_load_preset = QPushButton("Load")
        self._btn_load_preset.setToolTip("Apply the selected preset values to the timing knobs below.")
        self._btn_save_preset = QPushButton("Save As…")
        self._btn_save_preset.setToolTip("Save the current timing knobs as a named preset.")
        self._btn_delete_preset = QPushButton("Delete")
        self._btn_delete_preset.setToolTip("Delete the selected user preset.")
        preset_row.addWidget(self._btn_load_preset)
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

        self._btn_load_preset.clicked.connect(self._load_preset)
        self._btn_save_preset.clicked.connect(self._save_preset)
        self._btn_delete_preset.clicked.connect(self._delete_preset)
        self._cmb_preset.currentIndexChanged.connect(
            lambda _: self._update_delete_button()
        )

        # ── Timing knobs ─────────────────────────────────────────────────
        form = QFormLayout()

        # Maximum characters per line
        self._spi_max_cpl = QSpinBox()
        self._spi_max_cpl.setRange(10, 100)
        self._spi_max_cpl.setValue(self._settings.get("max_chars_per_line", 42))
        form.addRow("Max Chars Per Line:", self._spi_max_cpl)

        # Maximum lines
        self._spi_max_lines = QSpinBox()
        self._spi_max_lines.setRange(1, 4)
        self._spi_max_lines.setValue(self._settings.get("max_lines", 2))
        form.addRow("Max Lines:", self._spi_max_lines)

        # Max duration ms
        self._spi_max_dur = QSpinBox()
        self._spi_max_dur.setRange(1000, 10000)
        self._spi_max_dur.setSingleStep(100)
        self._spi_max_dur.setSuffix(" ms")
        self._spi_max_dur.setValue(self._settings.get("max_caption_ms", 3500))
        form.addRow("Max Duration:", self._spi_max_dur)

        # Min duration ms
        self._spi_min_dur = QSpinBox()
        self._spi_min_dur.setRange(100, 2000)
        self._spi_min_dur.setSingleStep(100)
        self._spi_min_dur.setSuffix(" ms")
        self._spi_min_dur.setValue(self._settings.get("min_caption_ms", 700))
        form.addRow("Min Duration:", self._spi_min_dur)

        # Min gap ms
        self._spi_min_gap = QSpinBox()
        self._spi_min_gap.setRange(0, 1000)
        self._spi_min_gap.setSingleStep(10)
        self._spi_min_gap.setSuffix(" ms")
        self._spi_min_gap.setValue(self._settings.get("min_gap_ms", 100))
        form.addRow("Min Gap:", self._spi_min_gap)

        # Lead in ms
        self._spi_lead_in = QSpinBox()
        self._spi_lead_in.setRange(0, 1000)
        self._spi_lead_in.setSingleStep(10)
        self._spi_lead_in.setSuffix(" ms")
        self._spi_lead_in.setValue(self._settings.get("lead_in_ms", 150))
        form.addRow("Lead-in Pad:", self._spi_lead_in)

        # Lead out ms
        self._spi_lead_out = QSpinBox()
        self._spi_lead_out.setRange(0, 1000)
        self._spi_lead_out.setSingleStep(10)
        self._spi_lead_out.setSuffix(" ms")
        self._spi_lead_out.setValue(self._settings.get("lead_out_ms", 250))
        form.addRow("Lead-out Pad:", self._spi_lead_out)

        # Target CPS Min
        self._spi_cps_min = QSpinBox()
        self._spi_cps_min.setRange(5, 30)
        self._spi_cps_min.setSuffix(" chars/sec")
        self._spi_cps_min.setValue(self._settings.get("target_cps_min", 12))
        form.addRow("Min Reading Speed:", self._spi_cps_min)

        # Target CPS Max
        self._spi_cps_max = QSpinBox()
        self._spi_cps_max.setRange(5, 50)
        self._spi_cps_max.setSuffix(" chars/sec")
        self._spi_cps_max.setValue(self._settings.get("target_cps_max", 20))
        form.addRow("Max Reading Speed:", self._spi_cps_max)

        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Populate preset combo
        self._refresh_presets()

    # ── Preset management ────────────────────────────────────────────────

    def _refresh_presets(self):
        """Rebuild the preset combo from built-in + user presets."""
        self._cmb_preset.clear()
        self._cmb_preset.addItem("(current settings)")

        for name in sorted(BUILTIN_TIMING_PRESETS):
            self._cmb_preset.addItem(f"📦 {name}")

        user_presets = self._settings.get("timing_presets", {})
        if user_presets:
            self._cmb_preset.addItem(_PRESET_SEPARATOR)
            idx = self._cmb_preset.count() - 1
            self._cmb_preset.model().item(idx).setEnabled(False)
            for name in sorted(user_presets):
                self._cmb_preset.addItem(f"💾 {name}")

        self._update_delete_button()

    def _get_selected_preset_name(self) -> tuple[str | None, bool]:
        text = self._cmb_preset.currentText()
        if text.startswith("📦 "):
            return text[2:].strip(), True
        if text.startswith("💾 "):
            return text[2:].strip(), False
        return None, False

    def _update_delete_button(self):
        name, is_builtin = self._get_selected_preset_name()
        self._btn_delete_preset.setEnabled(name is not None and not is_builtin)

    def _load_preset(self):
        name, is_builtin = self._get_selected_preset_name()
        if name is None:
            return

        if is_builtin:
            vals = BUILTIN_TIMING_PRESETS.get(name, {})
        else:
            user_presets = self._settings.get("timing_presets", {})
            vals = user_presets.get(name, {})

        if not vals:
            return

        self._spi_max_cpl.setValue(vals.get("max_chars_per_line", 42))
        self._spi_max_lines.setValue(vals.get("max_lines", 2))
        self._spi_max_dur.setValue(vals.get("max_caption_ms", 3500))
        self._spi_min_dur.setValue(vals.get("min_caption_ms", 700))
        self._spi_min_gap.setValue(vals.get("min_gap_ms", 100))
        self._spi_lead_in.setValue(vals.get("lead_in_ms", 150))
        self._spi_lead_out.setValue(vals.get("lead_out_ms", 250))
        self._spi_cps_min.setValue(vals.get("target_cps_min", 12))
        self._spi_cps_max.setValue(vals.get("target_cps_max", 20))

    def _save_preset(self):
        name, ok = QInputDialog.getText(
            self, "Save Timing Preset",
            "Enter a name for this timing preset:",
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        if name in BUILTIN_TIMING_PRESETS:
            QMessageBox.warning(
                self, "Reserved Name",
                f'"{name}" is a built-in preset name and cannot be overwritten.'
            )
            return

        vals = self._read_timing_fields()
        presets = self._settings.get("timing_presets", {})
        presets[name] = vals
        self._settings.set("timing_presets", presets)
        self._settings.save()
        self._refresh_presets()

        for i in range(self._cmb_preset.count()):
            if self._cmb_preset.itemText(i) == f"💾 {name}":
                self._cmb_preset.setCurrentIndex(i)
                break
        self._update_delete_button()

    def _delete_preset(self):
        name, is_builtin = self._get_selected_preset_name()
        if name is None or is_builtin:
            return

        reply = QMessageBox.question(
            self, "Delete Preset",
            f'Delete the timing preset "{name}"?',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            presets = self._settings.get("timing_presets", {})
            presets.pop(name, None)
            self._settings.set("timing_presets", presets)
            self._settings.save()
            self._refresh_presets()

    def _read_timing_fields(self) -> dict:
        return {
            "max_chars_per_line": self._spi_max_cpl.value(),
            "max_lines": self._spi_max_lines.value(),
            "max_caption_ms": self._spi_max_dur.value(),
            "min_caption_ms": self._spi_min_dur.value(),
            "min_gap_ms": self._spi_min_gap.value(),
            "lead_in_ms": self._spi_lead_in.value(),
            "lead_out_ms": self._spi_lead_out.value(),
            "target_cps_min": self._spi_cps_min.value(),
            "target_cps_max": self._spi_cps_max.value(),
        }

    def accept(self):
        self._settings.set("max_chars_per_line", self._spi_max_cpl.value())
        self._settings.set("max_lines", self._spi_max_lines.value())
        self._settings.set("max_caption_ms", self._spi_max_dur.value())
        self._settings.set("min_caption_ms", self._spi_min_dur.value())
        self._settings.set("min_gap_ms", self._spi_min_gap.value())
        self._settings.set("lead_in_ms", self._spi_lead_in.value())
        self._settings.set("lead_out_ms", self._spi_lead_out.value())
        
        min_cps = self._spi_cps_min.value()
        max_cps = self._spi_cps_max.value()
        if min_cps > max_cps:
            min_cps, max_cps = max_cps, min_cps
            
        self._settings.set("target_cps_min", min_cps)
        self._settings.set("target_cps_max", max_cps)
        self._settings.save()
        super().accept()
