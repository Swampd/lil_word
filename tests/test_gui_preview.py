import pytest
from PySide6.QtWidgets import QApplication
from app.ui.video_panel import AudioCanvasWidget, SubtitleOverlay

def test_audio_canvas_letterbox():
    app = QApplication.instance() or QApplication([])
    widget = AudioCanvasWidget()
    
    # Force a non-16:9 aspect ratio
    widget.resize(800, 600)  # 4:3
    
    # We can't easily introspect the QPainter output without mock intercept,
    # but we can verify it doesn't crash and has expanding size policy.
    assert widget.sizePolicy().hasHeightForWidth() is False
    assert widget.width() == 800
    assert widget.height() == 600
    
    # Just exercise the paint event to ensure no math errors
    widget.set_filename("test.mp3")
    widget.repaint()

def test_subtitle_overlay_letterbox_math():
    app = QApplication.instance() or QApplication([])
    overlay = SubtitleOverlay()
    
    # Set up some dummy values
    overlay._text = "Hello 16:9"
    overlay._region_origin = (0.0, 0.0)
    overlay._region_extent = (1.0, 1.0)
    
    # 4:3 widget bounds -> should letterbox
    overlay.resize(800, 600)
    overlay.repaint()
    
    # Ensure no crashes during paint
    assert overlay._text == "Hello 16:9"

def test_video_panel_overlay_geometry_on_load():
    from app.ui.video_panel import VideoPanel
    app = QApplication.instance() or QApplication([])
    
    panel = VideoPanel()
    # Force a specific size on the panel
    panel.resize(800, 568)
    # The active widget (DropZone at start) will fill the layout
    app.processEvents()
    
    # Currently media is not loaded, overlay might have default size
    # Load media (e.g., audio only)
    panel.load_media("dummy.mp3", has_video=False)
    
    # Assert that the overlay geometry is immediately updated to match the active stack widget
    # (which is the audio canvas)
    audio_widget = panel._stack.currentWidget()
    assert panel._overlay.geometry() == audio_widget.geometry(), \
        "Overlay geometry did not update to match the active surface on load_media"

