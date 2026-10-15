"""Behavior tests for immutable undo-history snapshots."""

from dataclasses import FrozenInstanceError

import pytest

from app.models.caption import Caption
from app.models.history import CaptionHistorySnapshot, SettingsSnapshot
from app.utils.settings import Settings


def test_caption_snapshot_preserves_identity_order_values_and_selection():
    captions = [
        Caption(100, 900, "First", id="caption-a"),
        Caption(1000, 1900, "Second", id="caption-b"),
        Caption(2000, 2900, "Third", id="caption-c"),
    ]

    snapshot = CaptionHistorySnapshot.capture(captions, selected_indices=[2, 0])

    assert [item.id for item in snapshot.captions] == [
        "caption-a",
        "caption-b",
        "caption-c",
    ]
    assert [
        (item.start_ms, item.end_ms, item.text)
        for item in snapshot.captions
    ] == [
        (100, 900, "First"),
        (1000, 1900, "Second"),
        (2000, 2900, "Third"),
    ]
    assert snapshot.selected_caption_ids == ("caption-c", "caption-a")
    assert snapshot.selected_indices() == (2, 0)


def test_caption_snapshot_is_isolated_and_restores_fresh_caption_objects():
    original = Caption(100, 900, "Original", id="caption-a")
    snapshot = CaptionHistorySnapshot.capture([original], selected_indices=[0])

    original.start_ms = 400
    original.text = "Mutated after capture"
    first_restore = snapshot.restore_captions()
    first_restore[0].end_ms = 5000
    first_restore[0].text = "Mutated restoration"
    second_restore = snapshot.restore_captions()

    assert first_restore[0] is not original
    assert second_restore[0] is not first_restore[0]
    assert (
        second_restore[0].id,
        second_restore[0].start_ms,
        second_restore[0].end_ms,
        second_restore[0].text,
    ) == ("caption-a", 100, 900, "Original")

    with pytest.raises(FrozenInstanceError):
        snapshot.captions[0].text = "Cannot mutate history"


def test_caption_snapshot_rejects_invalid_or_ambiguous_selection_identity():
    captions = [
        Caption(0, 1000, "First", id="duplicate"),
        Caption(1000, 2000, "Second", id="duplicate"),
    ]

    with pytest.raises(ValueError, match="unique"):
        CaptionHistorySnapshot.capture(captions, selected_indices=[0])

    with pytest.raises(IndexError, match="selection index"):
        CaptionHistorySnapshot.capture(
            [Caption(0, 1000, "Only", id="only")],
            selected_indices=[1],
        )


def test_settings_snapshot_deeply_isolates_nested_preset_values():
    settings = {
        "lead_in_ms": 150,
        "timing_presets": {
            "Interview": {
                "lead_in_ms": 80,
                "max_lines": 2,
            }
        },
        "recent_models": ["base", "small"],
    }
    snapshot = SettingsSnapshot.capture(settings)

    settings["lead_in_ms"] = 999
    settings["timing_presets"]["Interview"]["lead_in_ms"] = 999
    settings["recent_models"].append("large")
    first_restore = snapshot.restore()
    first_restore["timing_presets"]["Interview"]["max_lines"] = 4
    first_restore["recent_models"].append("medium")

    assert snapshot.restore() == {
        "lead_in_ms": 150,
        "timing_presets": {
            "Interview": {
                "lead_in_ms": 80,
                "max_lines": 2,
            }
        },
        "recent_models": ["base", "small"],
    }


def test_settings_snapshot_equality_does_not_depend_on_mapping_order():
    left = SettingsSnapshot.capture({"max_lines": 2, "lead_in_ms": 150})
    right = SettingsSnapshot.capture({"lead_in_ms": 150, "max_lines": 2})

    assert left == right


def test_settings_snapshot_requires_a_json_object():
    with pytest.raises(TypeError, match="mapping"):
        SettingsSnapshot.capture(["not", "a", "mapping"])

    with pytest.raises(TypeError, match="JSON-compatible"):
        SettingsSnapshot.capture({"invalid": object()})


def test_settings_exposes_an_isolated_complete_state_for_snapshot_capture(tmp_path):
    settings = Settings(tmp_path / "settings.json")
    settings.set(
        "timing_presets",
        {"Interview": {"lead_in_ms": 80}},
    )

    exported = settings.to_dict()
    snapshot = SettingsSnapshot.capture(exported)
    exported["timing_presets"]["Interview"]["lead_in_ms"] = 999

    assert settings.get("timing_presets") == {
        "Interview": {"lead_in_ms": 80},
    }
    assert snapshot.restore()["timing_presets"] == {
        "Interview": {"lead_in_ms": 80},
    }
    assert "export_font_family" in snapshot.restore()
