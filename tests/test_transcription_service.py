from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services import transcription_service


def test_transcribe_preserves_zero_word_probability():
    word = SimpleNamespace(start=0.0, end=0.5, word=" zero ", probability=0.0)
    segment = SimpleNamespace(start=0.0, end=0.5, text=" zero ", words=[word])
    model = Mock()
    model.transcribe.return_value = (iter([segment]), SimpleNamespace())

    with patch.object(transcription_service, "_get_model", return_value=model):
        segments, words = transcription_service.transcribe("audio.wav")

    assert segments == [{"start": 0.0, "end": 0.5, "text": "zero"}]
    assert len(words) == 1
    assert words[0].confidence == 0.0
