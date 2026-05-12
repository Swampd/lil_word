from PySide6.QtWidgets import QApplication
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
