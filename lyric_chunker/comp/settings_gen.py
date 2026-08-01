"""Fusion node-graph generation from a line manifest (spec addendum §6).

Pure logic, no bpy — runs standalone (``scripts/generate_comp.py``) or
from inside Blender later.

Emits Fusion's clipboard ``.setting`` text: paste it into a Fusion comp
and the full per-chunk graph appears, replicating the reference
workflow captured from the Salizar_Brenda comp:

    Loader -> ColorGain -> Transform -> Merge chain

Per chunk, at its (line-local) start frame S:
  - ColorGain: Gain Green/Blue keyframed from (1.0, 1.0) at S to
    (0.4, 0.05) at S+1 — a one-frame flip from white to the highlight
    orange. Red and Alpha stay 1.0.
  - Transform: Center rides a 3-point PolyPath (rest, dip -0.015, rest)
    whose Displacement spline is keyed 0 -> 0.5 -> 1 at S, S+1, S+4 —
    byte-for-byte the structure of the hand-animated reference bounce.

Delivery is the §6.3 clipboard route. The reference comp uses MediaIn
nodes fed by the Media Pool; generated graphs use Loader nodes reading
the PNGs from disk, which avoids Media Pool IDs that cannot be
fabricated from outside Resolve. EXPERIMENTAL until pasted Loaders are
confirmed to render on the Fusion page of the target Resolve install —
if they do not, the fallback is pasting everything except the Loaders
and connecting Media Pool imports by hand.
"""

import re

from .reactor import (
    DEFAULT_ARC_HEIGHT,
    DEFAULT_ELEMENT_DEPTH,
    DEFAULT_ELEMENT_DIP_IN,
    DEFAULT_ELEMENT_DIP_OUT,
    DEFAULT_ELEMENT_POSITION,
    DEFAULT_HOP_FRAMES,
    DEFAULT_TRAVEL_OFFSET,
    applies_to_line,
    chunk_indices,
    displacement_keys,
    is_absolute,
    safe_name,
    travel_keys,
)

DEFAULT_HIGHLIGHT_GAIN = (1.0, 0.4, 0.05)
DEFAULT_DIP_DEPTH = 0.015
DEFAULT_DIP_IN = 1
DEFAULT_DIP_OUT = 3

# ViewInfo grid spacing, roughly matching the hand-built reference layout.
_COL_X = 110.0
_ROW_Y = 33.0

# Loaders hold their still well past the line's own span (10 min at
# 24fps) so stretching the comp clip on the timeline never runs the
# image out.
LOADER_HOLD_PADDING = 14400

# With no timing data at all, chunks cascade across this many seconds
# (weighted by chunk length, like the SRT distribution) instead of all
# firing at frame 0. Real timing comes from markers or SRT.
DEFAULT_UNTIMED_SECONDS = 3.0
UNTIMED_MIN_WEIGHT = 2


def _join_clip_path(png_dir, filename):
    """Join using the clip dir's own separator style — the path is
    consumed by Resolve on the user's machine, not this one."""
    sep = "\\" if ("\\" in png_dir or re.match(r"^[A-Za-z]:", png_dir)) else "/"
    return png_dir.rstrip("/\\") + sep + filename


def _element_path(image, base_dir):
    """Element images may be absolute or relative to elements.json."""
    if is_absolute(image):
        return image
    sep = "\\" if ("\\" in base_dir or re.match(r"^[A-Za-z]:", base_dir)) else "/"
    tail = image.replace("/", sep).replace("\\", sep)
    return base_dir.rstrip("/\\") + sep + tail


def _lua_str(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _num(value):
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def line_local_frames(doc, untimed_seconds=DEFAULT_UNTIMED_SECONDS,
                      untimed_frames=None):
    """Per-chunk start frames relative to the line's own start, for
    comps that live on a per-line timeline clip starting at frame 0.

    Fully untimed lines get a length-weighted cascade across
    ``untimed_seconds`` — or exactly ``untimed_frames`` frames when
    given, which overrides the seconds value (§4.4-style scaffold). A
    partially timed line keeps its timed chunks; the untimed ones land
    at 0 with a warning.
    """
    warnings = []
    render = doc.get("render", {})
    fps = render.get("fps", 24) / render.get("fps_base", 1.0)
    line = doc.get("line", {})
    chunks = doc["chunks"]
    starts = [c.get("start_frame") for c in chunks]

    if all(s is None for s in starts):
        span = untimed_frames if untimed_frames else fps * untimed_seconds
        weights = [max(len(c.get("text", "")), UNTIMED_MIN_WEIGHT) for c in chunks]
        total = sum(weights)
        cursor = 0.0
        frames = []
        for w in weights:
            frames.append(round(cursor))
            cursor += span * (w / total)
        spread = (
            f"{untimed_frames} frames" if untimed_frames
            else f"{untimed_seconds:g}s"
        )
        warnings.append(
            f"no timing data — chunks spread across the first {spread} "
            "as a scaffold; use markers or an SRT for real timing"
        )
        return frames, warnings

    if line.get("start_seconds") is not None:
        base = round(line["start_seconds"] * fps)
    else:
        timed = [s for s in starts if s is not None]
        base = min(timed) if timed else 0
    frames = []
    for chunk, start in zip(chunks, starts):
        if start is None:
            warnings.append(
                f"{chunk['name']}: no timing (timing_source "
                f"{chunk.get('timing_source', 'none')!r}) — placed at frame 0"
            )
            frames.append(0)
        else:
            frames.append(max(0, start - base))
    return frames, warnings


def pixel_resolution(doc):
    render = doc.get("render", {})
    pct = render.get("resolution_percentage", 100) / 100.0
    return (
        max(1, round(render.get("resolution_x", 1920) * pct)),
        max(1, round(render.get("resolution_y", 1080) * pct)),
    )


def chunk_landing(chunk, resolution, offset):
    """Where a travelling element should land on this chunk: the top
    centre of its pixel bbox, plus the element's offset.

    ``bbox_px`` is [x_min, y_min, x_max, y_max] with the origin at
    bottom-left (§1.4), which is already Fusion's convention — so the
    normalized result drops straight into a Transform centre.
    """
    res_x, res_y = resolution
    bbox = chunk.get("bbox_px")
    if bbox and len(bbox) == 4 and bbox[2] > bbox[0]:
        x = ((bbox[0] + bbox[2]) / 2.0) / res_x
        y = bbox[3] / res_y
    else:
        screen = chunk.get("screen_position") or (0.5, 0.5)
        x, y = screen[0], screen[1]
    return (x + offset[0], y + offset[1])


def comp_length(doc, frames):
    render = doc.get("render", {})
    fps = render.get("fps", 24) / render.get("fps_base", 1.0)
    line = doc.get("line", {})
    if line.get("start_seconds") is not None and line.get("end_seconds") is not None:
        return max(1, round((line["end_seconds"] - line["start_seconds"]) * fps))
    return max(frames) + round(fps) if frames else round(fps)


def _loader(name, filename, length, pos, frame_index, clip_frames):
    """One chunk's Loader.

    Fusion resolves the numbered chunk PNGs into a single image
    sequence (``Line17_Chunk##``) and re-bases every Loader to its
    first frame, regardless of which file the Loader names — verified
    against Resolve 21. Each Loader therefore pins its own chunk by
    trimming to its 0-based ``frame_index`` in the ``clip_frames``-long
    sequence, held via ExtendLast."""
    length = length + LOADER_HOLD_PADDING
    return f"""\
\t\t{name} = Loader {{
\t\t\tClips = {{
\t\t\t\tClip {{
\t\t\t\t\tID = "Clip1",
\t\t\t\t\tFilename = {_lua_str(filename)},
\t\t\t\t\tFormatID = "PNGFormat",
\t\t\t\t\tLength = {clip_frames},
\t\t\t\t\tSaving = false,
\t\t\t\t\tTrimIn = {frame_index},
\t\t\t\t\tTrimOut = {frame_index},
\t\t\t\t\tExtendFirst = 0,
\t\t\t\t\tExtendLast = {length},
\t\t\t\t\tLoop = 1,
\t\t\t\t\tAspectMode = 0,
\t\t\t\t\tDepth = 0,
\t\t\t\t\tTimeCode = 0,
\t\t\t\t\tGlobalStart = 0,
\t\t\t\t\tGlobalEnd = {length}
\t\t\t\t}}
\t\t\t}},
\t\t\tInputs = {{
\t\t\t\t["Gamut.SLogVersion"] = Input {{ Value = FuID {{ "SLog2" }}, }},
\t\t\t\tPostMultiplyByAlpha = Input {{ Value = 1, }},
\t\t\t}},
\t\t\tViewInfo = OperatorInfo {{ Pos = {{ {_num(pos[0])}, {_num(pos[1])} }} }},
\t\t}},
"""


def _spline(name, color, keyframes, locked_y=False):
    flags = "Linear = true, LockedY = true" if locked_y else "Linear = true"
    frames = ",\n".join(
        f"\t\t\t\t[{frame}] = {{ {_num(value)}, Flags = {{ {flags} }} }}"
        for frame, value in keyframes
    )
    return f"""\
\t\t{name} = BezierSpline {{
\t\t\tSplineColor = {{ Red = {color[0]}, Green = {color[1]}, Blue = {color[2]} }},
\t\t\tKeyFrames = {{
{frames}
\t\t\t}}
\t\t}},
"""


def _color_gain(name, source, start, dip_in, highlight, pos):
    """ColorGain with Green/Blue gain keyframed white -> highlight."""
    parts = [f"""\
\t\t{name} = ColorGain {{
\t\t\tInputs = {{
\t\t\t\tInput = Input {{ SourceOp = {_lua_str(source)}, Source = "Output", }},
\t\t\t\tGainRed = Input {{ Value = {_num(highlight[0])}, }},
\t\t\t\tGainGreen = Input {{ SourceOp = {_lua_str(name + "_Green")}, Source = "Value", }},
\t\t\t\tGainBlue = Input {{ SourceOp = {_lua_str(name + "_Blue")}, Source = "Value", }},
\t\t\t}},
\t\t\tViewInfo = OperatorInfo {{ Pos = {{ {_num(pos[0])}, {_num(pos[1])} }} }},
\t\t}},
"""]
    parts.append(_spline(
        name + "_Green", (16, 164, 16),
        [(start, 1.0), (start + dip_in, highlight[1])],
    ))
    parts.append(_spline(
        name + "_Blue", (16, 16, 164),
        [(start, 1.0), (start + dip_in, highlight[2])],
    ))
    return "".join(parts)


def _place_transform(name, source, position, size, pos):
    """Static placement for an element that is not already full-frame.

    Full-frame elements (the recommended form, matching the chunk PNGs)
    need no placement at all — this is only emitted when a position or
    size is actually given."""
    return f"""\
\t\t{name} = Transform {{
\t\t\tInputs = {{
\t\t\t\tInput = Input {{ SourceOp = {_lua_str(source)}, Source = "Output", }},
\t\t\t\tCenter = Input {{ Value = {{ {_num(position[0])}, {_num(position[1])} }}, }},
\t\t\t\tSize = Input {{ Value = {_num(size)}, }},
\t\t\t}},
\t\t\tViewInfo = OperatorInfo {{ Pos = {{ {_num(pos[0])}, {_num(pos[1])} }} }},
\t\t}},
"""


def _travel_transform(name, source, x_keys, y_keys, size, pos):
    """Transform whose Centre is driven by an XYPath — independent X and
    Y splines, so the horizontal hop and the vertical arc are keyed
    exactly rather than inferred from path geometry."""
    path = name + "Path"
    return f"""\
\t\t{name} = Transform {{
\t\t\tInputs = {{
\t\t\t\tInput = Input {{ SourceOp = {_lua_str(source)}, Source = "Output", }},
\t\t\t\tCenter = Input {{ SourceOp = {_lua_str(path)}, Source = "Value", }},
\t\t\t\tSize = Input {{ Value = {_num(size)}, }},
\t\t\t}},
\t\t\tViewInfo = OperatorInfo {{ Pos = {{ {_num(pos[0])}, {_num(pos[1])} }} }},
\t\t}},
\t\t{path} = XYPath {{
\t\t\tDrawMode = "ModifyOnly",
\t\t\tInputs = {{
\t\t\t\tX = Input {{ SourceOp = {_lua_str(path + "X")}, Source = "Value", }},
\t\t\t\tY = Input {{ SourceOp = {_lua_str(path + "Y")}, Source = "Value", }},
\t\t\t}},
\t\t}},
""" + _spline(path + "X", (255, 128, 0), x_keys) \
    + _spline(path + "Y", (255, 0, 128), y_keys)


def _bounce_transform(name, source, keys, depth, pos):
    """Transform whose Center rides a 3-point PolyPath (rest, -depth,
    rest), driven by an explicit Displacement key list — the exact
    structure of the reference comp's hand-animated bounce, so it edits
    identically in the spline editor."""
    path = name + "Path"
    return f"""\
\t\t{name} = Transform {{
\t\t\tInputs = {{
\t\t\t\tInput = Input {{ SourceOp = {_lua_str(source)}, Source = "Output", }},
\t\t\t\tCenter = Input {{ SourceOp = {_lua_str(path)}, Source = "Position", }},
\t\t\t}},
\t\t\tViewInfo = OperatorInfo {{ Pos = {{ {_num(pos[0])}, {_num(pos[1])} }} }},
\t\t}},
\t\t{path} = PolyPath {{
\t\t\tDrawMode = "InsertAndModify",
\t\t\tInputs = {{
\t\t\t\tDisplacement = Input {{
\t\t\t\t\tSourceOp = {_lua_str(path + "Displacement")},
\t\t\t\t\tSource = "Value",
\t\t\t\t}},
\t\t\t\tPolyLine = Input {{
\t\t\t\t\tValue = Polyline {{
\t\t\t\t\t\tPoints = {{
\t\t\t\t\t\t\t{{ Linear = true, LockY = true, X = 0, Y = 0 }},
\t\t\t\t\t\t\t{{ Linear = true, LockY = true, X = 0, Y = {_num(-depth)} }},
\t\t\t\t\t\t\t{{ Linear = true, LockY = true, X = 0, Y = 0 }}
\t\t\t\t\t\t}}
\t\t\t\t\t}},
\t\t\t\t}}
\t\t\t}},
\t\t}},
""" + _spline(path + "Displacement", (255, 0, 255), keys, locked_y=True)


def _transform(name, source, start, dip_in, dip_out, depth, pos):
    """A lyric chunk's single bounce at its start frame."""
    keys = [
        (start, 0.0),
        (start + dip_in, 0.5),
        (start + dip_in + dip_out, 1.0),
    ]
    return _bounce_transform(name, source, keys, depth, pos)


def _element_branch(element, base_dir, starts, landings, length, row):
    """One reactor element.

    ``travel`` motion hops the element between word positions, landing
    on each chunk's start frame; ``bob`` (the default) dips it in place.
    """
    name = safe_name(element.get("name"))
    y = row * _ROW_Y
    loader = f"Load_El_{name}"
    size = float(element.get("size", 1.0))

    # Element images are standalone files, so no sequence trimming.
    parts = [_loader(
        loader, _element_path(element["image"], base_dir), length,
        (0.0, y), frame_index=0, clip_frames=1,
    )]
    tip = loader

    if str(element.get("motion", "bob")).lower() == "travel":
        x_keys, y_keys, warnings = travel_keys(
            starts, landings,
            int(element.get("hop_frames", DEFAULT_HOP_FRAMES)),
            float(element.get("arc_height", DEFAULT_ARC_HEIGHT)),
        )
        if x_keys:
            travel = f"Travel_El_{name}"
            parts.append(_travel_transform(
                travel, tip, x_keys, y_keys, size, (_COL_X, y)
            ))
            tip = travel
        return "".join(parts), tip, [f"element '{name}': {w}" for w in warnings]

    depth = float(element.get("bounce_depth", DEFAULT_ELEMENT_DEPTH))
    dip_in = int(element.get("dip_in", DEFAULT_ELEMENT_DIP_IN))
    dip_out = int(element.get("dip_out", DEFAULT_ELEMENT_DIP_OUT))
    position = tuple(element.get("position", DEFAULT_ELEMENT_POSITION))
    if position != tuple(DEFAULT_ELEMENT_POSITION) or size != 1.0:
        place = f"Place_El_{name}"
        parts.append(_place_transform(place, tip, position, size, (_COL_X, y)))
        tip = place

    keys, warnings = displacement_keys(starts, dip_in, dip_out)
    warnings = [f"element '{name}': {w}" for w in warnings]
    if keys:
        bounce = f"Bounce_El_{name}"
        parts.append(_bounce_transform(bounce, tip, keys, depth, (2 * _COL_X, y)))
        tip = bounce
    return "".join(parts), tip, warnings


def _merge(name, background, foreground, pos):
    return f"""\
\t\t{name} = Merge {{
\t\t\tInputs = {{
\t\t\t\tBackground = Input {{ SourceOp = {_lua_str(background)}, Source = "Output", }},
\t\t\t\tForeground = Input {{ SourceOp = {_lua_str(foreground)}, Source = "Output", }},
\t\t\t\tPerformDepthMerge = Input {{ Value = 0, }},
\t\t\t}},
\t\t\tViewInfo = OperatorInfo {{ Pos = {{ {_num(pos[0])}, {_num(pos[1])} }} }},
\t\t}},
"""


def generate_line_setting(
    doc,
    png_dir,
    highlight=DEFAULT_HIGHLIGHT_GAIN,
    dip_depth=DEFAULT_DIP_DEPTH,
    dip_in=DEFAULT_DIP_IN,
    dip_out=DEFAULT_DIP_OUT,
    untimed_seconds=DEFAULT_UNTIMED_SECONDS,
    untimed_frames=None,
    elements=None,
    elements_dir=None,
):
    """Build the pasteable node-graph text for one line manifest.

    ``png_dir`` is the directory holding the chunk PNGs (normally the
    manifest's own folder). ``elements`` is the optional reactor element
    list (§ reactor.py), resolved against ``elements_dir``. Returns
    ``(text, warnings)``. The graph ends at the last Merge (or a single
    branch's tip) — wire that to MediaOut after pasting.
    """
    chunks = doc["chunks"]
    if not chunks:
        raise ValueError("manifest has no chunks")
    frames, warnings = line_local_frames(doc, untimed_seconds, untimed_frames)
    length = comp_length(doc, frames)
    line_no = doc["line"]["index"]

    behind, in_front = [], []
    for element in (elements or []):
        if not applies_to_line(element, line_no):
            continue
        (in_front if element.get("in_front") else behind).append(element)

    tools = []

    resolution = pixel_resolution(doc)

    def add_elements(group, first_row):
        """Element branches, returning their tip names in order."""
        tips = []
        for offset, element in enumerate(group):
            indices = chunk_indices(element, len(chunks))
            starts = [frames[i] for i in indices]
            travel_offset = tuple(
                element.get("offset", DEFAULT_TRAVEL_OFFSET)
            )
            landings = [
                chunk_landing(chunks[i], resolution, travel_offset)
                for i in indices
            ]
            text, tip, element_warnings = _element_branch(
                element, elements_dir or png_dir, starts, landings, length,
                first_row + offset,
            )
            tools.append(text)
            warnings.extend(element_warnings)
            tips.append(tip)
        return tips

    # Behind the lyrics first — the merge chain stacks in list order.
    back_tips = add_elements(behind, len(chunks))

    branch_tips = []
    for row, (chunk, start) in enumerate(zip(chunks, frames)):
        base = chunk["name"]
        y = row * _ROW_Y
        loader = f"Load_{base}"
        color = f"Color_{base}"
        move = f"Move_{base}"
        tools.append(_loader(
            loader, _join_clip_path(png_dir, chunk["filename"]), length,
            (0.0, y), frame_index=row, clip_frames=len(chunks),
        ))
        tools.append(_color_gain(color, loader, start, dip_in, highlight, (_COL_X, y)))
        tools.append(_transform(move, color, start, dip_in, dip_out, dip_depth, (2 * _COL_X, y)))
        branch_tips.append(move)

    front_tips = add_elements(in_front, len(chunks) + len(behind))
    ordered_tips = back_tips + branch_tips + front_tips

    current = ordered_tips[0]
    for i, tip in enumerate(ordered_tips[1:], start=1):
        merge = f"Merge_Line{line_no}_{i}"
        tools.append(_merge(
            merge, current, tip,
            (3 * _COL_X + i * 40.0, (i + 0.5) * _ROW_Y),
        ))
        current = merge

    text = (
        "{\n"
        "\tTools = ordered() {\n"
        + "".join(tools)
        + "\t},\n"
        f"\tActiveTool = {_lua_str(current)}\n"
        "}\n"
    )
    return text, warnings
