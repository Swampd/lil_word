import subprocess
from unittest.mock import Mock, patch

import pytest

from app.services import media_service
from app.services.media_service import _run
from app.utils.errors import CancelledError


def test_run_kills_process_when_cancel_termination_times_out():
    proc = Mock()
    proc.poll.side_effect = [None]
    proc.wait.side_effect = [subprocess.TimeoutExpired(["tool"], 5), None]

    with patch("app.services.media_service.subprocess.Popen", return_value=proc):
        with pytest.raises(CancelledError):
            _run(["tool"], cancel_check=lambda: True)

    proc.terminate.assert_called_once_with()
    proc.kill.assert_called_once_with()
    assert proc.wait.call_count == 2


def test_media_properties_are_derived_from_one_probe_payload():
    info = {
        "format": {"duration": "12.3459"},
        "streams": [
            {"codec_type": "audio", "codec_name": "aac"},
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "avg_frame_rate": "30000/1001",
                "r_frame_rate": "60/1",
                "time_base": "1/90000",
            },
        ],
    }

    properties = media_service.media_properties_from_probe(info)

    assert properties.media_duration_ms == 12345
    assert properties.media_fps == 30
    assert properties.has_video is True
    assert properties.needs_proxy is True


def test_media_properties_keep_h264_and_audio_only_proxy_rules():
    h264 = media_service.media_properties_from_probe({
        "format": {"duration": "1.0"},
        "streams": [{
            "codec_type": "video",
            "codec_name": "h264",
            "avg_frame_rate": "24000/1001",
        }],
    })
    audio_only = media_service.media_properties_from_probe({
        "format": {"duration": "2.0"},
        "streams": [{"codec_type": "audio", "codec_name": "flac"}],
    })

    assert h264.media_fps == 24
    assert h264.has_video is True
    assert h264.needs_proxy is False
    assert audio_only.media_fps is None
    assert audio_only.has_video is False
    assert audio_only.needs_proxy is False
