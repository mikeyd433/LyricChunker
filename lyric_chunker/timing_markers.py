"""Timeline-marker timing and source precedence (spec addendum §4.3, §4.4).

Pure logic, no bpy — markers arrive as plain ``(name, frame)`` tuples so
this module is unit-testable outside Blender.

Markers are the only route to genuine chunk-level timing: the user
scrubs the song in the VSE and taps ``M`` along to the vocal. Matching
rules, in priority order:

  1. Named markers — a marker named ``Line1_Chunk1`` binds to that chunk
     directly (zero-padding in the marker name is tolerated).
  2. Positional fallback — if no named markers exist, markers map to
     chunks in chronological order.
  3. Count mismatch — warn with specifics, apply what matches, leave the
     rest at timing_source "none".

Precedence when SRT timing is also present: markers win per chunk;
chunks without a marker fall back to SRT distribution within their line.
"""

import re

CHUNK_MARKER_RE = re.compile(r"^Line0*(\d+)_Chunk0*(\d+)$", re.IGNORECASE)


def match_markers(markers, chunk_keys, fps):
    """Map markers to chunks.

    ``markers``: list of ``(name, frame)`` tuples.
    ``chunk_keys``: ordered list of ``(line_no, chunk_no)`` for every
    chunk being timed, in line/chunk order.
    ``fps``: effective frames per second (fps / fps_base).

    Returns ``(times, warnings)`` where ``times`` maps
    ``(line_no, chunk_no) -> start_seconds`` for matched chunks only.
    """
    warnings = []
    times = {}
    named = []
    for name, frame in markers:
        m = CHUNK_MARKER_RE.match(name.strip())
        if m:
            named.append(((int(m.group(1)), int(m.group(2))), frame))

    if named:
        chunk_set = set(chunk_keys)
        for key, frame in named:
            if key not in chunk_set:
                warnings.append(
                    f"marker Line{key[0]}_Chunk{key[1]} matches no generated "
                    "chunk — ignored"
                )
                continue
            if key in times:
                warnings.append(
                    f"duplicate marker for Line{key[0]}_Chunk{key[1]} — "
                    "keeping the earliest"
                )
                times[key] = min(times[key], frame / fps)
                continue
            times[key] = frame / fps
        return times, warnings

    if markers:
        ordered = sorted(frame for _, frame in markers)
        if len(ordered) != len(chunk_keys):
            warnings.append(
                f"{len(ordered)} markers, {len(chunk_keys)} chunks — applied "
                "what matches in order; the rest keep timing_source 'none'"
            )
        for key, frame in zip(chunk_keys, ordered):
            times[key] = frame / fps
    return times, warnings


def resolve_line_timing(
    line_no,
    chunk_texts,
    marker_times,
    srt_entry,
    distribute,
):
    """Combine marker and SRT timing for one line (§4.4 precedence).

    ``marker_times``: ``(line_no, chunk_no) -> seconds`` from
    :func:`match_markers`.
    ``srt_entry``: ``{"start": s, "end": s}`` or None.
    ``distribute``: the weighted distribution function
    (:func:`timing_srt.distribute`), injected to keep this module free of
    import direction concerns.

    Returns ``(chunk_times, line_span, line_source)`` where
    ``chunk_times`` is a list of ``(start_seconds_or_None, source)`` per
    chunk, ``line_span`` is ``(start, end)`` or ``(None, None)``, and
    ``line_source`` is "srt", "marker", or "none".
    """
    srt_starts = None
    if srt_entry is not None:
        srt_starts = distribute(srt_entry["start"], srt_entry["end"], chunk_texts)

    chunk_times = []
    any_marker = False
    for i in range(len(chunk_texts)):
        key = (line_no, i + 1)
        if key in marker_times:
            chunk_times.append((marker_times[key], "marker"))
            any_marker = True
        elif srt_starts is not None:
            chunk_times.append((srt_starts[i], "srt"))
        else:
            chunk_times.append((None, "none"))

    if srt_entry is not None:
        line_span = (srt_entry["start"], srt_entry["end"])
        line_source = "srt"
    elif any_marker:
        marked = [t for t, src in chunk_times if src == "marker"]
        line_span = (min(marked), None)
        line_source = "marker"
    else:
        line_span = (None, None)
        line_source = "none"
    return chunk_times, line_span, line_source
