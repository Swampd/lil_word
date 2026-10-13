import wave

from app.services import alignment_service


class _TrackingWaveReader:
    def __init__(self, reader):
        self._reader = reader
        self.read_requests: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._reader.close()

    def __getattr__(self, name):
        return getattr(self._reader, name)

    def readframes(self, frame_count: int) -> bytes:
        self.read_requests.append(frame_count)
        return self._reader.readframes(frame_count)


class _PatternVad:
    def __init__(self, _aggressiveness: int):
        self.frame_index = 0

    def is_speech(self, _frame: bytes, _sample_rate: int) -> bool:
        index = self.frame_index
        self.frame_index += 1

        # One silence crosses the 30-second read boundary. A second silence
        # reaches EOF, after which a 15 ms fragment remains in the WAV.
        return not (995 <= index <= 1005 or index >= 1998)


def test_detect_silence_streams_bounded_chunks_without_changing_timing(
    tmp_path,
    monkeypatch,
):
    sample_rate = 16_000
    full_frame_count = sample_rate * 60
    partial_frame_count = sample_rate * 15 // 1000
    wav_path = tmp_path / "long_audio.wav"

    with wave.open(str(wav_path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * (full_frame_count + partial_frame_count))

    real_wave_open = wave.open
    opened_readers: list[_TrackingWaveReader] = []

    def tracking_open(path, mode):
        reader = _TrackingWaveReader(real_wave_open(path, mode))
        opened_readers.append(reader)
        return reader

    monkeypatch.setattr(alignment_service, "_HAS_VAD", True)
    monkeypatch.setattr(alignment_service.webrtcvad, "Vad", _PatternVad)
    monkeypatch.setattr(alignment_service.wave, "open", tracking_open)

    silences = alignment_service.detect_silence_regions(str(wav_path))

    assert silences == [(29_850, 30_180), (59_940, 60_000)]
    assert len(opened_readers) == 1
    assert opened_readers[0].read_requests
    assert max(opened_readers[0].read_requests) <= sample_rate * 30

