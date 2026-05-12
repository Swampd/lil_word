"""Custom exceptions for Lil Word."""

class CancelledError(Exception):
    """Raised when a long-running operation is explicitly cancelled."""
    pass

class ModelDownloadError(Exception):
    """Raised when the transcription model cannot be downloaded (e.g. offline)."""
    pass
