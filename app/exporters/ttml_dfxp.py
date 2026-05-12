"""TTML/DFXP writer over the shared Cue/CueStyle/CueRegion schema.

Premiere-safe profile: explicitly binds styles and regions per cue
to avoid CSS inheritance loopholes in third-party NLEs.
"""

from .base import BaseTextExporter
from .ttml_helpers import (
    collect_unique_styles_regions,
    render_style_attrs,
    generate_body_paragraphs,
)
from app.models.cue import Cue


class TTMLExporter(BaseTextExporter):
    """
    Exports Cues to Premiere-safe TTML/DFXP format.
    Explicitly binds styles and regions per object to avoid inheritance loopholes.
    """

    def generate(self, cues: list[Cue]) -> str:
        unique_styles, unique_regions, style_ids, region_ids = (
            collect_unique_styles_regions(cues)
        )

        # ── Document header ───────────────────────────────────────────────
        doc = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<tt xmlns="http://www.w3.org/ns/ttml"',
            '    xmlns:tts="http://www.w3.org/ns/ttml#styling"',
            '    xmlns:ttp="http://www.w3.org/ns/ttml#parameter"',
            '    xml:lang="en">',
            '  <head>',
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
                f'      <region xml:id="{r_id}" tts:origin="{region_obj.origin}" tts:extent="{region_obj.extent}" />'
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
