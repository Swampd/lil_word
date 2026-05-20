import subprocess
from unittest.mock import Mock, patch

import pytest

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
