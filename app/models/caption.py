"""Caption block data model."""

from dataclasses import dataclass, field
import uuid


@dataclass
class Caption:
    """A single caption block with timing and text."""
    start_ms: int
    end_ms: int
    text: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def clone(self) -> "Caption":
        return Caption(
            start_ms=self.start_ms,
            end_ms=self.end_ms,
            text=self.text,
            id=uuid.uuid4().hex[:12],
        )

    def __repr__(self) -> str:
        return (
            f"Caption({self.start_ms}-{self.end_ms}ms, "
            f"{len(self.text)} chars, id={self.id})"
        )


@dataclass
class TranscriptWord:
    """A single word from the transcript with timing and confidence."""
    start_ms: int
    end_ms: int
    text: str
    confidence: float = 1.0
    idx: int = 0
