import tempfile
import os
import pytest
from pathlib import Path
import app.utils.settings

@pytest.fixture(autouse=True)
def isolate_settings_file(monkeypatch):
    """Ensure all tests use a temporary settings file instead of the real appdata one."""
    workspace = Path(__file__).parent.parent
    test_tmp = workspace / ".test_tmp"
    test_tmp.mkdir(exist_ok=True)
    
    with tempfile.NamedTemporaryFile(dir=test_tmp, suffix=".json", delete=False) as f:
        temp_settings = Path(f.name)
        
    monkeypatch.setattr(app.utils.settings, "_SETTINGS_FILE", temp_settings)
    yield
    try:
        temp_settings.unlink(missing_ok=True)
    except OSError:
        pass
