"""Tests for style preset management in Settings and ExportSettingsDialog."""

import sys
import tempfile
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont

from app.utils.settings import Settings, BUILTIN_PRESETS
from app.ui.export_settings_dialog import ExportSettingsDialog, StylePreviewWidget


def _ensure_app():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    return app


# ── Settings preset API tests ────────────────────────────────────────────


def test_builtin_presets_exist():
    """Verify built-in presets are shipped and have all required keys."""
    assert len(BUILTIN_PRESETS) >= 3
    for name, style in BUILTIN_PRESETS.items():
        for key in Settings._STYLE_KEYS:
            assert key in style, f"Built-in preset '{name}' missing key '{key}'"


def test_save_and_load_user_preset():
    """Verify user presets roundtrip through save/load."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        settings_file = f.name

    try:
        settings = Settings(settings_file)

        # No presets initially
        assert settings.get_style_presets() == {}

        # Save a preset
        style = {
            "export_font_family": "Comic Sans",
            "export_font_size": "200%",
            "export_fill_color": "#FF0000",
            "export_background_color": "#00FF00FF",
            "export_text_align": "left",
            "export_region_origin": "5% 70%",
            "export_region_extent": "90% 20%",
        }
        settings.save_style_preset("My Preset", style)

        # Load it back
        presets = settings.get_style_presets()
        assert "My Preset" in presets
        assert presets["My Preset"]["export_font_family"] == "Comic Sans"
        assert presets["My Preset"]["export_font_size"] == "200%"
        assert presets["My Preset"]["export_fill_color"] == "#FF0000"

        # Verify it persists across Settings instances
        settings2 = Settings(settings_file)
        presets2 = settings2.get_style_presets()
        assert "My Preset" in presets2
        assert presets2["My Preset"]["export_font_family"] == "Comic Sans"
    finally:
        Path(settings_file).unlink(missing_ok=True)


def test_delete_user_preset():
    """Verify preset deletion works."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        settings_file = f.name

    try:
        settings = Settings(settings_file)
        settings.save_style_preset("Deletable", {"export_font_family": "Times"})
        assert "Deletable" in settings.get_style_presets()

        settings.delete_style_preset("Deletable")
        assert "Deletable" not in settings.get_style_presets()
    finally:
        os.unlink(settings_file)


def test_get_current_style():
    """Verify get_current_style returns current setting values."""
    settings = Settings()
    style = settings.get_current_style()
    assert style["export_font_family"] == "Arial"
    assert style["export_font_size"] == "100%"
    assert len(style) == len(Settings._STYLE_KEYS)


def test_apply_style():
    """Verify apply_style updates settings values."""
    settings = Settings()
    style = {"export_font_family": "Verdana", "export_fill_color": "#123456"}
    settings.apply_style(style)
    assert settings.get("export_font_family") == "Verdana"
    assert settings.get("export_fill_color") == "#123456"
    # Unchanged keys stay at defaults
    assert settings.get("export_font_size") == "100%"


# ── Dialog tests ─────────────────────────────────────────────────────────


def test_dialog_structure_style_first():
    """Verify dialog groups are ordered so style comes before Whisper settings."""
    app = _ensure_app()
    settings = Settings()
    dlg = ExportSettingsDialog(settings)

    from PySide6.QtWidgets import QGroupBox
    groups = dlg.findChildren(QGroupBox)
    titles = [g.title() for g in groups]

    # Verify all expected groups exist
    assert "Style Presets" in titles
    assert "Caption Appearance" in titles
    assert "Caption Placement (TTML-family only)" in titles
    assert "Whisper Model" in titles

    # Verify Whisper Model comes AFTER Caption Appearance
    idx_appearance = titles.index("Caption Appearance")
    idx_whisper = titles.index("Whisper Model")
    assert idx_appearance < idx_whisper


def test_dialog_title_and_header_wording():
    """Verify dialog title and explanatory header reflect the style-first workflow."""
    app = _ensure_app()
    settings = Settings()
    dlg = ExportSettingsDialog(settings)

    # Verify window title
    assert "Caption Styles" in dlg.windowTitle()

    # Find the explanatory header label (it's the first QLabel added directly to the dialog layout)
    from PySide6.QtWidgets import QLabel
    labels = dlg.findChildren(QLabel)
    header_text = ""
    for label in labels:
        if "Design your caption look" in label.text():
            header_text = label.text()
            break

    # Verify header explicitly focuses on style design and mentions Whisper settings are below
    assert header_text != ""
    assert "Design your caption look" in header_text
    assert "Whisper model settings are configured below" in header_text


def test_dialog_note_downstream_importer_wording():
    """Verify dialog note clarifies export metadata vs downstream importer rendering."""
    app = _ensure_app()
    settings = Settings()
    dlg = ExportSettingsDialog(settings)

    from PySide6.QtWidgets import QLabel
    labels = dlg.findChildren(QLabel)
    note_text = ""
    for label in labels:
        if "TTML / EBU-TT / SMPTE-TT" in label.text():
            note_text = label.text()
            break

    assert note_text != ""
    assert "metadata" in note_text.lower()
    assert "downstream importer" in note_text.lower()
    assert "Premiere Pro" in note_text


def test_dialog_has_preset_controls():
    """Verify ExportSettingsDialog has preset combo, Save As, Delete buttons."""
    app = _ensure_app()
    settings = Settings()
    dlg = ExportSettingsDialog(settings)

    assert hasattr(dlg, '_cmb_preset')
    assert hasattr(dlg, '_btn_save_preset')
    assert hasattr(dlg, '_btn_delete_preset')


def test_dialog_preset_combo_has_builtins():
    """Verify the preset combo lists built-in presets."""
    app = _ensure_app()
    settings = Settings()
    dlg = ExportSettingsDialog(settings)

    items = [dlg._cmb_preset.itemText(i) for i in range(dlg._cmb_preset.count())]
    # Should have "(current settings)" + 3 built-in presets
    assert items[0] == "(current settings)"
    builtin_items = [i for i in items if i.startswith("📦")]
    assert len(builtin_items) == len(BUILTIN_PRESETS)


def test_dialog_load_builtin_preset():
    """Verify loading a built-in preset populates the style fields."""
    app = _ensure_app()
    settings = Settings()
    dlg = ExportSettingsDialog(settings)

    # Select "📦 Cinema Subtitles" - this will auto-load now
    for i in range(dlg._cmb_preset.count()):
        if "Cinema Subtitles" in dlg._cmb_preset.itemText(i):
            dlg._cmb_preset.setCurrentIndex(i)
            break

    cinema = BUILTIN_PRESETS["Cinema Subtitles"]
    # Due to OS fallback, we just check that setting happened without asserting the exact native mapped string
    assert dlg._txt_font_size.text() == cinema["export_font_size"]
    assert dlg._txt_fill_color.text() == cinema["export_fill_color"]


def test_dialog_shows_user_presets():
    """Verify user presets appear in the combo with 💾 prefix."""
    app = _ensure_app()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        settings_file = f.name

    try:
        settings = Settings(settings_file)
        settings.save_style_preset("My Custom", {"export_font_family": "Courier"})

        dlg = ExportSettingsDialog(settings)
        items = [dlg._cmb_preset.itemText(i) for i in range(dlg._cmb_preset.count())]
        user_items = [i for i in items if i.startswith("💾")]
        assert len(user_items) == 1
        assert "My Custom" in user_items[0]
    finally:
        os.unlink(settings_file)


def test_dialog_delete_button_disabled_for_builtins():
    """Verify Delete is disabled when a built-in preset is selected."""
    app = _ensure_app()
    settings = Settings()
    dlg = ExportSettingsDialog(settings)

    # Select a built-in — signal should auto-update Delete button
    for i in range(dlg._cmb_preset.count()):
        if dlg._cmb_preset.itemText(i).startswith("📦"):
            dlg._cmb_preset.setCurrentIndex(i)
            break

    assert not dlg._btn_delete_preset.isEnabled()


def test_dialog_delete_button_disabled_for_current_settings():
    """Verify Delete is disabled for the '(current settings)' entry."""
    app = _ensure_app()
    settings = Settings()
    dlg = ExportSettingsDialog(settings)

    dlg._cmb_preset.setCurrentIndex(0)  # "(current settings)"
    assert not dlg._btn_delete_preset.isEnabled()


def test_selecting_user_preset_enables_delete():
    """Verify that selecting a user preset in the combo enables Delete."""
    app = _ensure_app()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        settings_file = f.name

    try:
        settings = Settings(settings_file)
        settings.save_style_preset("UserStyle", {"export_font_family": "Courier"})

        dlg = ExportSettingsDialog(settings)

        # Start on "(current settings)" — Delete should be disabled
        dlg._cmb_preset.setCurrentIndex(0)
        assert not dlg._btn_delete_preset.isEnabled()

        # Select the user preset — Delete should become enabled via signal
        for i in range(dlg._cmb_preset.count()):
            if "UserStyle" in dlg._cmb_preset.itemText(i):
                dlg._cmb_preset.setCurrentIndex(i)
                break

        assert dlg._btn_delete_preset.isEnabled()
    finally:
        os.unlink(settings_file)


def test_save_as_creates_deletable_preset():
    """Verify Save As… creates a user preset that is immediately deletable."""
    app = _ensure_app()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        settings_file = f.name

    try:
        settings = Settings(settings_file)
        dlg = ExportSettingsDialog(settings)

        # Initially no user presets
        user_items = [dlg._cmb_preset.itemText(i) for i in range(dlg._cmb_preset.count())
                      if dlg._cmb_preset.itemText(i).startswith("💾")]
        assert len(user_items) == 0

        # Mock QInputDialog to return a preset name
        with patch("app.ui.export_settings_dialog.QInputDialog.getText",
                    return_value=("TestPreset", True)):
            dlg._save_preset()

        # Preset should now exist in settings
        assert "TestPreset" in settings.get_style_presets()

        # Combo should have the new user preset selected
        assert "TestPreset" in dlg._cmb_preset.currentText()

        # Delete should be enabled because a user preset is selected
        assert dlg._btn_delete_preset.isEnabled()
    finally:
        os.unlink(settings_file)


def test_delete_removes_preset_and_disables_button():
    """Verify Delete removes the user preset and disables the Delete button."""
    app = _ensure_app()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        settings_file = f.name

    try:
        settings = Settings(settings_file)
        settings.save_style_preset("ToDelete", {"export_font_family": "Trebuchet"})

        dlg = ExportSettingsDialog(settings)

        # Select the user preset
        for i in range(dlg._cmb_preset.count()):
            if "ToDelete" in dlg._cmb_preset.itemText(i):
                dlg._cmb_preset.setCurrentIndex(i)
                break
        assert dlg._btn_delete_preset.isEnabled()

        # Mock QMessageBox.question to return Yes
        with patch("app.ui.export_settings_dialog.QMessageBox.question",
                    return_value=QMessageBox.Yes):
            dlg._delete_preset()

        # Preset should be gone from settings
        assert "ToDelete" not in settings.get_style_presets()

        # Combo should no longer have the deleted preset
        items = [dlg._cmb_preset.itemText(i) for i in range(dlg._cmb_preset.count())]
        assert not any("ToDelete" in item for item in items)

        # Delete should be disabled (back to current settings / builtin)
        assert not dlg._btn_delete_preset.isEnabled()
    finally:
        os.unlink(settings_file)


def test_save_as_rejects_builtin_name():
    """Verify Save As… rejects a name that matches a built-in preset."""
    app = _ensure_app()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        settings_file = f.name

    try:
        settings = Settings(settings_file)
        dlg = ExportSettingsDialog(settings)

        builtin_name = list(BUILTIN_PRESETS.keys())[0]

        # Mock QInputDialog to return a built-in name, then mock the warning
        with patch("app.ui.export_settings_dialog.QInputDialog.getText",
                    return_value=(builtin_name, True)), \
             patch("app.ui.export_settings_dialog.QMessageBox.warning"):
            dlg._save_preset()

        # Should NOT be saved as a user preset
        assert builtin_name not in settings.get_style_presets()
    finally:
        Path(settings_file).unlink(missing_ok=True)


# ── Preview widget tests ─────────────────────────────────────────────────


def test_preview_widget_exists_in_dialog():
    """Verify dialog has a StylePreviewWidget."""
    app = _ensure_app()
    settings = Settings()
    dlg = ExportSettingsDialog(settings)

    assert hasattr(dlg, '_preview')
    assert isinstance(dlg._preview, StylePreviewWidget)


def test_preview_widget_set_style():
    """Verify StylePreviewWidget accepts style updates without crashing."""
    app = _ensure_app()
    pw = StylePreviewWidget()
    pw.set_style(
        font_family="Courier New",
        font_size_str="120%",
        fill_color="#FF0000",
        bg_color="#000000CC",
        text_align="left",
        region_origin="5% 70%",
        region_extent="90% 20%",
    )
    # Verify internal state was updated
    assert pw._font_family == "Courier New"
    assert pw._fill_color == "#FF0000"
    assert pw._text_align == "left"


def test_preview_updates_on_field_change():
    """Verify preview updates when dialog style fields change."""
    app = _ensure_app()
    settings = Settings()
    dlg = ExportSettingsDialog(settings)

    # Change font family — preview should update
    dlg._txt_font_family.setCurrentFont(QFont("Impact"))
    dlg._txt_font_size.setText("150%")
    assert dlg._preview._font_family == "Impact"

    # Change fill color
    dlg._txt_fill_color.setText("#00FF00")
    assert dlg._preview._fill_color == "#00FF00"

    # Change alignment
    dlg._cmb_text_align.setCurrentText("right")
    assert dlg._preview._text_align == "right"


def test_preview_updates_on_preset_load():
    """Verify preview reflects loaded preset values."""
    app = _ensure_app()
    settings = Settings()
    dlg = ExportSettingsDialog(settings)

    # Select and load Cinema Subtitles
    for i in range(dlg._cmb_preset.count()):
        if "Cinema Subtitles" in dlg._cmb_preset.itemText(i):
            dlg._cmb_preset.setCurrentIndex(i)
            break
    dlg._load_preset()

    cinema = BUILTIN_PRESETS["Cinema Subtitles"]
    assert dlg._preview._font_family == cinema["export_font_family"]
    assert dlg._preview._fill_color == cinema["export_fill_color"]


def test_preview_font_size_parsing():
    """Verify StylePreviewWidget parses CSS font sizes correctly."""
    assert StylePreviewWidget._parse_font_size("100%") == 16
    assert StylePreviewWidget._parse_font_size("200%") == 32
    assert StylePreviewWidget._parse_font_size("24px") == 24
    assert StylePreviewWidget._parse_font_size("12pt") == 16  # 12 * 4/3 = 16
    assert StylePreviewWidget._parse_font_size("1.5em") == 24  # 1.5 * 16
    assert StylePreviewWidget._parse_font_size("") == 16
    assert StylePreviewWidget._parse_font_size("invalid") == 16


def test_preview_region_parsing():
    """Verify region parsing for origin/extent."""
    assert StylePreviewWidget._parse_region("10% 80%", (0, 0)) == (0.10, 0.80)
    assert StylePreviewWidget._parse_region("5% 70%", (0, 0)) == (0.05, 0.70)
    assert StylePreviewWidget._parse_region("invalid", (0.1, 0.8)) == (0.1, 0.8)
    assert StylePreviewWidget._parse_region("", (0.1, 0.8)) == (0.1, 0.8)


def test_preview_handles_invalid_colors_gracefully():
    """Verify preview falls back to defaults for invalid colors."""
    app = _ensure_app()
    pw = StylePreviewWidget()
    pw.set_style(
        font_family="Arial",
        font_size_str="100%",
        fill_color="not-a-color",
        bg_color="also-bad",
        text_align="center",
        region_origin="10% 80%",
        region_extent="80% 15%",
    )
    # Should fall back to defaults
    assert pw._fill_color == "#FFFFFF"
    assert pw._bg_color == "#00000000"
