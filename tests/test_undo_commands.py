"""Behavior tests for the central undo-command framework."""

import pytest
from PySide6.QtWidgets import QApplication

from app.models.caption import Caption
from app.models.history import (
    CaptionHistorySnapshot,
    CaptionSnapshot,
    SettingsSnapshot,
)

from app.services.history_service import (
    ApplicationHistory,
    CaptionRangeReplaceCommand,
    CaptionRangeState,
    FullCaptionReplaceCommand,
    PresetChangeCommand,
    PresetState,
    SettingsChangeCommand,
    CaptionTextEditCommand,
    CaptionTextState,
    CaptionTiming,
    CaptionTimingChangeCommand,
    CaptionTimingState,
)
from app.services.project_service import ProjectService
from app.ui.main_window import MainWindow
from app.utils.settings import Settings


class _HistoryTarget:
    """Small in-memory consumer exercising the command/target contract."""

    def __init__(self):
        self.caption_text = None
        self.caption_timing = None
        self.caption_range = None
        self.all_captions = None
        self.settings = None
        self.preset = None

    def apply_caption_text(self, state):
        self.caption_text = state

    def apply_caption_timing(self, state):
        self.caption_timing = state

    def apply_caption_range(self, state):
        self.caption_range = state

    def apply_all_captions(self, state):
        self.all_captions = state

    def apply_settings(self, state):
        self.settings = state

    def apply_preset(self, state):
        self.preset = state


def test_caption_text_command_runs_redo_undo_and_redo_on_the_application_stack():
    target = _HistoryTarget()
    history = ApplicationHistory()
    before = CaptionTextState("caption-a", "Before", ("caption-a",))
    after = CaptionTextState("caption-a", "After", ("caption-a",))

    history.push(CaptionTextEditCommand(target, before, after))

    assert target.caption_text == after
    assert history.canUndo()
    assert history.undoText() == "Edit Caption Text"

    history.undo()
    assert target.caption_text == before
    assert history.canRedo()
    assert history.redoText() == "Edit Caption Text"

    history.redo()
    assert target.caption_text == after


def test_caption_timing_command_restores_all_affected_caption_boundaries():
    target = _HistoryTarget()
    history = ApplicationHistory()
    before = CaptionTimingState(
        captions=(
            CaptionTiming("caption-a", 100, 900),
            CaptionTiming("caption-b", 1000, 1900),
        ),
        selected_caption_ids=("caption-a", "caption-b"),
    )
    after = CaptionTimingState(
        captions=(
            CaptionTiming("caption-a", 50, 900),
            CaptionTiming("caption-b", 950, 1900),
        ),
        selected_caption_ids=("caption-a", "caption-b"),
    )

    history.push(CaptionTimingChangeCommand(target, before, after))
    assert target.caption_timing == after
    assert history.undoText() == "Adjust Caption Timing"

    history.undo()
    assert target.caption_timing == before

    history.redo()
    assert target.caption_timing == after


def test_caption_range_command_reverses_the_correct_number_of_rows():
    target = _HistoryTarget()
    history = ApplicationHistory()
    before_captions = (
        CaptionSnapshot("caption-a", 0, 900, "First"),
        CaptionSnapshot("caption-b", 1000, 1900, "Second"),
    )
    after_captions = (
        CaptionSnapshot("caption-merged", 0, 1900, "First Second"),
    )

    history.push(
        CaptionRangeReplaceCommand(
            target,
            start_index=3,
            before_captions=before_captions,
            after_captions=after_captions,
            before_selection_ids=("caption-a", "caption-b"),
            after_selection_ids=("caption-merged",),
            text="Merge Captions",
        )
    )

    assert target.caption_range == CaptionRangeState(
        start_index=3,
        remove_count=2,
        captions=after_captions,
        selected_caption_ids=("caption-merged",),
    )
    assert history.undoText() == "Merge Captions"

    history.undo()
    assert target.caption_range == CaptionRangeState(
        start_index=3,
        remove_count=1,
        captions=before_captions,
        selected_caption_ids=("caption-a", "caption-b"),
    )

    history.redo()
    assert target.caption_range.captions == after_captions


def test_full_caption_command_restores_the_complete_caption_and_selection_state():
    target = _HistoryTarget()
    history = ApplicationHistory()
    before = CaptionHistorySnapshot.capture(
        [Caption(0, 900, "Manual", id="caption-manual")],
        selected_indices=[0],
    )
    after = CaptionHistorySnapshot.capture(
        [
            Caption(0, 700, "Regenerated one", id="caption-new-a"),
            Caption(800, 1500, "Regenerated two", id="caption-new-b"),
        ],
        selected_indices=[1],
    )

    history.push(
        FullCaptionReplaceCommand(
            target,
            before,
            after,
            text="Regenerate All Captions",
        )
    )
    assert target.all_captions == after
    assert history.undoText() == "Regenerate All Captions"

    history.undo()
    assert target.all_captions == before

    history.redo()
    assert target.all_captions == after


def test_settings_command_restores_the_entire_settings_snapshot():
    target = _HistoryTarget()
    history = ApplicationHistory()
    before = SettingsSnapshot.capture(
        {"lead_in_ms": 150, "export_fill_color": "#FFFFFF"}
    )
    after = SettingsSnapshot.capture(
        {"lead_in_ms": 80, "export_fill_color": "#FFFF00"}
    )

    history.push(SettingsChangeCommand(target, before, after, text="Change Rules"))
    assert target.settings == after
    assert history.undoText() == "Change Rules"

    history.undo()
    assert target.settings == before

    history.redo()
    assert target.settings == after


def test_preset_command_can_restore_a_deleted_preset():
    target = _HistoryTarget()
    history = ApplicationHistory()
    preset_values = SettingsSnapshot.capture(
        {"lead_in_ms": 80, "max_lines": 2}
    )
    before = PresetState("timing", "Interview", preset_values)
    after = PresetState("timing", "Interview", None)

    history.push(
        PresetChangeCommand(target, before, after, text="Delete Timing Preset")
    )
    assert target.preset == after
    assert history.undoText() == "Delete Timing Preset"

    history.undo()
    assert target.preset == before

    history.redo()
    assert target.preset == after


def test_preset_command_can_reverse_creation_or_overwrite():
    target = _HistoryTarget()
    history = ApplicationHistory()
    absent = PresetState("style", "Portfolio", None)
    created = PresetState(
        "style",
        "Portfolio",
        SettingsSnapshot.capture({"export_fill_color": "#FFFF00"}),
    )
    overwritten = PresetState(
        "style",
        "Portfolio",
        SettingsSnapshot.capture({"export_fill_color": "#00FFFF"}),
    )

    history.push(
        PresetChangeCommand(target, absent, created, text="Create Style Preset")
    )
    history.push(
        PresetChangeCommand(
            target,
            created,
            overwritten,
            text="Overwrite Style Preset",
        )
    )
    assert target.preset == overwritten

    history.undo()
    assert target.preset == created

    history.undo()
    assert target.preset == absent


def test_no_op_command_is_not_applied_or_added_to_history():
    target = _HistoryTarget()
    history = ApplicationHistory()
    unchanged = CaptionTextState("caption-a", "Same", ("caption-a",))

    history.push(CaptionTextEditCommand(target, unchanged, unchanged))

    assert target.caption_text is None
    assert history.count() == 0
    assert not history.canUndo()


def test_commands_reject_mismatched_caption_identity():
    target = _HistoryTarget()

    with pytest.raises(ValueError, match="same caption"):
        CaptionTextEditCommand(
            target,
            CaptionTextState("caption-a", "Before"),
            CaptionTextState("caption-b", "After"),
        )

    with pytest.raises(ValueError, match="same captions"):
        CaptionTimingChangeCommand(
            target,
            CaptionTimingState((CaptionTiming("caption-a", 0, 900),)),
            CaptionTimingState((CaptionTiming("caption-b", 0, 900),)),
        )


def test_preset_command_rejects_mismatched_preset_identity():
    target = _HistoryTarget()

    with pytest.raises(ValueError, match="same preset"):
        PresetChangeCommand(
            target,
            PresetState("timing", "Interview", None),
            PresetState("style", "Portfolio", None),
        )


def test_main_window_owns_one_empty_application_history_stack(tmp_path):
    app = QApplication.instance() or QApplication([])
    service = ProjectService(tmp_path / "projects.db")
    window = MainWindow(Settings(tmp_path / "settings.json"), service)
    try:
        assert isinstance(window._history, ApplicationHistory)
        assert window._history.parent() is window
        assert window._history.count() == 0
    finally:
        window.deleteLater()
        app.processEvents()
        service.close()
