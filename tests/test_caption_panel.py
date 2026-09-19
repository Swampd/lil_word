from PySide6.QtWidgets import QApplication
from unittest.mock import patch

from app.ui.caption_panel import CaptionPanel
from app.models.caption import Caption

def test_caption_panel_full_text_editor():
    app = QApplication.instance() or QApplication([])

    panel = CaptionPanel()
    
    cap1 = Caption(start_ms=0, end_ms=1000, text="A very long text that would be truncated in a table cell due to its ellipses and layout but should remain intact here.")
    cap2 = Caption(start_ms=1000, end_ms=2000, text="Next caption")
    panel.set_captions([cap1, cap2])

    assert panel._editor.isEnabled() is False
    assert panel._editor.toPlainText() == ""

    # Select the first row
    panel._table.selectRow(0)
    assert panel._editor.isEnabled() is True
    assert panel._editor.toPlainText() == cap1.text
    
    # Selecting both should disable the editor
    panel._table.selectAll()
    assert panel._editor.isEnabled() is False
    assert panel._editor.toPlainText() == ""
    assert panel._editor.toPlainText() == ""
    
    # Edit text via the dedicated full-text area
    panel._table.clearSelection()
    panel._table.selectRow(1)
    assert panel._editor.isEnabled() is True
    
    new_text = "Edited caption text via the dedicated field"
    panel._editor.setPlainText(new_text)
    
    # Should automatically reflect back into the active model and table
    assert panel._captions[1].text == new_text
    assert panel._table.item(1, 2).text() == new_text
    
    # Edit inline via table should also reflect into the editor
    panel._table.item(1, 2).setText("Edited inline")
    assert panel._editor.toPlainText() == "Edited inline"
    assert panel._captions[1].text == "Edited inline"

def test_caption_panel_row_sizing():
    app = QApplication.instance() or QApplication([])
    panel = CaptionPanel()
    
    # Needs to be shown to actually calculate layout properly in some environments,
    # but resizeRowToContents works on the internal model regardless.
    cap = Caption(start_ms=0, end_ms=1000, text="Word "*50)
    panel.set_captions([cap])
    
    # Store initial height
    initial_height = panel._table.rowHeight(0)
    
    # Change text to something very short
    panel._table.item(0, 2).setText("Short")
    app.processEvents()
    short_height = panel._table.rowHeight(0)
    
    # Change to something extremely long
    long_text = "Word \n" * 10
    panel._table.item(0, 2).setText(long_text)
    app.processEvents()
    long_height = panel._table.rowHeight(0)
    
    # The height should be adapted to contents
    assert long_height > short_height, f"Row height did not expand for long text ({long_height} vs {short_height})"


def test_playhead_lookup_is_logarithmic_and_end_time_is_inclusive():
    app = QApplication.instance() or QApplication([])
    panel = CaptionPanel()

    class CountingCaption:
        def __init__(self, start_ms, end_ms, text):
            self._start_ms = start_ms
            self.start_reads = 0
            self.end_ms = end_ms
            self.text = text

        @property
        def start_ms(self):
            self.start_reads += 1
            return self._start_ms

    captions = [
        CountingCaption(i * 1000, i * 1000 + 900, f"Caption {i}")
        for i in range(256)
    ]
    panel.set_captions(captions)
    for caption in captions:
        caption.start_reads = 0

    panel.set_playhead(captions[-1]._start_ms + 900)

    assert panel.selected_indices() == [255]
    assert sum(caption.start_reads for caption in captions) < 20


def test_playhead_only_changes_selection_when_active_row_changes():
    app = QApplication.instance() or QApplication([])
    panel = CaptionPanel()
    captions = [
        Caption(start_ms=0, end_ms=1000, text="First"),
        Caption(start_ms=2000, end_ms=3000, text="Second"),
    ]
    panel.set_captions(captions)

    panel.set_playhead(500)
    assert panel.selected_indices() == [0]

    panel._table.selectRow(1)
    panel.set_playhead(600)
    assert panel.selected_indices() == [1]

    panel.set_captions(captions)
    panel._table.selectRow(1)
    panel.set_playhead(1000)
    assert panel.selected_indices() == [0]


def test_refresh_caption_rows_preserves_unaffected_items_and_selection():
    app = QApplication.instance() or QApplication([])
    panel = CaptionPanel()
    captions = [
        Caption(start_ms=0, end_ms=1000, text="First"),
        Caption(start_ms=1100, end_ms=2000, text="Selected"),
    ]
    panel.set_captions(captions)
    panel._table.selectRow(1)
    unaffected_items = [panel._table.item(1, col) for col in range(3)]

    refreshed = [
        Caption(start_ms=100, end_ms=1050, text="First expanded"),
        captions[1],
    ]
    with patch.object(panel._table, "resizeRowsToContents") as resize_all, \
         patch.object(panel._table, "resizeRowToContents") as resize_row:
        panel.refresh_caption_rows(refreshed, [0])

    assert panel._table.item(0, 0).text() == "00:00.1"
    assert panel._table.item(0, 1).text() == "00:01.0"
    assert panel._table.item(0, 2).text() == "First expanded"
    assert [panel._table.item(1, col) for col in range(3)] == unaffected_items
    assert panel.selected_indices() == [1]
    assert panel._editor.isEnabled()
    assert panel._editor.toPlainText() == "Selected"
    resize_all.assert_not_called()
    resize_row.assert_called_once_with(0)
