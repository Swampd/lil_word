from PySide6.QtWidgets import QApplication
from app.ui.caption_rules_dialog import CaptionRulesDialog
from app.utils.settings import Settings

from pathlib import Path

def test_caption_rules_dialog_bounds_and_persistence():
    app = QApplication.instance() or QApplication([])
    settings_file = Path(".test_tmp/rules_dialog_settings.json")
    if settings_file.exists():
        settings_file.unlink()
    
    settings = Settings(settings_file)
    # Reset some settings for baseline
    settings.set("max_chars_per_line", 42)
    settings.set("target_cps_min", 12)
    
    dlg = CaptionRulesDialog(settings)
    
    # Test bounds of max_cpl
    dlg._spi_max_cpl.setValue(5)
    assert dlg._spi_max_cpl.value() == 10  # Clamped to minimum

    dlg._spi_max_cpl.setValue(105)
    assert dlg._spi_max_cpl.value() == 100  # Clamped to maximum
    
    # Test Cancel does not persist
    dlg._spi_max_cpl.setValue(35)
    dlg.reject()
    assert settings.get("max_chars_per_line") == 42
    
    # Re-instantiate
    dlg2 = CaptionRulesDialog(settings)
    dlg2._spi_max_cpl.setValue(35)
    dlg2._spi_cps_min.setValue(8)
    dlg2.accept()
    
    assert settings.get("max_chars_per_line") == 35
    assert settings.get("target_cps_min") == 8

    # Test inverted cps
    dlg3 = CaptionRulesDialog(settings)
    dlg3._spi_cps_min.setValue(25)
    dlg3._spi_cps_max.setValue(10)
    dlg3.accept()

    assert settings.get("target_cps_min") == 10
    assert settings.get("target_cps_max") == 25

def test_caption_rules_dialog_default_values():
    app = QApplication.instance() or QApplication([])
    settings_file = Path(".test_tmp/rules_dialog_defaults_settings.json")
    if settings_file.exists():
        settings_file.unlink()
        
    # Fresh settings
    settings = Settings(settings_file)
    dlg = CaptionRulesDialog(settings)
    
    # Assert fresh dialog uses the new voiceover defaults
    assert dlg._spi_lead_in.value() == 150
    assert dlg._spi_lead_out.value() == 250
    assert dlg._spi_min_dur.value() == 700
    assert dlg._spi_max_dur.value() == 3500
    assert dlg._spi_min_gap.value() == 100
    assert dlg._spi_cps_min.value() == 12
    assert dlg._spi_cps_max.value() == 20
    assert dlg._spi_max_cpl.value() == 42
    assert dlg._spi_max_lines.value() == 2
