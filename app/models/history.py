"""Immutable value snapshots used by undo and redo history."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

from app.models.caption import Caption


@dataclass(frozen=True, slots=True)
class CaptionSnapshot:
    """Immutable value copy of one caption, including its stable identity."""

    id: str
    start_ms: int
    end_ms: int
    text: str

    @classmethod
    def capture(cls, caption: Caption) -> CaptionSnapshot:
        return cls(
            id=caption.id,
            start_ms=caption.start_ms,
            end_ms=caption.end_ms,
            text=caption.text,
        )

    def restore(self) -> Caption:
        """Return a new mutable caption with the captured identity and values."""
        return Caption(
            id=self.id,
            start_ms=self.start_ms,
            end_ms=self.end_ms,
            text=self.text,
        )


@dataclass(frozen=True, slots=True)
class CaptionHistorySnapshot:
    """Immutable ordered caption state plus identity-based row selection."""

    captions: tuple[CaptionSnapshot, ...]
    selected_caption_ids: tuple[str, ...] = ()

    @classmethod
    def capture(
        cls,
        captions: Sequence[Caption],
        selected_indices: Iterable[int] = (),
    ) -> CaptionHistorySnapshot:
        captured = tuple(CaptionSnapshot.capture(caption) for caption in captions)
        caption_ids = tuple(caption.id for caption in captured)
        if len(set(caption_ids)) != len(caption_ids):
            raise ValueError("caption IDs must be unique in a history snapshot")

        indices = tuple(selected_indices)
        if len(set(indices)) != len(indices):
            raise ValueError("selection indices must be unique")

        selected_ids: list[str] = []
        for index in indices:
            if not 0 <= index < len(captured):
                raise IndexError(f"selection index out of range: {index}")
            selected_ids.append(captured[index].id)

        return cls(captions=captured, selected_caption_ids=tuple(selected_ids))

    def restore_captions(self) -> list[Caption]:
        """Return a fresh mutable caption list for applying this snapshot."""
        return [caption.restore() for caption in self.captions]

    def selected_indices(self) -> tuple[int, ...]:
        """Resolve the captured selection against the captured caption order."""
        indices_by_id = {
            caption.id: index for index, caption in enumerate(self.captions)
        }
        return tuple(indices_by_id[caption_id] for caption_id in self.selected_caption_ids)


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    """Immutable deep copy of the application's JSON-backed settings state."""

    _serialized: str

    @classmethod
    def capture(cls, settings: Mapping[str, Any]) -> SettingsSnapshot:
        if not isinstance(settings, Mapping):
            raise TypeError("settings snapshot source must be a mapping")

        try:
            serialized = json.dumps(
                dict(settings),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise TypeError("settings values must be JSON-compatible") from exc

        return cls(_serialized=serialized)

    def restore(self) -> dict[str, Any]:
        """Return a fresh mutable settings mapping for applying this snapshot."""
        restored = json.loads(self._serialized)
        if not isinstance(restored, dict):
            raise ValueError("settings snapshot root must be a JSON object")
        return restored
