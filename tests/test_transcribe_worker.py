from unittest.mock import patch, MagicMock
from app.ui.main_window import _TranscribeWorker
from app.utils.settings import Settings
from app.models.project import Project

@patch("app.services.caption_job.transcription_service.transcribe")
@patch("app.services.caption_job.caption_engine.generate_captions")
@patch("app.services.caption_job.alignment_service.refine_timing")
def test_transcribe_worker_forwards_settings(mock_refine, mock_generate_captions, mock_transcribe):
    mock_transcribe.return_value = ([], [])
    mock_generate_captions.return_value = []
    mock_refine.return_value = []

    from pathlib import Path
    settings = Settings(Path(".test_tmp/test_transcribe_worker.json"))
    settings.set("max_chars_per_line", 33)
    settings.set("max_lines", 4)
    settings.set("max_caption_ms", 3500)
    settings.set("min_caption_ms", 850)
    settings.set("min_gap_ms", 90)
    settings.set("lead_in_ms", 110)
    settings.set("lead_out_ms", 160)
    settings.set("target_cps_min", 14)
    settings.set("target_cps_max", 22)

    worker = _TranscribeWorker("dummy.mp3", settings, 5000)
    worker.run()

    mock_generate_captions.assert_called_once()
    kwargs = mock_generate_captions.call_args.kwargs
    
    assert kwargs.get("max_cpl") == 33
    assert kwargs.get("max_lines") == 4
    assert kwargs.get("max_dur") == 3500
    assert kwargs.get("min_dur") == 850
    assert kwargs.get("min_gap") == 90
    assert kwargs.get("lead_in") == 110
    assert kwargs.get("lead_out") == 160
    assert kwargs.get("target_cps_min") == 14
    assert kwargs.get("target_cps_max") == 22
