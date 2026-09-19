"""Caption panel – editable caption list with split/merge/nudge actions."""

from __future__ import annotations

from bisect import bisect_right
import re
from typing import Iterable, Optional

from PySide6.QtCore import Qt, Signal, Slot, QModelIndex
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QAbstractItemView, QHeaderView, QMenu, QMessageBox,
    QPlainTextEdit
)

from app.models.caption import Caption
from app.utils.timecode import ms_to_display

_NUDGE_MS = 50  # ms per nudge step


class CaptionPanel(QWidget):
    """Editable table of caption blocks with timing controls."""

    caption_clicked = Signal(int)      # emits start_ms when a row is clicked
    captions_changed = Signal()        # emits when captions are edited
    split_feedback = Signal(str)       # emits reason when split cannot act
    merge_feedback = Signal(str)       # emits reason when merge cannot act
    reflow_selected_requested = Signal()  # emits when user wants selected-only reflow

    def __init__(self, parent=None):
        super().__init__(parent)
        self._captions: list[Caption] = []
        self._active_caption_row: Optional[int] = None
        self._updating = False  # guard against re-entrant edits

        # --- Table ---
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Start", "End", "Text"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setWordWrap(True)
        self._table.setTextElideMode(Qt.ElideNone)
        self._table.verticalHeader().setDefaultSectionSize(28)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.cellChanged.connect(self._on_cell_changed)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        # --- Editor ---
        self._editor = QPlainTextEdit()
        self._editor.setFixedHeight(60)
        self._editor.setPlaceholderText("Select a single caption to edit full text…")
        self._editor.setEnabled(False)
        self._editor.textChanged.connect(self._on_editor_changed)

        # --- Action buttons ---
        btn_layout = QHBoxLayout()
        _tooltips = {
            "Split": "Split the selected caption at the playhead position. "
                     "Requires: one caption selected, playhead inside it, at least two words.",
            "Merge": "Merge two or more contiguous selected captions into one.",
            "Regen Sel": "Regenerate only the selected contiguous captions using current timing rules. "
                         "Requires a contiguous selection and transcript data available.",
        }
        for label, slot in [
            ("◀ Start", self._nudge_start_earlier),
            ("Start ▶", self._nudge_start_later),
            ("◀ End", self._nudge_end_earlier),
            ("End ▶", self._nudge_end_later),
            ("Split", self._split_at_playhead),
            ("Merge", self._merge_selected),
            ("Regen Sel", self._request_reflow_selected),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.clicked.connect(slot)
            if label in _tooltips:
                btn.setToolTip(_tooltips[label])
            btn_layout.addWidget(btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._editor)
        layout.addLayout(btn_layout)

        self._playhead_ms: int = 0

    # ── Public API ───────────────────────────────────────────────────────

    def get_drop_targets(self) -> list[QWidget]:
        return [self, self._table, self._table.viewport()]

    def set_captions(self, captions: list[Caption]):
        self._captions = captions
        self._active_caption_row = None
        self._refresh_table()

    def get_captions(self) -> list[Caption]:
        return list(self._captions)

    def refresh_caption_rows(
        self,
        captions: list[Caption],
        rows: Iterable[int],
    ) -> None:
        """Refresh only changed caption rows without rebuilding the table."""
        if len(captions) != self._table.rowCount():
            self.set_captions(captions)
            return

        self._captions = captions
        text_rows: list[int] = []
        self._updating = True
        try:
            for row in sorted(set(rows)):
                if not 0 <= row < len(captions):
                    continue

                caption = captions[row]
                start_item = self._table.item(row, 0)
                end_item = self._table.item(row, 1)
                text_item = self._table.item(row, 2)

                if start_item is None:
                    self._table.setItem(row, 0, self._time_item(caption.start_ms))
                else:
                    start_item.setText(ms_to_display(caption.start_ms))

                if end_item is None:
                    self._table.setItem(row, 1, self._time_item(caption.end_ms))
                else:
                    end_item.setText(ms_to_display(caption.end_ms))

                text_changed = text_item is None or text_item.text() != caption.text
                if text_item is None:
                    text_item = QTableWidgetItem(caption.text)
                    text_item.setFlags(text_item.flags() | Qt.ItemIsEditable)
                    text_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    self._table.setItem(row, 2, text_item)
                else:
                    text_item.setText(caption.text)
                text_item.setToolTip(caption.text)

                if text_changed:
                    text_rows.append(row)
        finally:
            self._updating = False

        for row in text_rows:
            self._table.resizeRowToContents(row)

    def set_playhead(self, ms: int):
        """Update playhead position (used for split action)."""
        self._playhead_ms = ms
        row = bisect_right(
            self._captions,
            ms,
            key=lambda caption: caption.start_ms,
        ) - 1
        if row < 0 or ms > self._captions[row].end_ms:
            row = None

        if row == self._active_caption_row:
            return

        self._active_caption_row = row
        if row is not None:
            self._table.selectRow(row)

    def highlight_row(self, index: int):
        if 0 <= index < self._table.rowCount():
            self._table.selectRow(index)

    def selected_indices(self) -> list[int]:
        rows = set()
        for idx in self._table.selectedIndexes():
            rows.add(idx.row())
        return sorted(rows)

    # ── Table refresh ────────────────────────────────────────────────────

    def _refresh_table(self):
        self._updating = True
        self._table.setRowCount(len(self._captions))
        for i, cap in enumerate(self._captions):
            self._table.setItem(i, 0, self._time_item(cap.start_ms))
            self._table.setItem(i, 1, self._time_item(cap.end_ms))
            text_item = QTableWidgetItem(cap.text)
            text_item.setFlags(text_item.flags() | Qt.ItemIsEditable)
            text_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            text_item.setToolTip(cap.text)
            self._table.setItem(i, 2, text_item)
        self._table.resizeRowsToContents()
        self._updating = False
        self._on_selection_changed()

    @staticmethod
    def _time_item(ms: int) -> QTableWidgetItem:
        item = QTableWidgetItem(ms_to_display(ms))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setTextAlignment(Qt.AlignCenter)
        return item

    # ── Slots ────────────────────────────────────────────────────────────

    @Slot(int, int)
    def _on_cell_clicked(self, row, col):
        if 0 <= row < len(self._captions):
            self.caption_clicked.emit(self._captions[row].start_ms)

    @Slot(int, int)
    def _on_cell_changed(self, row, col):
        if self._updating or col != 2:
            return
        if 0 <= row < len(self._captions):
            item = self._table.item(row, 2)
            if item:
                new_text = item.text()
                self._captions[row].text = new_text

                # sync editor if editing the active row
                idxs = self.selected_indices()
                if len(idxs) == 1 and idxs[0] == row:
                    self._updating = True
                    self._editor.setPlainText(new_text)
                    self._updating = False

                self._table.resizeRowToContents(row)
                self.captions_changed.emit()

    @Slot()
    def _on_selection_changed(self):
        if self._updating:
            return
        idxs = self.selected_indices()
        if len(idxs) == 1:
            self._updating = True
            self._editor.setEnabled(True)
            self._editor.setPlainText(self._captions[idxs[0]].text)
            self._updating = False
        else:
            self._updating = True
            self._editor.setPlainText("")
            self._editor.setEnabled(False)
            self._updating = False

    @Slot()
    def _on_editor_changed(self):
        if self._updating:
            return
        idxs = self.selected_indices()
        if len(idxs) == 1:
            row = idxs[0]
            new_text = self._editor.toPlainText()
            self._captions[row].text = new_text
            self._updating = True
            
            item = self._table.item(row, 2)
            if item:
                item.setText(new_text)
                
            self._table.resizeRowToContents(row)
            self._updating = False
            self.captions_changed.emit()

    @Slot()
    def _nudge_start_earlier(self):
        for i in self.selected_indices():
            self._captions[i].start_ms = max(0, self._captions[i].start_ms - _NUDGE_MS)
        self._refresh_table()
        self.captions_changed.emit()

    @Slot()
    def _nudge_start_later(self):
        for i in self.selected_indices():
            cap = self._captions[i]
            cap.start_ms = min(cap.end_ms - 100, cap.start_ms + _NUDGE_MS)
        self._refresh_table()
        self.captions_changed.emit()

    @Slot()
    def _nudge_end_earlier(self):
        for i in self.selected_indices():
            cap = self._captions[i]
            cap.end_ms = max(cap.start_ms + 100, cap.end_ms - _NUDGE_MS)
        self._refresh_table()
        self.captions_changed.emit()

    @Slot()
    def _nudge_end_later(self):
        for i in self.selected_indices():
            self._captions[i].end_ms += _NUDGE_MS
        self._refresh_table()
        self.captions_changed.emit()

    @Slot()
    def _split_at_playhead(self):
        """Split the selected caption at the current playhead position."""
        sel = self.selected_indices()
        if len(sel) != 1:
            self.split_feedback.emit(
                "Split requires exactly one caption selected."
            )
            return
        idx = sel[0]
        cap = self._captions[idx]
        ph = self._playhead_ms
        if ph <= cap.start_ms + 100 or ph >= cap.end_ms - 100:
            self.split_feedback.emit(
                "Split requires the playhead inside the selected caption "
                "(not within 100 ms of either edge)."
            )
            return

        # Split at a token boundary without rebuilding the text. Keeping the
        # original slices preserves repeated spaces and explicit line breaks.
        tokens = list(re.finditer(r"\S+", cap.text, flags=re.UNICODE))
        if len(tokens) < 2:
            self.split_feedback.emit(
                "Split requires at least two words in the caption."
            )
            return
        frac = (ph - cap.start_ms) / (cap.end_ms - cap.start_ms)
        split_word = max(1, min(len(tokens) - 1, int(len(tokens) * frac)))
        split_at = tokens[split_word].start()

        cap1 = Caption(
            start_ms=cap.start_ms,
            end_ms=ph,
            text=cap.text[:split_at],
        )
        cap2 = Caption(
            start_ms=ph,
            end_ms=cap.end_ms,
            text=cap.text[split_at:],
        )
        self._captions[idx:idx + 1] = [cap1, cap2]
        self._refresh_table()
        self.captions_changed.emit()

    @Slot()
    def _merge_selected(self):
        """Merge selected contiguous captions into one."""
        sel = self.selected_indices()
        if len(sel) < 2:
            self.merge_feedback.emit(
                "Merge requires at least two captions selected."
            )
            return
        # Ensure contiguous
        if sel[-1] - sel[0] != len(sel) - 1:
            self.merge_feedback.emit(
                "Merge requires contiguous (adjacent) captions selected."
            )
            return
        merged_text = self._merge_caption_texts(
            self._captions[i].text for i in sel
        )
        merged = Caption(
            start_ms=self._captions[sel[0]].start_ms,
            end_ms=self._captions[sel[-1]].end_ms,
            text=merged_text,
        )
        self._captions[sel[0]:sel[-1] + 1] = [merged]
        self._refresh_table()
        self.captions_changed.emit()

    @staticmethod
    def _merge_caption_texts(texts) -> str:
        """Join caption text without discarding existing whitespace."""
        merged = ""
        for text in texts:
            if merged and text and not merged[-1].isspace() and not text[0].isspace():
                merged += " "
            merged += text
        return merged

    @Slot()
    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Split at playhead", self._split_at_playhead)
        menu.addAction("Merge selected", self._merge_selected)
        menu.addAction("Regen selected", self._request_reflow_selected)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    @Slot()
    def _request_reflow_selected(self):
        """Emit signal requesting selected-caption-only reflow."""
        self.reflow_selected_requested.emit()
