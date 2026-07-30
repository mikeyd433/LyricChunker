"""JSON manifest read/write and output naming (spec addendum §1).

Pure logic, no bpy — unit-testable outside Blender.

One manifest per line, written into that line's output folder as
``Line<N>.json`` next to the chunk PNGs. ``manifest_version`` increments
on breaking schema change; never reuse a version number for a changed
shape. ``song.json`` at the output root is reserved for the v1.5
cross-line index — do not use that filename for anything else.
"""

import json

MANIFEST_VERSION = 1

# Single source of truth for the add-on version; blender_manifest.toml
# must match (the single-file build script asserts it).
ADDON_ID = "lyric_chunker"
ADDON_VERSION = "2.3.0"

RESERVED_FILENAMES = {"song.json"}


def fmt_num(n, pad):
    return f"{n:02d}" if pad else str(n)


def line_dirname(line_no, pad=False):
    return f"Line{fmt_num(line_no, pad)}"


def chunk_name(line_no, chunk_no, pad=False):
    return f"Line{fmt_num(line_no, pad)}_Chunk{fmt_num(chunk_no, pad)}"


def chunk_filename(line_no, chunk_no, pad=False):
    return chunk_name(line_no, chunk_no, pad) + ".png"


def manifest_filename(line_no, pad=False):
    return line_dirname(line_no, pad) + ".json"


def build_chunk_entry(
    index,
    name,
    text,
    filename,
    world_position,
    screen_position,
    bbox_px,
    offset_x,
    manual_offset_x=0.0,
    start_seconds=None,
    start_frame=None,
    timing_source="none",
):
    """One entry for the ``chunks`` array.

    ``start_seconds`` is the canonical timing value (survives fps
    changes); ``start_frame`` is derived convenience only. No end times —
    chunk visibility duration is a comp-side decision (§4.5).
    ``bbox_px`` is [x_min, y_min, x_max, y_max] with origin at
    bottom-left, matching Blender's camera view and Fusion.
    """
    return {
        "index": index,
        "name": name,
        "text": text,
        "filename": filename,
        "world_position": [round(v, 6) for v in world_position],
        "screen_position": [round(v, 6) for v in screen_position],
        "bbox_px": list(bbox_px),
        "offset_x": round(offset_x, 6),
        "manual_offset_x": round(manual_offset_x, 6),
        "start_seconds": None if start_seconds is None else round(start_seconds, 4),
        "start_frame": start_frame,
        "timing_source": timing_source,
    }


def build_manifest(
    generator,
    project,
    render,
    line,
    chunks,
    verification=None,
    rendered_at=None,
):
    return {
        "manifest_version": MANIFEST_VERSION,
        "generator": generator,
        "project": project,
        "render": render,
        "line": line,
        "chunks": chunks,
        "verification": verification or {"run": False},
        "rendered_at": rendered_at,
    }


def write_manifest(path, manifest):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def read_manifest(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    version = data.get("manifest_version")
    if version != MANIFEST_VERSION:
        raise ValueError(
            f"manifest_version {version!r} in {path} — this add-on reads "
            f"version {MANIFEST_VERSION}"
        )
    return data


def seconds_to_frame(seconds, fps, fps_base=1.0):
    """Derived start_frame; start_seconds stays the source of truth."""
    if seconds is None:
        return None
    return round(seconds * (fps / fps_base))
