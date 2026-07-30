"""SRT parsing and weighted chunk distribution (spec addendum §4.2, §4.4).

Pure logic, no bpy — unit-testable outside Blender.

SRT is the primary import target: it carries start *and* end times, so
the line span is known rather than guessed. Subtitle entries map to
lines **in order** — the entry at file position N supplies line N's
span (with the §5.3 start-index offset, lines 12–20 map to entries
12–20). SRT text is NOT used as lyric content; the delimited text block
stays the source of truth.

Import produces a scaffold, not final timing (§4.1) — the user
fine-tunes in Fusion.
"""

import re

# Weight floor for distribution: without it, chunks like "a" or "ed"
# collapse to near-zero duration and land on top of their neighbour.
MIN_WEIGHT = 2

_TIMESTAMP_RE = re.compile(
    r"(\d+):([0-5]?\d):([0-5]?\d)[,.](\d{1,3})"
)
_TIMING_LINE_RE = re.compile(
    r"^\s*(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)"
)


class SrtParseError(ValueError):
    pass


def timestamp_to_seconds(stamp):
    m = _TIMESTAMP_RE.fullmatch(stamp.strip())
    if not m:
        raise SrtParseError(f"bad SRT timestamp: {stamp!r}")
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def parse_srt(text):
    """Parse SRT text into ``[{"start": s, "end": s, "text": str}, ...]``
    in file order. Tolerates missing index lines, ``.`` millisecond
    separators, and BOM. Raises SrtParseError on a malformed timing line.
    """
    entries = []
    block = []
    for raw in text.lstrip("﻿").splitlines() + [""]:
        if raw.strip():
            block.append(raw)
            continue
        if not block:
            continue
        entries.append(_parse_block(block, position=len(entries) + 1))
        block = []
    return entries


def _parse_block(block, position):
    idx = 0
    # Optional numeric index line.
    if idx < len(block) and block[idx].strip().isdigit():
        idx += 1
    if idx >= len(block):
        raise SrtParseError(f"SRT entry {position}: no timing line")
    m = _TIMING_LINE_RE.match(block[idx])
    if not m:
        raise SrtParseError(
            f"SRT entry {position}: expected 'start --> end', got "
            f"{block[idx].strip()!r}"
        )
    start = timestamp_to_seconds(m.group(1))
    end = timestamp_to_seconds(m.group(2))
    if end < start:
        raise SrtParseError(f"SRT entry {position}: end before start")
    return {
        "start": start,
        "end": end,
        "text": "\n".join(line.strip() for line in block[idx + 1:]),
    }


def entry_for_line(entries, line_no):
    """Entry supplying line ``line_no`` (1-based, in file order), or None."""
    if 1 <= line_no <= len(entries):
        return entries[line_no - 1]
    return None


def distribute(start_seconds, end_seconds, chunk_texts, min_weight=MIN_WEIGHT):
    """Distribute chunk start times across a line span, weighted by chunk
    character length (§4.4). Returns one start time per chunk; the first
    chunk starts at ``start_seconds``. Character count is a proxy for
    sung duration, not a measure of it — the result is a scaffold.
    """
    weights = [max(len(text), min_weight) for text in chunk_texts]
    total = sum(weights)
    span = end_seconds - start_seconds
    cursor = start_seconds
    starts = []
    for w in weights:
        starts.append(cursor)
        cursor += span * (w / total)
    return starts
