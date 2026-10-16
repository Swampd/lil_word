"""Central undo stack and reversible application commands."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from PySide6.QtCore import QObject
from PySide6.QtGui import QUndoCommand, QUndoStack

from app.models.history import (
    CaptionHistorySnapshot,
    CaptionSnapshot,
    SettingsSnapshot,
)


@dataclass(frozen=True, slots=True)
class CaptionTextState:
    """Text and selection state for one caption edit."""

    caption_id: str
    text: str
    selected_caption_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaptionTiming:
    """Timing boundaries for one caption."""

    caption_id: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class CaptionTimingState:
    """Timing and selection state for one or more affected captions."""

    captions: tuple[CaptionTiming, ...]
    selected_caption_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaptionRangeState:
    """One caption-list splice to apply at a stable list position."""

    start_index: int
    remove_count: int
    captions: tuple[CaptionSnapshot, ...]
    selected_caption_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PresetState:
    """One named timing or style preset, or its absence when deleted."""

    preset_kind: str
    name: str
    values: SettingsSnapshot | None


class HistoryTarget(Protocol):
    """Application-side state operations invoked by history commands."""

    def apply_caption_text(self, state: CaptionTextState) -> None: ...

    def apply_caption_timing(self, state: CaptionTimingState) -> None: ...

    def apply_caption_range(self, state: CaptionRangeState) -> None: ...

    def apply_all_captions(self, state: CaptionHistorySnapshot) -> None: ...

    def apply_settings(self, state: SettingsSnapshot) -> None: ...

    def apply_preset(self, state: PresetState) -> None: ...


_StateT = TypeVar("_StateT")


class _StateCommand(QUndoCommand, Generic[_StateT]):
    """Apply one immutable state on redo and its predecessor on undo."""

    def __init__(
        self,
        apply_state: Callable[[_StateT], None],
        before: _StateT,
        after: _StateT,
        text: str,
    ):
        super().__init__(text)
        self._apply_state = apply_state
        self._before = before
        self._after = after

    @property
    def is_noop(self) -> bool:
        return self._before == self._after

    def undo(self) -> None:
        self._apply_state(self._before)

    def redo(self) -> None:
        self._apply_state(self._after)


class CaptionTextEditCommand(_StateCommand[CaptionTextState]):
    """Reversibly replace one caption's text."""

    def __init__(
        self,
        target: HistoryTarget,
        before: CaptionTextState,
        after: CaptionTextState,
        text: str = "Edit Caption Text",
    ):
        if before.caption_id != after.caption_id:
            raise ValueError("text command states must identify the same caption")
        super().__init__(target.apply_caption_text, before, after, text)


class CaptionTimingChangeCommand(_StateCommand[CaptionTimingState]):
    """Reversibly replace timing boundaries for affected captions."""

    def __init__(
        self,
        target: HistoryTarget,
        before: CaptionTimingState,
        after: CaptionTimingState,
        text: str = "Adjust Caption Timing",
    ):
        before_ids = tuple(caption.caption_id for caption in before.captions)
        after_ids = tuple(caption.caption_id for caption in after.captions)
        if before_ids != after_ids:
            raise ValueError("timing command states must identify the same captions")
        super().__init__(target.apply_caption_timing, before, after, text)


class CaptionRangeReplaceCommand(_StateCommand[CaptionRangeState]):
    """Reversibly replace a contiguous range of captions."""

    def __init__(
        self,
        target: HistoryTarget,
        start_index: int,
        before_captions: tuple[CaptionSnapshot, ...],
        after_captions: tuple[CaptionSnapshot, ...],
        before_selection_ids: tuple[str, ...] = (),
        after_selection_ids: tuple[str, ...] = (),
        text: str = "Replace Caption Range",
    ):
        undo_state = CaptionRangeState(
            start_index=start_index,
            remove_count=len(after_captions),
            captions=before_captions,
            selected_caption_ids=before_selection_ids,
        )
        redo_state = CaptionRangeState(
            start_index=start_index,
            remove_count=len(before_captions),
            captions=after_captions,
            selected_caption_ids=after_selection_ids,
        )
        super().__init__(target.apply_caption_range, undo_state, redo_state, text)


class FullCaptionReplaceCommand(_StateCommand[CaptionHistorySnapshot]):
    """Reversibly replace the complete caption collection."""

    def __init__(
        self,
        target: HistoryTarget,
        before: CaptionHistorySnapshot,
        after: CaptionHistorySnapshot,
        text: str = "Replace All Captions",
    ):
        super().__init__(target.apply_all_captions, before, after, text)


class SettingsChangeCommand(_StateCommand[SettingsSnapshot]):
    """Reversibly replace the complete application settings state."""

    def __init__(
        self,
        target: HistoryTarget,
        before: SettingsSnapshot,
        after: SettingsSnapshot,
        text: str = "Change Settings",
    ):
        super().__init__(target.apply_settings, before, after, text)


class PresetChangeCommand(_StateCommand[PresetState]):
    """Reversibly create, overwrite, or delete a named preset."""

    def __init__(
        self,
        target: HistoryTarget,
        before: PresetState,
        after: PresetState,
        text: str = "Change Preset",
    ):
        if (before.preset_kind, before.name) != (after.preset_kind, after.name):
            raise ValueError("preset command states must identify the same preset")
        super().__init__(target.apply_preset, before, after, text)


class ApplicationHistory(QUndoStack):
    """The single session-level undo/redo stack for application commands."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

    def push(self, command: QUndoCommand) -> None:
        """Record a real state change and ignore commands with no effect."""
        if isinstance(command, _StateCommand) and command.is_noop:
            return
        super().push(command)
