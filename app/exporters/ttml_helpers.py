"""Shared TTML-family exporter helpers.

Contains common logic used by TTML/DFXP, EBU-TT, and SMPTE-TT writers:
- Timecode formatting
- Style/region identity hashing and deduplication
- Paragraph body generation (text escaping, newline→<br/>, style/region binding)
"""

import xml.sax.saxutils

from app.models.cue import Cue
from app.utils.colors import normalize_hex_color


def format_time(ms: int) -> str:
    """Format milliseconds to TTML full-clock timecode 'HH:MM:SS.mmm'."""
    val = max(0, ms)
    s, msec = divmod(val, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{msec:03d}"


def style_key(style) -> tuple:
    """Return a hashable tuple capturing all identity-relevant style fields."""
    return (
        style.font_family,
        style.font_size,
        style.fill_color,
        style.background_color,
        style.text_align,
        style.italic,
        style.bold,
        style.underline,
    )


def region_key(region) -> tuple:
    """Return a hashable tuple capturing all identity-relevant region fields."""
    return (region.region_name, region.origin, region.extent)


def collect_unique_styles_regions(cues: list[Cue]):
    """Deduplicate styles and regions across a list of cues.

    Returns:
        (unique_styles, unique_regions, style_ids, region_ids)
        where unique_styles/regions are lists of (xml_id, obj) pairs
        and style_ids/region_ids are dicts mapping hash-tuples to xml_ids.
    """
    unique_styles: list[tuple[str, object]] = []
    unique_regions: list[tuple[str, object]] = []
    s_ids: dict[tuple, str] = {}
    r_ids: dict[tuple, str] = {}

    for cue in cues:
        if cue.style:
            sk = style_key(cue.style)
            if sk not in s_ids:
                s_id = f"style-{len(unique_styles)}"
                unique_styles.append((s_id, cue.style))
                s_ids[sk] = s_id

        if cue.region:
            rk = region_key(cue.region)
            if rk not in r_ids:
                safe_name = "".join(
                    c if c.isalnum() else "_" for c in cue.region.region_name
                ).strip("_") or "region"
                r_id = f"{safe_name}-{len(unique_regions)}"
                unique_regions.append((r_id, cue.region))
                r_ids[rk] = r_id

    return unique_styles, unique_regions, s_ids, r_ids


def render_style_attrs(style_obj) -> str:
    """Return the common tts: attribute string fragment for a style declaration.

    All user-configurable values are XML-escaped to prevent malformed output
    when Settings contain characters like ``&``, ``<``, or ``"``.
    """
    def _esc_attr(val: str) -> str:
        """Escape a string for safe use inside XML double-quoted attributes."""
        return xml.sax.saxutils.escape(val, {'"': '&quot;'})

    font_family = _esc_attr(str(style_obj.font_family))
    font_size = _esc_attr(str(style_obj.font_size))
    text_align = _esc_attr(str(style_obj.text_align))
    fill_color = _esc_attr(normalize_hex_color(style_obj.fill_color, "#FFFFFF"))
    bg_color = _esc_attr(normalize_hex_color(style_obj.background_color, "#00000000"))
    font_style = "italic" if style_obj.italic else "normal"
    font_weight = "bold" if style_obj.bold else "normal"
    text_decoration = "underline" if style_obj.underline else "none"
    return (
        f'tts:fontFamily="{font_family}" tts:fontSize="{font_size}" '
        f'tts:textAlign="{text_align}" tts:color="{fill_color}" '
        f'tts:backgroundColor="{bg_color}" '
        f'tts:fontStyle="{font_style}" tts:fontWeight="{font_weight}" '
        f'tts:textDecoration="{text_decoration}"'
    )


def generate_body_paragraphs(
    cues: list[Cue],
    style_ids: dict[tuple, str],
    region_ids: dict[tuple, str],
) -> list[str]:
    """Generate <p> elements for the TTML <body><div> section."""
    paragraphs: list[str] = []
    for index, cue in enumerate(cues, 1):
        start = format_time(cue.start)
        end = format_time(cue.end)

        safe_text = xml.sax.saxutils.escape(cue.text)
        lines = safe_text.split('\\n') if '\\n' in safe_text else safe_text.split('\n')
        p_content = '<br />'.join(lines)

        s_attr = ""
        if cue.style:
            s_attr = f' style="{style_ids[style_key(cue.style)]}"'

        r_attr = ""
        if cue.region:
            r_attr = f' region="{region_ids[region_key(cue.region)]}"'

        paragraphs.append(
            f'      <p xml:id="cue{index}" begin="{start}" end="{end}"{r_attr}{s_attr}>{p_content}</p>'
        )
    return paragraphs
