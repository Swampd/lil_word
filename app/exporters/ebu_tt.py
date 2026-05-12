"""EBU-TT writer – EBU Tech 3350 profile over the shared Cue/CueStyle/CueRegion schema.

This is a custom writer (no external dependency such as pycaption or lxml).
It emits a TTML-profile document with the EBU-TT namespace extensions and
conservative explicit styles/regions matching the Premiere-safe profile strategy
established by the TTML/DFXP exporter.
"""

from .base import BaseTextExporter
from .ttml_helpers import (
    collect_unique_styles_regions,
    render_style_attrs,
    generate_body_paragraphs,
)
from app.models.cue import Cue


class EBUTTExporter(BaseTextExporter):
    """
    Exports Cues to EBU-TT (EBU Tech 3350) format.

    EBU-TT is a constrained TTML profile used in European broadcasting.
    This writer emits explicit styles and regions per cue, matching the
    conservative Premiere-safe strategy used by TTMLExporter.
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
            '    xmlns:ebuttm="urn:ebu:tt:metadata"',
            '    xmlns:ebutts="urn:ebu:tt:style"',
            '    ttp:timeBase="media"',
            '    xml:lang="en">',
            '  <head>',
            '    <metadata>',
            '      <ebuttm:documentMetadata>',
            '        <ebuttm:conformsToStandard>urn:ebu:tt:distribution:2014-01</ebuttm:conformsToStandard>',
            '      </ebuttm:documentMetadata>',
            '    </metadata>',
            '    <styling>',
        ]

        # ── Style declarations ────────────────────────────────────────────
        for s_id, style_obj in unique_styles:
            doc.append(
                f'      <style xml:id="{s_id}" {render_style_attrs(style_obj)} '
                f'ebutts:linePadding="0.5c" />'
            )

        doc.append('    </styling>')
        doc.append('    <layout>')

        # ── Region declarations ───────────────────────────────────────────
        for r_id, region_obj in unique_regions:
            doc.append(
                f'      <region xml:id="{r_id}" tts:origin="{region_obj.origin}" tts:extent="{region_obj.extent}" '
                f'tts:displayAlign="after" tts:overflow="visible" />'
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
