"""Caption engine – transform transcript segments/words into timed caption blocks.

Implements the timing rules from the plan:
- lead-in padding: 80-150 ms
- lead-out padding: 120-200 ms  
- minimum caption duration: 700 ms
- maximum caption duration: 4000 ms
- minimum gap between captions: 80 ms
- target reading speed: 12-18 chars/sec
- max lines: 2
- prefer line breaks at punctuation and natural phrase boundaries
- avoid 1-word orphan second lines
- never overlap adjacent captions
"""

from __future__ import annotations

import re
from typing import Optional

from app.models.caption import Caption, TranscriptWord

# ── Defaults (Tuned for Voiceover Cadence) ──

LEAD_IN_MS = 150
LEAD_OUT_MS = 250
MIN_CAPTION_MS = 700
MAX_CAPTION_MS = 3500
MIN_GAP_MS = 100
TARGET_CPS_MIN = 12
TARGET_CPS_MAX = 20
MAX_LINES = 2
MAX_CHARS_PER_LINE = 42

# Punctuation that is a good split point
_SPLIT_PUNCT = re.compile(r"[.!?,;:–—\-]$")


def generate_captions(
    segments: list[dict],
    words: list[TranscriptWord],
    *,
    lead_in: int = LEAD_IN_MS,
    lead_out: int = LEAD_OUT_MS,
    min_dur: int = MIN_CAPTION_MS,
    max_dur: int = MAX_CAPTION_MS,
    min_gap: int = MIN_GAP_MS,
    max_lines: int = MAX_LINES,
    max_cpl: int = MAX_CHARS_PER_LINE,
    target_cps_min: int = TARGET_CPS_MIN,
    target_cps_max: int = TARGET_CPS_MAX,
    media_duration_ms: int = 0,
) -> list[Caption]:
    """Build caption blocks from transcript data.

    If word-level timestamps are available and usable, they drive the splits.
    Otherwise we fall back to segment-level timing.
    """
    if words and len(words) >= 2:
        captions = _build_from_words(
            words, lead_in=lead_in, lead_out=lead_out,
            min_dur=min_dur, max_dur=max_dur,
            max_lines=max_lines, max_cpl=max_cpl,
            target_cps_min=target_cps_min, target_cps_max=target_cps_max,
        )
    else:
        captions = _build_from_segments(
            segments, lead_in=lead_in, lead_out=lead_out,
            min_dur=min_dur, max_dur=max_dur,
            max_lines=max_lines, max_cpl=max_cpl,
            target_cps_min=target_cps_min, target_cps_max=target_cps_max,
        )

    # Post-process: deterministic normalizer
    captions = normalize_captions(
        captions, min_dur=min_dur, min_gap=min_gap,
        media_duration_ms=media_duration_ms,
    )
    return captions


# ── Deterministic timing normalizer (shared) ─────────────────────────────────

def normalize_captions(
    captions: list[Caption],
    *,
    min_dur: int = MIN_CAPTION_MS,
    min_gap: int = MIN_GAP_MS,
    media_duration_ms: int = 0,
) -> list[Caption]:
    """Normalize caption timing with deterministic priority:

    1. No negative starts
    2. No overlaps  (hard guarantee)
    3. Clamp to media duration  (hard guarantee when media_duration_ms > 0)
    4. Min gap when possible  (best effort)
    5. Min duration when possible  (best effort, never violates #2/#3)

    Captions entirely outside the media duration are dropped.
    If captions are too dense to satisfy both min-duration and no-overlap,
    adjacent captions are merged rather than allowed to overlap.
    """
    if not captions:
        return captions

    # Sort by start time
    captions.sort(key=lambda c: c.start_ms)

    # Pass 1: clamp negative starts
    for cap in captions:
        if cap.start_ms < 0:
            cap.start_ms = 0

    # Pass 2: drop captions entirely outside media duration, clamp the rest
    if media_duration_ms > 0:
        kept: list[Caption] = []
        for cap in captions:
            if cap.start_ms >= media_duration_ms:
                # Entirely after media end — try to merge text into previous
                if kept:
                    kept[-1].text = kept[-1].text + " " + cap.text
                # Otherwise drop silently
                continue
            if cap.end_ms > media_duration_ms:
                cap.end_ms = media_duration_ms
            kept.append(cap)
        captions = kept

    if not captions:
        return captions

    # Pass 3: ensure end > start (minimum 50ms)
    for cap in captions:
        if cap.end_ms <= cap.start_ms:
            cap.end_ms = cap.start_ms + min(50, min_dur)

    # Pass 4: forward sweep – eliminate overlaps, try to maintain min_gap
    for i in range(len(captions) - 1):
        cur = captions[i]
        nxt = captions[i + 1]

        if cur.end_ms + min_gap > nxt.start_ms:
            # Overlapping or gap too small
            if cur.end_ms > nxt.start_ms:
                # Hard overlap: split the difference at the midpoint
                mid = (cur.end_ms + nxt.start_ms) // 2
                cur.end_ms = mid
                nxt.start_ms = mid
            else:
                # Gap exists but is smaller than min_gap – acceptable, don't overlap
                pass

    # Pass 5: merge captions that became degenerate (duration < 50ms) after overlap fix
    merged: list[Caption] = []
    for cap in captions:
        if cap.end_ms - cap.start_ms < 50:
            # Try to merge into previous
            if merged:
                merged[-1].end_ms = max(merged[-1].end_ms, cap.end_ms)
                merged[-1].text = merged[-1].text + " " + cap.text
            else:
                cap.end_ms = cap.start_ms + min(min_dur, 200)
                merged.append(cap)
        else:
            merged.append(cap)
    captions = merged

    # Pass 6: best-effort min duration (extend end, but not past next start or media end)
    for i, cap in enumerate(captions):
        if cap.end_ms - cap.start_ms < min_dur:
            desired_end = cap.start_ms + min_dur
            # Don't overlap with next caption
            if i < len(captions) - 1:
                desired_end = min(desired_end, captions[i + 1].start_ms)
            # Don't exceed media duration
            if media_duration_ms > 0:
                desired_end = min(desired_end, media_duration_ms)
            cap.end_ms = desired_end

    # Final: re-clamp media duration
    if media_duration_ms > 0:
        for cap in captions:
            if cap.end_ms > media_duration_ms:
                cap.end_ms = media_duration_ms

    # Final guarantee: no overlaps (paranoia check)
    for i in range(len(captions) - 1):
        if captions[i].end_ms > captions[i + 1].start_ms:
            captions[i].end_ms = captions[i + 1].start_ms

    # Final: drop any remaining zero-duration captions
    captions = [c for c in captions if c.end_ms > c.start_ms]

    return captions


# ── Word-based caption building ──────────────────────────────────────────────

def _build_from_words(
    words: list[TranscriptWord],
    lead_in: int,
    lead_out: int,
    min_dur: int,
    max_dur: int,
    max_lines: int,
    max_cpl: int,
    target_cps_min: int,
    target_cps_max: int,
) -> list[Caption]:
    """Group words into caption blocks respecting timing and length rules."""
    captions: list[Caption] = []
    buf_words: list[TranscriptWord] = []
    buf_start: int = 0

    for w in words:
        if not buf_words:
            buf_words.append(w)
            buf_start = w.start_ms
            continue

        current_text = " ".join(bw.text for bw in buf_words) + " " + w.text
        current_dur = w.end_ms - buf_start
        line_count = _count_lines(current_text, max_cpl)

        # Should we flush the buffer?
        should_flush = False
        pause_ms = w.start_ms - buf_words[-1].end_ms

        # Duration would exceed max
        if current_dur > max_dur:
            should_flush = True
        # Too many lines
        elif line_count > max_lines:
            should_flush = True
        # Explicit long pause detection (much more natural than CPS dropping)
        elif current_dur >= min_dur and pause_ms > 400:
            should_flush = True
        # Good split point: punctuation at end of previous word
        elif (current_dur >= min_dur
              and _SPLIT_PUNCT.search(buf_words[-1].text)
              and (len(current_text) > max_cpl * 0.5 or pause_ms > 150)):
            should_flush = True
        # Speed bounds (CPS)
        elif current_dur >= min_dur and (
            (len(current_text) / (max(current_dur, 1) / 1000.0)) < target_cps_min or
            (len(current_text) / (max(current_dur, 1) / 1000.0)) > target_cps_max
        ):
            # The naive CPS heuristic causes awkward mid-phrase chopping during slow/fast speech.
            # We only force a CPS flush if the text has reasonable substance (e.g. >70% of a line),
            # preventing 1- or 2-word fragments from breaking the human reading cadence.
            if len(" ".join(bw.text for bw in buf_words)) > max_cpl * 0.7:
                should_flush = True

        if should_flush:
            text = " ".join(bw.text for bw in buf_words)
            text = _wrap_text(text, max_cpl)
            captions.append(Caption(
                start_ms=max(0, buf_start - lead_in),
                end_ms=buf_words[-1].end_ms + lead_out,
                text=text,
            ))
            buf_words = [w]
            buf_start = w.start_ms
        else:
            buf_words.append(w)

    # Flush remainder
    if buf_words:
        text = " ".join(bw.text for bw in buf_words)
        text = _wrap_text(text, max_cpl)
        captions.append(Caption(
            start_ms=max(0, buf_start - lead_in),
            end_ms=buf_words[-1].end_ms + lead_out,
            text=text,
        ))

    return captions


# ── Segment-based caption building (fallback) ────────────────────────────────

def _build_from_segments(
    segments: list[dict],
    lead_in: int,
    lead_out: int,
    min_dur: int,
    max_dur: int,
    max_lines: int,
    max_cpl: int,
    target_cps_min: int,
    target_cps_max: int,
) -> list[Caption]:
    """Build captions from segment-level timing (no word timestamps)."""
    captions: list[Caption] = []
    for seg in segments:
        start_ms = int(seg["start"] * 1000)
        end_ms = int(seg["end"] * 1000)
        text = seg["text"].strip()
        if not text:
            continue

        total_dur = end_ms - start_ms
        seg_cps = len(text) / (max(total_dur, 1) / 1000.0)
        
        # If the segment is short enough (after potential slow-capping), emit as-is
        if total_dur <= max_dur and _count_lines(text, max_cpl) <= max_lines and target_cps_min <= seg_cps <= target_cps_max:
            # We already know it passes CPS rules here, so no truncation needed on this path.
            captions.append(Caption(
                start_ms=max(0, start_ms - lead_in),
                end_ms=end_ms + lead_out,
                text=_wrap_text(text, max_cpl),
            ))
        else:
            # Split long segments proportionally by word count
            seg_words = text.split()
            num_chunks = max(1, total_dur // max_dur + 1)
            
            # If still violating CPS limits, force more chunks to distribute text weight
            if seg_cps > target_cps_max:
                multiplier = int((seg_cps // max(target_cps_max, 1)) + 1)
                num_chunks = max(num_chunks, multiplier)
                
            chunk_size = max(1, len(seg_words) // num_chunks)
            
            for i in range(0, len(seg_words), chunk_size):
                chunk = seg_words[i:i + chunk_size]
                if not chunk:
                    continue
                frac_start = i / len(seg_words)
                frac_end = min((i + len(chunk)) / len(seg_words), 1.0)
                c_start = start_ms + int(total_dur * frac_start)
                c_end = start_ms + int(total_dur * frac_end)
                
                chunk_text_joined = " ".join(chunk)
                chunk_dur = c_end - c_start
                chunk_cps = len(chunk_text_joined) / (max(chunk_dur, 1) / 1000.0)
                
                # Apply slow-reading truncation recursively to chunks
                if target_cps_min > 0 and chunk_cps < target_cps_min:
                    desired_dur = int((len(chunk_text_joined) / target_cps_min) * 1000.0)
                    c_end = c_start + max(min_dur, desired_dur)
                
                captions.append(Caption(
                    start_ms=max(0, c_start - lead_in),
                    end_ms=c_end + lead_out,
                    text=_wrap_text(chunk_text_joined, max_cpl),
                ))

    return captions


# ── Text wrapping ────────────────────────────────────────────────────────────

def _wrap_text(text: str, max_cpl: int) -> str:
    """Wrap caption text into ≤2 lines, preferring natural break points."""
    text = text.strip()
    if len(text) <= max_cpl:
        return text

    words = text.split()
    if len(words) <= 1:
        return text

    # Find the best split point near the midpoint
    best_idx = len(words) // 2
    best_score = 999

    for i in range(1, len(words)):
        line1 = " ".join(words[:i])
        line2 = " ".join(words[i:])
        # Avoid 1-word orphan on second line
        if len(words) - i == 1 and len(words) > 3:
            continue
        balance = abs(len(line1) - len(line2))
        # Bonus for splitting after punctuation
        punct_bonus = -5 if _SPLIT_PUNCT.search(words[i - 1]) else 0
        score = balance + punct_bonus
        if score < best_score:
            best_score = score
            best_idx = i

    line1 = " ".join(words[:best_idx])
    line2 = " ".join(words[best_idx:])
    return f"{line1}\n{line2}"


def _count_lines(text: str, max_cpl: int) -> int:
    """Estimate how many lines a text would need."""
    if not text:
        return 0
    return (len(text) + max_cpl - 1) // max_cpl
