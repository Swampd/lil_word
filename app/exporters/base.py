"""Exporter base contracts for the shared Cue schema.

Provides two abstract base classes for format-specific writers:
- ``BaseTextExporter``   – for text-based formats (TTML, EBU-TT, SMPTE-TT, MCC)
- ``BaseBinaryExporter`` – for binary formats (EBU STL)

Both share ``convert_captions()`` via the common ``BaseExporter`` ancestor.

``BaseExporter`` itself is a concrete utility base class — it provides only the
shared ``convert_captions()`` classmethod and carries no abstract ``generate()``
contract.  Direct instantiation is allowed but not useful; all real exporters
should inherit from one of the two typed subclasses.
"""

from abc import ABC, abstractmethod

from app.models.cue import Cue
from app.models.caption import Caption
from app.models.style import CueStyle
from app.models.region import CueRegion


class BaseExporter:
    """Concrete utility base for all caption exporters using the Cue schema.

    Provides the shared ``convert_captions()`` classmethod that maps internal
    Caption objects to the normalized Cue/CueStyle/CueRegion schema.

    This class carries no abstract ``generate()`` method — the typed return
    contract lives in ``BaseTextExporter`` (→ str) and ``BaseBinaryExporter``
    (→ bytes).  All real exporters should inherit from one of those two.
    """

    @classmethod
    def convert_captions(cls, captions: list[Caption], profile=None, settings=None) -> list[Cue]:
        """Map internal simple Captions to robust semantic Cues with independent profile styling.

        If ``settings`` is provided and ``profile`` is not, the settings are
        forwarded to ``get_premiere_safe_profile()`` so that user-configured
        export defaults override the hardcoded baseline.
        """

        if profile is None:
            from app.validation.premiere_profiles import get_premiere_safe_profile
            profile = get_premiere_safe_profile(settings=settings)

        import copy
        cues = []
        for cap in captions:
            # Create a brand new copy of the profile's default style/region per cue
            # so mutating one cue's style does not affect others.
            cues.append(Cue(
                start=cap.start_ms,
                end=cap.end_ms,
                text=cap.text,
                style=copy.deepcopy(profile.default_style),
                region=copy.deepcopy(profile.default_region)
            ))

        return cues


class BaseTextExporter(BaseExporter, ABC):
    """Abstract base for text-based exporters (TTML, EBU-TT, SMPTE-TT, MCC).

    Subclasses implement ``generate()`` returning ``str``.
    """

    @abstractmethod
    def generate(self, cues: list[Cue]) -> str:
        """Process a list of Cue objects into formatted text content."""
        pass


class BaseBinaryExporter(BaseExporter, ABC):
    """Abstract base for binary exporters (EBU STL).

    Subclasses implement ``generate()`` returning ``bytes``.
    """

    @abstractmethod
    def generate(self, cues: list[Cue]) -> bytes:
        """Process a list of Cue objects into binary content."""
        pass
