"""Tests for timing presets in CaptionRulesDialog and split feedback in CaptionPanel."""

import sys
import tempfile
import os
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

from app.utils.settings import Settings
from app.ui.caption_rules_dialog import CaptionRulesDialog, BUILTIN_TIMING_PRESETS, _TIMING_KEYS
from app.ui.caption_panel import CaptionPanel
from app.models.caption import Caption


def _ensure_app():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    return app


# ── Timing preset tests ─────────────────────────────────────────────────


def test_builtin_timing_presets_exist():
    """Verify built-in timing presets are shipped and complete."""
    assert len(BUILTIN_TIMING_PRESETS) >= 4
    for name, vals in BUILTIN_TIMING_PRESETS.items():
        for key in _TIMING_KEYS:
            assert key in vals, f"Built-in timing preset '{name}' missing key '{key}'"


def test_rules_dialog_has_preset_controls():
    """Verify CaptionRulesDialog has preset combo and buttons."""
    app = _ensure_app()
    settings = Settings()
    dlg = CaptionRulesDialog(settings)

    assert hasattr(dlg, '_cmb_preset')
    assert hasattr(dlg, '_btn_load_preset')
    assert hasattr(dlg, '_btn_save_preset')
    assert hasattr(dlg, '_btn_delete_preset')


def test_rules_dialog_preset_combo_has_builtins():
    """Verify the preset combo lists built-in timing presets."""
    app = _ensure_app()
    settings = Settings()
    dlg = CaptionRulesDialog(settings)

    items = [dlg._cmb_preset.itemText(i) for i in range(dlg._cmb_preset.count())]
    assert items[0] == "(current settings)"
    builtin_items = [i for i in items if i.startswith("📦")]
    assert len(builtin_items) == len(BUILTIN_TIMING_PRESETS)


def test_rules_dialog_load_builtin_preset():
    """Verify loading a built-in timing preset populates knobs."""
    app = _ensure_app()
    settings = Settings()
    dlg = CaptionRulesDialog(settings)

    # Select Relaxed Reading
    for i in range(dlg._cmb_preset.count()):
        if "Relaxed Reading" in dlg._cmb_preset.itemText(i):
            dlg._cmb_preset.setCurrentIndex(i)
            break

    dlg._load_preset()

    relaxed = BUILTIN_TIMING_PRESETS["Relaxed Reading"]
    assert dlg._spi_lead_in.value() == relaxed["lead_in_ms"]
    assert dlg._spi_lead_out.value() == relaxed["lead_out_ms"]
    assert dlg._spi_min_dur.value() == relaxed["min_caption_ms"]
    assert dlg._spi_max_dur.value() == relaxed["max_caption_ms"]
    assert dlg._spi_min_gap.value() == relaxed["min_gap_ms"]
    assert dlg._spi_cps_min.value() == relaxed["target_cps_min"]
    assert dlg._spi_cps_max.value() == relaxed["target_cps_max"]


def test_rules_dialog_save_user_preset():
    """Verify Save As… creates a user timing preset."""
    app = _ensure_app()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        settings_file = f.name

    try:
        settings = Settings(settings_file)
        dlg = CaptionRulesDialog(settings)

        with patch("app.ui.caption_rules_dialog.QInputDialog.getText",
                    return_value=("My Timing", True)):
            dlg._save_preset()

        presets = settings.get("timing_presets", {})
        assert "My Timing" in presets
        assert presets["My Timing"]["lead_in_ms"] == dlg._spi_lead_in.value()
    finally:
        os.unlink(settings_file)


def test_rules_dialog_delete_user_preset():
    """Verify Delete removes a user timing preset."""
    app = _ensure_app()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        settings_file = f.name

    try:
        settings = Settings(settings_file)
        # Manually create a preset
        settings.set("timing_presets", {"ToDelete": {"lead_in_ms": 50}})
        settings.save()

        dlg = CaptionRulesDialog(settings)

        # Select the user preset
        for i in range(dlg._cmb_preset.count()):
            if "ToDelete" in dlg._cmb_preset.itemText(i):
                dlg._cmb_preset.setCurrentIndex(i)
                break

        with patch("app.ui.caption_rules_dialog.QMessageBox.question",
                    return_value=QMessageBox.Yes):
            dlg._delete_preset()

        assert "ToDelete" not in settings.get("timing_presets", {})
    finally:
        os.unlink(settings_file)


def test_rules_dialog_delete_disabled_for_builtins():
    """Verify Delete is disabled for built-in timing presets."""
    app = _ensure_app()
    settings = Settings()
    dlg = CaptionRulesDialog(settings)

    for i in range(dlg._cmb_preset.count()):
        if dlg._cmb_preset.itemText(i).startswith("📦"):
            dlg._cmb_preset.setCurrentIndex(i)
            break

    assert not dlg._btn_delete_preset.isEnabled()


# ── Split feedback tests ─────────────────────────────────────────────────


def test_split_emits_feedback_no_selection():
    """Verify Split emits feedback when no captions are selected."""
    app = _ensure_app()
    panel = CaptionPanel()

    cap = Caption(start_ms=0, end_ms=2000, text="Hello world test")
    panel.set_captions([cap])

    # Don't select any row
    panel._table.clearSelection()

    messages = []
    panel.split_feedback.connect(messages.append)
    panel._split_at_playhead()

    assert len(messages) == 1
    assert "exactly one" in messages[0].lower()


def test_split_emits_feedback_playhead_outside():
    """Verify Split emits feedback when playhead is at caption edge."""
    app = _ensure_app()
    panel = CaptionPanel()

    cap = Caption(start_ms=1000, end_ms=3000, text="Hello world test")
    panel.set_captions([cap])
    panel._table.selectRow(0)
    panel._playhead_ms = 1050  # within 100ms of start

    messages = []
    panel.split_feedback.connect(messages.append)
    panel._split_at_playhead()

    assert len(messages) == 1
    assert "playhead" in messages[0].lower()


def test_split_emits_feedback_single_word():
    """Verify Split emits feedback when caption has fewer than 2 words."""
    app = _ensure_app()
    panel = CaptionPanel()

    cap = Caption(start_ms=1000, end_ms=3000, text="Hello")
    panel.set_captions([cap])
    panel._table.selectRow(0)
    panel._playhead_ms = 2000  # middle of caption

    messages = []
    panel.split_feedback.connect(messages.append)
    panel._split_at_playhead()

    assert len(messages) == 1
    assert "two words" in messages[0].lower()


def test_split_succeeds_no_feedback():
    """Verify Split succeeds without emitting feedback when conditions are met."""
    app = _ensure_app()
    panel = CaptionPanel()

    cap = Caption(start_ms=1000, end_ms=3000, text="Hello world test")
    panel.set_captions([cap])
    panel._table.selectRow(0)
    panel._playhead_ms = 2000  # middle of caption

    messages = []
    panel.split_feedback.connect(messages.append)
    panel._split_at_playhead()

    # No feedback — split succeeded
    assert len(messages) == 0
    # Captions should now have 2 entries
    assert len(panel.get_captions()) == 2


def test_split_button_has_tooltip():
    """Verify the Split button has a helpful tooltip."""
    app = _ensure_app()
    panel = CaptionPanel()

    from PySide6.QtWidgets import QPushButton
    split_btn = None
    for child in panel.findChildren(QPushButton):
        if child.text() == "Split":
            split_btn = child
            break

    assert split_btn is not None
    assert "playhead" in split_btn.toolTip().lower()
    assert "one caption" in split_btn.toolTip().lower()


# ── Merge feedback tests ─────────────────────────────────────────────────


def test_merge_emits_feedback_insufficient_selection():
    """Verify Merge emits feedback when fewer than 2 captions selected."""
    app = _ensure_app()
    panel = CaptionPanel()

    caps = [
        Caption(start_ms=0, end_ms=1000, text="First"),
        Caption(start_ms=1000, end_ms=2000, text="Second"),
    ]
    panel.set_captions(caps)
    panel._table.selectRow(0)  # only one selected

    messages = []
    panel.merge_feedback.connect(messages.append)
    panel._merge_selected()

    assert len(messages) == 1
    assert "at least two" in messages[0].lower()


def test_merge_emits_feedback_noncontiguous():
    """Verify Merge emits feedback when selected rows are not contiguous."""
    app = _ensure_app()
    panel = CaptionPanel()

    caps = [
        Caption(start_ms=0, end_ms=1000, text="First"),
        Caption(start_ms=1000, end_ms=2000, text="Second"),
        Caption(start_ms=2000, end_ms=3000, text="Third"),
    ]
    panel.set_captions(caps)
    # Select rows 0 and 2 (non-contiguous) using QItemSelectionModel
    from PySide6.QtCore import QItemSelectionModel
    panel._table.selectRow(0)
    panel._table.selectionModel().select(
        panel._table.model().index(2, 0),
        QItemSelectionModel.Select | QItemSelectionModel.Rows,
    )

    messages = []
    panel.merge_feedback.connect(messages.append)
    panel._merge_selected()

    assert len(messages) == 1
    assert "contiguous" in messages[0].lower()


def test_merge_succeeds_no_feedback():
    """Verify Merge succeeds without emitting feedback when conditions are met."""
    app = _ensure_app()
    panel = CaptionPanel()

    caps = [
        Caption(start_ms=0, end_ms=1000, text="First"),
        Caption(start_ms=1000, end_ms=2000, text="Second"),
    ]
    panel.set_captions(caps)
    panel._table.selectRow(0)
    # Select additional row for contiguous merge
    from PySide6.QtCore import QItemSelectionModel
    panel._table.selectionModel().select(
        panel._table.model().index(1, 0),
        QItemSelectionModel.Select | QItemSelectionModel.Rows,
    )

    messages = []
    panel.merge_feedback.connect(messages.append)
    panel._merge_selected()

    assert len(messages) == 0
    result = panel.get_captions()
    assert len(result) == 1
    assert result[0].text == "First Second"


def test_merge_button_has_tooltip():
    """Verify the Merge button has a helpful tooltip."""
    app = _ensure_app()
    panel = CaptionPanel()

    from PySide6.QtWidgets import QPushButton
    merge_btn = None
    for child in panel.findChildren(QPushButton):
        if child.text() == "Merge":
            merge_btn = child
            break

    assert merge_btn is not None
    assert "contiguous" in merge_btn.toolTip().lower() or "two" in merge_btn.toolTip().lower()


# ── Regen prompt tests ───────────────────────────────────────────────────


def _make_window():
    """Create a MainWindow for testing. Returns (window, settings, project_svc, db_path)."""
    from app.ui.main_window import MainWindow
    from app.services.project_service import ProjectService

    test_dir = _ensure_test_dir()
    db_path = test_dir / "test_gui_regen.db"
    db_path.unlink(missing_ok=True)

    settings = Settings()
    project_svc = ProjectService(db_path)
    window = MainWindow(settings, project_svc)
    return window, settings, project_svc, db_path


def _teardown(project_svc, db_path):
    project_svc.close()
    db_path.unlink(missing_ok=True)


def test_open_rules_no_change_no_prompt():
    """Verify no prompt when timing rules are accepted without changes."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        window._captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
        window._words = [{"start": 0.0, "end": 1.0, "word": "Test"}]

        # Mock dialog that accepts but changes nothing in settings
        with patch("app.ui.main_window.CaptionRulesDialog") as MockDlg, \
             patch("app.ui.main_window.QMessageBox.question") as mock_q:
            MockDlg.return_value.exec.return_value = CaptionRulesDialog.Accepted
            MockDlg.Accepted = CaptionRulesDialog.Accepted
            window._open_rules()

            # No prompt should fire because nothing changed
            mock_q.assert_not_called()
    finally:
        _teardown(svc, db)


def test_open_rules_change_but_no_transcript_data_shows_hint():
    """Verify status hint when timing changed but no transcript data available."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        window._captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
        window._words = []
        window._segments = []

        # Mock dialog that accepts AND changes a setting
        def side_effect_exec():
            settings.set("lead_in_ms", 999)
            return CaptionRulesDialog.Accepted

        with patch("app.ui.main_window.CaptionRulesDialog") as MockDlg, \
             patch("app.ui.main_window.QMessageBox.question") as mock_q:
            MockDlg.return_value.exec.side_effect = side_effect_exec
            MockDlg.Accepted = CaptionRulesDialog.Accepted
            window._open_rules()

            # No question prompt — can't regen without transcript data
            mock_q.assert_not_called()

        # Status should explain the situation
        status = window._status_label.text()
        assert "not available" in status.lower() or "Re-transcribe" in status
    finally:
        _teardown(svc, db)


def test_open_rules_change_with_words_shows_prompt():
    """Verify regen prompt when timing changed and words are available."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        window._captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
        window._words = [{"start": 0.0, "end": 1.0, "word": "Test"}]
        window._segments = []

        def side_effect_exec():
            settings.set("lead_in_ms", 999)
            return CaptionRulesDialog.Accepted

        with patch("app.ui.main_window.CaptionRulesDialog") as MockDlg, \
             patch("app.ui.main_window.QMessageBox.question",
                    return_value=QMessageBox.No) as mock_q:
            MockDlg.return_value.exec.side_effect = side_effect_exec
            MockDlg.Accepted = CaptionRulesDialog.Accepted
            window._open_rules()

            # Prompt should fire
            mock_q.assert_called_once()
            msg = mock_q.call_args[0][2]
            assert "changed" in msg.lower() or "Regenerate" in msg

        # Status shows deferred hint
        assert "Regen" in window._status_label.text()
    finally:
        _teardown(svc, db)


def test_open_rules_change_with_segments_but_no_words_shows_prompt():
    """Verify regen prompt when timing changed, words are absent, but segments exist."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        window._captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
        window._words = []
        window._segments = [{"start": 0.0, "end": 1.0, "text": "Test"}]

        def side_effect_exec():
            settings.set("lead_in_ms", 999)
            return CaptionRulesDialog.Accepted

        with patch("app.ui.main_window.CaptionRulesDialog") as MockDlg, \
             patch("app.ui.main_window.QMessageBox.question",
                    return_value=QMessageBox.No) as mock_q:
            MockDlg.return_value.exec.side_effect = side_effect_exec
            MockDlg.Accepted = CaptionRulesDialog.Accepted
            window._open_rules()

            # Prompt should fire because segments exist
            mock_q.assert_called_once()
            msg = mock_q.call_args[0][2]
            assert "changed" in msg.lower() or "Regenerate" in msg

        # Status shows deferred hint
        assert "Regen" in window._status_label.text()
    finally:
        _teardown(svc, db)


def test_open_rules_yes_calls_direct_reflow():
    """Verify Yes path calls _reflow_captions_direct (no double confirm)."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        window._captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
        window._words = [{"start": 0.0, "end": 1.0, "word": "Test"}]

        def side_effect_exec():
            settings.set("lead_in_ms", 999)
            return CaptionRulesDialog.Accepted

        with patch("app.ui.main_window.CaptionRulesDialog") as MockDlg, \
             patch("app.ui.main_window.QMessageBox.question",
                    return_value=QMessageBox.Yes), \
             patch.object(window, "_reflow_captions_direct") as mock_direct, \
             patch.object(window, "_reflow_captions") as mock_reflow:
            MockDlg.return_value.exec.side_effect = side_effect_exec
            MockDlg.Accepted = CaptionRulesDialog.Accepted
            window._open_rules()

            # Should call _direct (no overwrite confirm), NOT _reflow_captions
            mock_direct.assert_called_once()
            mock_reflow.assert_not_called()
    finally:
        _teardown(svc, db)


def test_standalone_reflow_still_has_overwrite_warning():
    """Verify standalone _reflow_captions still shows overwrite warning."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        window._captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
        window._words = [{"start": 0.0, "end": 1.0, "word": "Test"}]

        with patch("app.ui.main_window.QMessageBox.warning",
                    return_value=QMessageBox.Cancel) as mock_warn:
            window._reflow_captions()

            # The standalone path still shows the overwrite warning
            mock_warn.assert_called_once()
    finally:
        _teardown(svc, db)

# ── Selected reflow tests ────────────────────────────────────────────────


def test_reflow_selected_no_transcript_data():
    """Verify selected reflow shows message when no transcript data is available."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        window._captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
        window._words = []
        window._segments = []
        window._caption_panel.set_captions(window._captions)
        window._caption_panel._table.selectRow(0)

        window._reflow_selected()
        assert "no transcript data" in window._status_label.text().lower()
    finally:
        _teardown(svc, db)


def test_reflow_selected_no_selection():
    """Verify selected reflow shows message when nothing selected."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        from app.models.caption import TranscriptWord
        window._captions = [Caption(start_ms=0, end_ms=1000, text="Test")]
        window._words = [TranscriptWord(start_ms=0, end_ms=500, text="Test")]
        window._caption_panel.set_captions(window._captions)
        window._caption_panel._table.clearSelection()

        window._reflow_selected()
        assert "select" in window._status_label.text().lower()
    finally:
        _teardown(svc, db)


def test_reflow_selected_success_splices():
    """Verify selected reflow regenerates selected captions and keeps others."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        from app.models.caption import TranscriptWord
        # 3 captions; we'll regen only the middle one
        window._captions = [
            Caption(start_ms=0, end_ms=1000, text="First stays"),
            Caption(start_ms=1000, end_ms=2000, text="Middle regen"),
            Caption(start_ms=2000, end_ms=3000, text="Last stays"),
        ]
        window._words = [
            TranscriptWord(start_ms=0, end_ms=500, text="First"),
            TranscriptWord(start_ms=500, end_ms=1000, text="stays"),
            TranscriptWord(start_ms=1000, end_ms=1500, text="Middle"),
            TranscriptWord(start_ms=1500, end_ms=2000, text="regen"),
            TranscriptWord(start_ms=2000, end_ms=2500, text="Last"),
            TranscriptWord(start_ms=2500, end_ms=3000, text="stays"),
        ]
        window._caption_panel.set_captions(window._captions)
        window._caption_panel._table.selectRow(1)  # select middle

        window._reflow_selected()

        result = window._captions
        # First and last should be untouched
        assert result[0].text == "First stays"
        assert result[-1].text == "Last stays"
        # Status should show reflow summary
        assert "Reflowed" in window._status_label.text()
    finally:
        _teardown(svc, db)


def test_reflow_selected_no_transcript_data_in_range():
    """Verify selected reflow shows message when no transcript data matches the time range."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        from app.models.caption import TranscriptWord
        window._captions = [Caption(start_ms=5000, end_ms=6000, text="Far away")]
        # Words and segments are all at 0-1000ms, caption is at 5000-6000ms
        window._words = [
            TranscriptWord(start_ms=0, end_ms=500, text="Early"),
            TranscriptWord(start_ms=500, end_ms=1000, text="words"),
        ]
        window._segments = [
            {"start": 0.0, "end": 1.0, "text": "Early words"}
        ]
        window._caption_panel.set_captions(window._captions)
        window._caption_panel._table.selectRow(0)

        window._reflow_selected()
        assert "no transcript data found" in window._status_label.text().lower()
    finally:
        _teardown(svc, db)


def test_shared_reflow_core_exists():
    """Verify _run_reflow_core exists and is used by both reflow paths."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        assert hasattr(window, '_run_reflow_core')
        assert callable(window._run_reflow_core)
    finally:
        _teardown(svc, db)


def test_reflow_selected_uses_segments_when_words_missing():
    """Verify selected reflow succeeds using segments if words are absent."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        from unittest.mock import patch
        window._captions = [Caption(start_ms=1000, end_ms=2000, text="Old text")]
        window._words = []
        window._segments = [
            {"start": 1.0, "end": 2.0, "text": "Segment fallback works"}
        ]
        window._caption_panel.set_captions(window._captions)
        window._caption_panel._table.selectRow(0)

        with patch.object(window, "_run_reflow_core", return_value=[Caption(start_ms=1000, end_ms=2000, text="Segment fallback works")]) as mock_core:
            window._reflow_selected()
            
            mock_core.assert_called_once()
            _, kwargs = mock_core.call_args
            passed_segments = kwargs.get("segments")
            assert len(passed_segments) == 1
            assert passed_segments[0]["text"] == "Segment fallback works"

            assert "Reflowed" in window._status_label.text()
    finally:
        _teardown(svc, db)


def test_reflow_captions_uses_segments_when_words_missing():
    """Verify full-project reflow succeeds using segments if words are absent."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        from unittest.mock import patch
        window._captions = [Caption(start_ms=1000, end_ms=2000, text="Old text")]
        window._words = []
        window._segments = [
            {"start": 1.0, "end": 2.0, "text": "Segment fallback full proj"}
        ]

        with patch.object(window, "_run_reflow_core", return_value=[Caption(start_ms=1000, end_ms=2000, text="Segment fallback full proj")]) as mock_core:
            with patch("app.ui.main_window.QMessageBox.warning", return_value=QMessageBox.Yes):
                window._reflow_captions()
            
            mock_core.assert_called_once()
            assert "Reflowed" in window._status_label.text()
    finally:
        _teardown(svc, db)


def test_regen_button_has_updated_tooltip():
    """Verify the main Regen button tooltip reflects segment-aware behavior."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        tooltip = window._btn_reflow.toolTip().lower()
        assert "transcript data" in tooltip
        assert "transcript words" not in tooltip
    finally:
        _teardown(svc, db)


def test_regen_sel_button_has_tooltip():
    """Verify the Regen Sel button has a discoverable tooltip."""
    app = _ensure_app()
    panel = CaptionPanel()

    from PySide6.QtWidgets import QPushButton
    btn = None
    for child in panel.findChildren(QPushButton):
        if child.text() == "Regen Sel":
            btn = child
            break

    assert btn is not None
    tooltip = btn.toolTip().lower()
    assert "contiguous" in tooltip
    assert "transcript data" in tooltip
    assert "transcript words" not in tooltip


def test_regen_sel_button_exists_in_panel():
    """Verify the Regen Sel button and context menu action exist."""
    app = _ensure_app()
    panel = CaptionPanel()

    from PySide6.QtWidgets import QPushButton
    labels = [c.text() for c in panel.findChildren(QPushButton)]
    assert "Regen Sel" in labels
    assert hasattr(panel, 'reflow_selected_requested')


def test_reflow_selected_noncontiguous_rejected():
    """Verify non-contiguous selection is rejected with clear feedback."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        from app.models.caption import TranscriptWord
        from PySide6.QtCore import QItemSelectionModel

        window._captions = [
            Caption(start_ms=0, end_ms=1000, text="First"),
            Caption(start_ms=1000, end_ms=2000, text="Second"),
            Caption(start_ms=2000, end_ms=3000, text="Third"),
        ]
        window._words = [
            TranscriptWord(start_ms=0, end_ms=500, text="First"),
            TranscriptWord(start_ms=1000, end_ms=1500, text="Second"),
            TranscriptWord(start_ms=2000, end_ms=2500, text="Third"),
        ]
        window._caption_panel.set_captions(window._captions)

        # Select rows 0 and 2 (non-contiguous, skipping row 1)
        window._caption_panel._table.selectRow(0)
        window._caption_panel._table.selectionModel().select(
            window._caption_panel._table.model().index(2, 0),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )

        # Confirm selection is indeed non-contiguous
        sel = window._caption_panel.selected_indices()
        assert sel == [0, 2], f"Expected [0, 2] but got {sel}"

        window._reflow_selected()

        # Should reject with contiguous message
        status = window._status_label.text().lower()
        assert "contiguous" in status

        # All captions should remain unchanged
        assert len(window._captions) == 3
        assert window._captions[0].text == "First"
        assert window._captions[1].text == "Second"
        assert window._captions[2].text == "Third"
    finally:
        _teardown(svc, db)


def test_reflow_selected_contiguous_still_works():
    """Verify contiguous multi-selection still reflows correctly."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        from app.models.caption import TranscriptWord
        from PySide6.QtCore import QItemSelectionModel

        window._captions = [
            Caption(start_ms=0, end_ms=1000, text="Prefix"),
            Caption(start_ms=1000, end_ms=2000, text="First target"),
            Caption(start_ms=2000, end_ms=3000, text="Second target"),
            Caption(start_ms=3000, end_ms=4000, text="Suffix"),
        ]
        window._words = [
            TranscriptWord(start_ms=0, end_ms=500, text="Prefix"),
            TranscriptWord(start_ms=1000, end_ms=1500, text="First"),
            TranscriptWord(start_ms=1500, end_ms=2000, text="target"),
            TranscriptWord(start_ms=2000, end_ms=2500, text="Second"),
            TranscriptWord(start_ms=2500, end_ms=3000, text="target"),
            TranscriptWord(start_ms=3000, end_ms=3500, text="Suffix"),
        ]
        window._caption_panel.set_captions(window._captions)

        # Select rows 1 and 2 (contiguous)
        window._caption_panel._table.selectRow(1)
        window._caption_panel._table.selectionModel().select(
            window._caption_panel._table.model().index(2, 0),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )

        window._reflow_selected()

        # Prefix and suffix should be untouched
        assert window._captions[0].text == "Prefix"
        assert window._captions[-1].text == "Suffix"
        # Status should show reflow
        assert "Reflowed" in window._status_label.text()
    finally:
        _teardown(svc, db)


def test_reopen_hydrates_segments():
    """Verify reopening a project restores transcript segments."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        from app.models.project import Project
        proj = svc.create_project(Project(title="HydrateSegs"))
        
        segs = [{"start": 0.0, "end": 1.0, "text": "hydrate me"}]
        svc.save_segments(proj.id, segs)

        window._open_project_by_id(proj.id)

        assert len(window._segments) == 1
        assert window._segments[0]["text"] == "hydrate me"
    finally:
        _teardown(svc, db)


def test_reflow_selected_uses_local_segment_subset():
    """Verify selected reflow only passes segments overlapping the selection to the core."""
    app = _ensure_app()
    window, settings, svc, db = _make_window()

    try:
        from app.models.caption import TranscriptWord
        from unittest.mock import patch

        window._captions = [
            Caption(start_ms=0, end_ms=1000, text="First"),
            Caption(start_ms=1000, end_ms=2000, text="Second"),
            Caption(start_ms=2000, end_ms=3000, text="Third"),
        ]
        window._words = [
            TranscriptWord(start_ms=0, end_ms=500, text="First"),
            TranscriptWord(start_ms=1000, end_ms=1500, text="Second"),
            TranscriptWord(start_ms=2000, end_ms=2500, text="Third"),
        ]
        window._segments = [
            {"start": 0.0, "end": 1.0, "text": "First"},
            {"start": 1.0, "end": 2.0, "text": "Second"},
            {"start": 2.0, "end": 3.0, "text": "Third"},
        ]
        window._caption_panel.set_captions(window._captions)

        # Select the middle row (1000ms - 2000ms)
        window._caption_panel._table.selectRow(1)

        # Patch _run_reflow_core to spy on the 'segments' keyword argument
        with patch.object(window, "_run_reflow_core", return_value=[Caption(start_ms=1000, end_ms=2000, text="Second")]) as mock_core:
            window._reflow_selected()

            mock_core.assert_called_once()
            _, kwargs = mock_core.call_args
            passed_segments = kwargs.get("segments")

            assert passed_segments is not None
            assert len(passed_segments) == 1
            assert passed_segments[0]["text"] == "Second"

    finally:
        _teardown(svc, db)


def _ensure_test_dir():
    from pathlib import Path
    d = Path(__file__).parent / "_test_data"
    d.mkdir(exist_ok=True)
    return d
