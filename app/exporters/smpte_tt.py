"""SMPTE-TT writer – SMPTE ST 2052-1 profile over the shared Cue/CueStyle/CueRegion schema.

This is a custom writer (no external dependency).
It emits a TTML-profile document with SMPTE-TT namespace extensions and
conservative explicit styles/regions matching the Premiere-safe profile strategy.
"""

from .base import BaseTextExporter
from .ttml_helpers import (
    collect_unique_styles_regions,
    render_style_attrs,
    generate_body_paragraphs,
)
from app.models.cue import Cue


class SMPTETTExporter(BaseTextExporter):
    """
    Exports Cues to SMPTE-TT (SMPTE ST 2052-1) format.

    SMPTE-TT is the SMPTE Timed Text standard used in North American
    broadcast and digital cinema workflows.  This writer emits explicit
    styles and regions per cue, matching the conservative Premiere-safe
    strategy used by TTMLExporter and EBUTTExporter.
    """

    def generate(self, cues: list[Cue]) -> str:
        unique_styles, unique_regions, style_ids, region_ids = (
            collect_unique_styles_regions(cues)
        )

        # ── Document header ───────────────────────────────────────────────
        doc = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<tt xmlns="http://www.w3.org/ns/ttml"',
            '    xmlns:ttp="http://www.w3.org/ns/ttml#parameter"',
            '    xmlns:tts="http://www.w3.org/ns/ttml#styling"',
            '    xmlns:smpte="http://www.smpte-ra.org/schemas/2052-1/2010/smpte-tt"',
            '    ttp:timeBase="media"',
            '    ttp:cellResolution="32 15"',
            '    xml:lang="en">',
            '  <head>',
            '    <metadata>',
            '      <smpte:information smpte:mode="Enhanced" />',
            '    </metadata>',
            '    <styling>',
        ]

        # ── Style declarations ────────────────────────────────────────────
        for s_id, style_obj in unique_styles:
            doc.append(f'      <style xml:id="{s_id}" {render_style_attrs(style_obj)} />')

        doc.extend([
            '    </styling>',
            '    <layout>',
        ])

        # ── Region declarations ───────────────────────────────────────────
        for r_id, region_obj in unique_regions:
            doc.append(
                f'      <region xml:id="{r_id}" tts:origin="{region_obj.origin}" tts:extent="{region_obj.extent}" '
                f'tts:displayAlign="after" tts:writingMode="lrtb" tts:overflow="visible" />'
            )

        doc.extend([
            '    </layout>',
            '  </head>',
            '  <body>',
            '    <div>',
        ])

        # ── Body paragraphs ──────────────────────────────────────────────
        doc.extend(generate_body_paragraphs(cues, style_ids, region_ids))

        doc.extend([
            '    </div>',
            '  </body>',
            '</tt>',
            '',
        ])

        return '\n'.join(doc)
