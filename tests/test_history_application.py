"""Integration tests for applying undo-history state to the application."""

import json

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.models.caption import Caption
from app.models.history import CaptionHistorySnapshot, CaptionSnapshot, SettingsSnapshot
from app.models.project import Project
from app.services.history_service import (
    CaptionRangeState,
    CaptionTextEditCommand,
    CaptionTextState,
    CaptionTiming,
    CaptionTimingState,
    PresetState,
    SettingsChangeCommand,
)
from app.services.project_service import ProjectService
from app.ui.main_window import MainWindow
from app.utils.settings import Settings


@pytest.fixture
def history_window(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings_path = tmp_path / "settings.json"
    settings = Settings(settings_path)
    service = ProjectService(tmp_path / "projects.db")
    project = service.create_project(Project(title="History application"))
    window = MainWindow(settings, service)
    window._project = project
    try:
        yield window, service, settings_path
    finally:
        window.deleteLater()
        app.processEvents()
        service.close()


def _load_captions(window, service, captions):
    window._captions = captions
    window._caption_panel.set_captions(captions)
    window._video_panel.set_captions(captions)
    service.save_captions(window._project.id, captions)


def test_apply_caption_text_synchronizes_views_selection_and_sqlite(history_window):
    window, service, _ = history_window
    captions = [
        Caption(0, 1000, "First", id="caption-a"),
        Caption(1100, 2000, "Before", id="caption-b"),
    ]
    _load_captions(window, service, captions)
    changes = []
    window._caption_panel.captions_changed.connect(lambda: changes.append(True))

    before = CaptionTextState("caption-b", "Before", ("caption-b",))
    after = CaptionTextState("caption-b", "After", ("caption-b",))

    window._history.push(
        CaptionTextEditCommand(window, before, after)
    )

    assert window._caption_panel._table.item(1, 2).text() == "After"
    window._history.undo()
    assert window._caption_panel._table.item(1, 2).text() == "Before"
    assert window._caption_panel._editor.toPlainText() == "Before"
    window._history.redo()
    QTest.qWait(550)

    assert [caption.text for caption in window._captions] == ["First", "After"]
    assert window._caption_panel._table.item(1, 2).text() == "After"
    assert window._video_panel._captions[1].text == "After"
    assert window._caption_panel.selected_indices() == [1]
    assert window._caption_panel._editor.toPlainText() == "After"
    assert [caption.text for caption in service.load_captions(window._project.id)] == [
        "First",
        "After",
    ]
    assert changes == []
    assert window._status_label.text() == "Caption text updated (autosaved)"


def test_apply_caption_timing_restores_exact_state_without_normalizing(history_window):
    window, service, _ = history_window
    captions = [Caption(100, 900, "Short", id="caption-a")]
    _load_captions(window, service, captions)

    window.apply_caption_timing(
        CaptionTimingState(
            captions=(CaptionTiming("caption-a", 250, 300),),
            selected_caption_ids=("caption-a",),
        )
    )
    window._flush_caption_save()

    caption = window._captions[0]
    assert (caption.start_ms, caption.end_ms) == (250, 300)
    assert window._caption_panel._table.item(0, 0).text() == "00:00.2"
    assert window._caption_panel._table.item(0, 1).text() == "00:00.3"
    assert window._caption_panel.selected_indices() == [0]
    saved = service.load_captions(window._project.id)[0]
    assert (saved.start_ms, saved.end_ms) == (250, 300)


def test_apply_caption_timing_validates_every_caption_before_mutating(history_window):
    window, _, _ = history_window
    captions = [
        Caption(100, 900, "First", id="caption-a"),
        Caption(1000, 1900, "Second", id="caption-b"),
    ]
    _load_captions(window, window._project_svc, captions)

    with pytest.raises(ValueError, match="caption not found: missing"):
        window.apply_caption_timing(
            CaptionTimingState(
                captions=(
                    CaptionTiming("caption-a", 250, 800),
                    CaptionTiming("missing", 900, 1500),
                ),
                selected_caption_ids=("caption-a",),
            )
        )

    assert [
        (caption.start_ms, caption.end_ms) for caption in window._captions
    ] == [(100, 900), (1000, 1900)]


def test_apply_caption_range_splices_rows_and_restores_selection(history_window):
    window, service, _ = history_window
    captions = [
        Caption(0, 900, "First", id="caption-a"),
        Caption(1000, 1900, "Replace me", id="caption-b"),
        Caption(2000, 2900, "Last", id="caption-c"),
    ]
    _load_captions(window, service, captions)

    window.apply_caption_range(
        CaptionRangeState(
            start_index=1,
            remove_count=1,
            captions=(
                CaptionSnapshot("caption-b1", 1000, 1400, "Replacement one"),
                CaptionSnapshot("caption-b2", 1500, 1900, "Replacement two"),
            ),
            selected_caption_ids=("caption-b2",),
        )
    )
    window._flush_caption_save()

    assert [caption.id for caption in window._captions] == [
        "caption-a",
        "caption-b1",
        "caption-b2",
        "caption-c",
    ]
    assert window._caption_panel._table.rowCount() == 4
    assert window._caption_panel.selected_indices() == [2]
    assert window._caption_panel._editor.toPlainText() == "Replacement two"
    assert [caption.text for caption in window._video_panel._captions] == [
        "First",
        "Replacement one",
        "Replacement two",
        "Last",
    ]
    assert [caption.text for caption in service.load_captions(window._project.id)] == [
        "First",
        "Replacement one",
        "Replacement two",
        "Last",
    ]


def test_apply_all_captions_replaces_collection_and_restores_selection(history_window):
    window, service, _ = history_window
    _load_captions(
        window,
        service,
        [Caption(0, 1000, "Old", id="caption-old")],
    )
    state = CaptionHistorySnapshot(
        captions=(
            CaptionSnapshot("caption-new-a", 100, 800, "New one"),
            CaptionSnapshot("caption-new-b", 900, 1600, "New two"),
        ),
        selected_caption_ids=("caption-new-a",),
    )

    window.apply_all_captions(state)
    window._flush_caption_save()

    assert [caption.id for caption in window._captions] == [
        "caption-new-a",
        "caption-new-b",
    ]
    assert window._caption_panel.selected_indices() == [0]
    assert window._caption_panel._editor.toPlainText() == "New one"
    assert [caption.text for caption in service.load_captions(window._project.id)] == [
        "New one",
        "New two",
    ]


def test_apply_settings_replaces_persists_and_refreshes_video_style(history_window):
    window, _, settings_path = history_window
    original = window._settings.to_dict()
    updated = window._settings.to_dict()
    updated["export_fill_color"] = "#12AB34"
    updated["min_caption_ms"] = 950

    window._history.push(
        SettingsChangeCommand(
            window,
            SettingsSnapshot.capture(original),
            SettingsSnapshot.capture(updated),
        )
    )

    assert window._settings.to_dict() == updated
    assert json.loads(settings_path.read_text(encoding="utf-8")) == updated
    assert window._video_panel._overlay._fill_color == "#12AB34"
    assert window._status_label.text() == "Settings updated"

    window._history.undo()
    assert window._settings.to_dict() == original
    assert json.loads(settings_path.read_text(encoding="utf-8")) == original
    assert window._video_panel._overlay._fill_color == original["export_fill_color"]

    window._history.redo()
    assert window._settings.to_dict() == updated
    assert json.loads(settings_path.read_text(encoding="utf-8")) == updated
    assert window._video_panel._overlay._fill_color == "#12AB34"


@pytest.mark.parametrize(
    ("preset_kind", "settings_key"),
    [("timing", "timing_presets"), ("style", "style_presets")],
)
def test_apply_preset_creates_and_deletes_persisted_user_preset(
    history_window,
    preset_kind,
    settings_key,
):
    window, _, settings_path = history_window
    values = SettingsSnapshot.capture({"sample": 123})

    window.apply_preset(PresetState(preset_kind, "Portfolio", values))

    assert window._settings.get(settings_key) == {"Portfolio": {"sample": 123}}
    assert json.loads(settings_path.read_text(encoding="utf-8"))[settings_key] == {
        "Portfolio": {"sample": 123}
    }

    window.apply_preset(PresetState(preset_kind, "Portfolio", None))

    assert window._settings.get(settings_key) == {}
    assert json.loads(settings_path.read_text(encoding="utf-8"))[settings_key] == {}


def test_apply_preset_rejects_unknown_preset_kind(history_window):
    window, _, _ = history_window

    with pytest.raises(ValueError, match="unknown preset kind"):
        window.apply_preset(PresetState("unknown", "Portfolio", None))
