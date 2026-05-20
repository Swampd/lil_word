from pathlib import Path
from unittest.mock import patch

from app.models.caption import Caption, TranscriptWord
from app.services.caption_job import CaptionJobRequest, export_caption_outputs, run_caption_job
from app.utils.errors import CancelledError


def test_caption_job_runs_headless_and_writes_premiere_outputs(tmp_path):
    media_path = tmp_path / "source.mp4"
    media_path.write_bytes(b"fake media")
    captions = [Caption(start_ms=0, end_ms=1000, text="Hello Premiere")]
    words = [TranscriptWord(start_ms=0, end_ms=500, text="Hello", confidence=0.9, idx=0)]
    segments = [{"start": 0.0, "end": 1.0, "text": "Hello Premiere"}]
    settings = {
        "whisper_model": "small",
        "whisper_device": "cpu",
        "whisper_compute_type": "int8",
        "max_chars_per_line": 33,
        "max_lines": 3,
        "lead_in_ms": 120,
        "lead_out_ms": 220,
    }
    progress = []

    with patch("app.services.caption_job.media_service.get_duration_ms", return_value=1000), \
         patch("app.services.caption_job.media_service.has_video_stream", return_value=False), \
         patch("app.services.caption_job.media_service.extract_audio_wav"), \
         patch("app.services.caption_job.transcription_service.transcribe", return_value=(segments, words)) as mock_transcribe, \
         patch("app.services.caption_job.caption_engine.generate_captions", return_value=captions) as mock_generate, \
         patch("app.services.caption_job.alignment_service.refine_timing", return_value=captions):
        result = run_caption_job(
            CaptionJobRequest(
                input_path=str(media_path),
                output_dir=str(tmp_path),
                outputs=["ttml", "srt"],
                settings=settings,
            ),
            progress_callback=progress.append,
        )

    assert result.status == "ok"
    assert result.media_duration_ms == 1000
    assert result.captions == captions
    assert set(result.outputs) == {"ttml", "srt"}
    assert Path(result.outputs["ttml"]).name == "source_lilword.ttml"
    assert Path(result.outputs["srt"]).name == "source_lilword.srt"
    assert Path(result.outputs["ttml"]).exists()
    assert Path(result.outputs["srt"]).read_text(encoding="utf-8").startswith("1\n")

    mock_transcribe.assert_called_once()
    assert mock_transcribe.call_args.kwargs["model_size"] == "small"
    assert mock_transcribe.call_args.kwargs["device"] == "cpu"
    assert mock_generate.call_args.kwargs["max_cpl"] == 33
    assert mock_generate.call_args.kwargs["max_lines"] == 3
    assert mock_generate.call_args.kwargs["lead_in"] == 120
    assert mock_generate.call_args.kwargs["lead_out"] == 220

    phases = [event.phase for event in progress]
    assert phases == [
        "starting",
        "probing_media",
        "extracting_audio",
        "loading_model",
        "transcribing",
        "generating_captions",
        "refining_timing",
        "exporting_ttml",
        "exporting_srt",
        "complete",
    ]


def test_caption_job_returns_cancelled_when_cancelled_before_media(tmp_path):
    result = run_caption_job(
        CaptionJobRequest(input_path=str(tmp_path / "source.mp4"), output_dir=str(tmp_path)),
        cancel_check=lambda: True,
    )

    assert result.status == "cancelled"
    assert result.error is not None
    assert result.error.exception_type == "CancelledError"


def test_caption_job_propagates_cancellation_during_transcription(tmp_path):
    media_path = tmp_path / "source.mp4"
    media_path.write_bytes(b"fake media")

    def cancel_from_transcribe(*args, cancel_check=None, **kwargs):
        assert cancel_check is not None
        raise CancelledError("Transcription cancelled by user.")

    with patch("app.services.caption_job.media_service.get_duration_ms", return_value=1000), \
         patch("app.services.caption_job.media_service.has_video_stream", return_value=False), \
         patch("app.services.caption_job.media_service.extract_audio_wav"), \
         patch("app.services.caption_job.transcription_service.transcribe", side_effect=cancel_from_transcribe):
        result = run_caption_job(
            CaptionJobRequest(input_path=str(media_path), output_dir=str(tmp_path)),
            cancel_check=lambda: False,
        )

    assert result.status == "cancelled"
    assert result.audio_path is not None
    assert result.captions == []


def test_caption_job_output_paths_are_collision_safe(tmp_path):
    media_path = tmp_path / "source.mp4"
    media_path.write_bytes(b"fake media")
    (tmp_path / "source_lilword.srt").write_text("existing", encoding="utf-8")

    outputs, items = export_caption_outputs(
        [Caption(start_ms=0, end_ms=1000, text="Hello")],
        str(media_path),
        str(tmp_path),
        ["srt"],
    )

    assert Path(outputs["srt"]).name == "source_lilword_2.srt"
    assert items[0].format == "srt"
