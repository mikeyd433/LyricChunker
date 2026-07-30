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


def _join_clip_path(png_dir, filename):
    """Join using the clip dir's own separator style — the path is
    consumed by Resolve on the user's machine, not this one."""
    sep = "\\" if ("\\" in png_dir or re.match(r"^[A-Za-z]:", png_dir)) else "/"
    return png_dir.rstrip("/\\") + sep + filename


def _lua_str(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _num(value):
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def line_local_frames(doc):
    """Per-chunk start frames relative to the line's own start, for
    comps that live on a per-line timeline clip starting at frame 0.

    Returns (frames, warnings): one int per chunk. Chunks without
    timing land at 0 and produce a warning.
    """
    warnings = []
    render = doc.get("render", {})
    fps = render.get("fps", 24) / render.get("fps_base", 1.0)
    line = doc.get("line", {})
    starts = [c.get("start_frame") for c in doc["chunks"]]
    if line.get("start_seconds") is not None:
        base = round(line["start_seconds"] * fps)
    else:
        timed = [s for s in starts if s is not None]
        base = min(timed) if timed else 0
    frames = []
    for chunk, start in zip(doc["chunks"], starts):
        if start is None:
            warnings.append(
                f"{chunk['name']}: no timing (timing_source "
                f"{chunk.get('timing_source', 'none')!r}) — placed at frame 0"
            )
            frames.append(0)
        else:
            frames.append(max(0, start - base))
    return frames, warnings


def comp_length(doc, frames):
    render = doc.get("render", {})
    fps = render.get("fps", 24) / render.get("fps_base", 1.0)
    line = doc.get("line", {})
    if line.get("start_seconds") is not None and line.get("end_seconds") is not None:
        return max(1, round((line["end_seconds"] - line["start_seconds"]) * fps))
    return max(frames) + round(fps) if frames else round(fps)


def _loader(name, filename, length, pos):
    length = length + LOADER_HOLD_PADDING
    return f"""\
\t\t{name} = Loader {{
\t\t\tClips = {{
\t\t\t\tClip {{
\t\t\t\t\tID = "Clip1",
\t\t\t\t\tFilename = {_lua_str(filename)},
\t\t\t\t\tFormatID = "PNGFormat",
\t\t\t\t\tStartFrame = 0,
\t\t\t\t\tLengthSetManually = true,
\t\t\t\t\tTrimIn = 0,
\t\t\t\t\tTrimOut = 0,
\t\t\t\t\tExtendFirst = 0,
\t\t\t\t\tExtendLast = {length},
\t\t\t\t\tLoop = 0,
\t\t\t\t\tAspectMode = 0,
\t\t\t\t\tDepth = 0,
\t\t\t\t\tGlobalStart = 0,
\t\t\t\t\tGlobalEnd = {length}
\t\t\t\t}}
\t\t\t}},
\t\t\tInputs = {{
\t\t\t\t["Gamut.SLogVersion"] = Input {{ Value = FuID {{ "SLog2" }}, }},
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


def _transform(name, source, start, dip_in, dip_out, depth, pos):
    """Transform whose Center rides a 3-point PolyPath (rest, -depth,
    rest) via a Displacement spline keyed 0 -> 0.5 -> 1 at S, S+dip_in,
    S+dip_in+dip_out — the exact structure of the reference comp's
    hand-animated bounce, so it edits identically in the spline editor."""
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
""" + _spline(
        path + "Displacement", (255, 0, 255),
        [(start, 0.0), (start + dip_in, 0.5), (start + dip_in + dip_out, 1.0)],
        locked_y=True,
    )


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
):
    """Build the pasteable node-graph text for one line manifest.

    ``png_dir`` is the directory holding the chunk PNGs (normally the
    manifest's own folder). Returns ``(text, warnings)``. The graph ends
    at the last Merge (or the single chunk's Transform) — wire that to
    MediaOut after pasting.
    """
    chunks = doc["chunks"]
    if not chunks:
        raise ValueError("manifest has no chunks")
    frames, warnings = line_local_frames(doc)
    length = comp_length(doc, frames)

    tools = []
    branch_tips = []
    for row, (chunk, start) in enumerate(zip(chunks, frames)):
        base = chunk["name"]
        y = row * _ROW_Y
        loader = f"Load_{base}"
        color = f"Color_{base}"
        move = f"Move_{base}"
        tools.append(_loader(
            loader, _join_clip_path(png_dir, chunk["filename"]), length,
            (0.0, y),
        ))
        tools.append(_color_gain(color, loader, start, dip_in, highlight, (_COL_X, y)))
        tools.append(_transform(move, color, start, dip_in, dip_out, dip_depth, (2 * _COL_X, y)))
        branch_tips.append(move)

    line_no = doc["line"]["index"]
    current = branch_tips[0]
    for i, tip in enumerate(branch_tips[1:], start=1):
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
