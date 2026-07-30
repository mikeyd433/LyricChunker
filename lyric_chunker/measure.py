"""Prefix width measurement via a temporary Text object (spec addendum §2.3).

Widths are read from the depsgraph-evaluated object — text dimensions
are not valid until evaluation.

Refinement over the plain cumulative-prefix method: each chunk's offset
is measured as

    offset_i = max_x(prefix + chunk_i) - max_x(chunk_i alone)

with both bodies measured LEFT-aligned. Subtracting the chunk's own
extent means word-separating spaces (which have no ink and would vanish
from a trailing-space measurement) are always interior to the measured
body, and the kerning pair straddling the chunk boundary is captured in
the offset. The residual §2.4 error is only the glyphs' own rendering,
which is identical either way.

Alignment: chunks are built LEFT/BASELINE-aligned and the template's
alignment is folded into a single base offset, measured by comparing the
full line's evaluated bounds under the template's alignment vs
LEFT/BASELINE. This keeps offsets measured against the same origin they
are applied to.
"""

import bpy

from .splitting import flat_chunks, full_text, prefix_text

TEMP_MEASURE_NAME = "LC_measure_temp"

FONT_METRIC_ATTRS = (
    "size",
    "shear",
    "space_character",
    "space_word",
    "space_line",
    "small_caps_scale",
    "resolution_u",
    "extrude",
    "bevel_depth",
    "bevel_resolution",
    "offset",
)


def copy_font_metrics(src_data, dst_data):
    """Copy everything that affects glyph placement/extents from one text
    datablock to another."""
    if src_data.font is not None:
        dst_data.font = src_data.font
    for attr in FONT_METRIC_ATTRS:
        setattr(dst_data, attr, getattr(src_data, attr))


def evaluated_bounds(context, obj):
    """(min_x, min_y, max_x, max_y) of the evaluated object's local
    bound_box. Returns zeros for empty geometry."""
    context.view_layer.update()
    deps = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps)
    corners = eval_obj.bound_box
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return min(xs), min(ys), max(xs), max(ys)


class TextMeasurer:
    """Temporary Text object for width measurement. Use as a context
    manager so the temp object is always cleaned up."""

    def __init__(self, context, template, align_x='LEFT', align_y='BOTTOM_BASELINE'):
        self.context = context
        curve = bpy.data.curves.new(TEMP_MEASURE_NAME, type='FONT')
        if template is not None and template.type == 'FONT':
            copy_font_metrics(template.data, curve)
        curve.align_x = align_x
        curve.align_y = align_y
        self.obj = bpy.data.objects.new(TEMP_MEASURE_NAME, curve)
        self.obj.hide_render = True
        context.scene.collection.objects.link(self.obj)

    def bounds(self, body):
        self.obj.data.body = body
        return evaluated_bounds(self.context, self.obj)

    def max_x(self, body):
        return self.bounds(body)[2]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        data = self.obj.data
        bpy.data.objects.remove(self.obj, do_unlink=True)
        bpy.data.curves.remove(data)
        return False


def measure_layout(context, template, words):
    """Measure per-chunk X offsets and the alignment base offset.

    Returns ``(offsets, base)``: ``offsets`` is one local-space X offset
    per flat chunk, relative to the LEFT/BASELINE origin of the full
    line; ``base`` is the ``(x, y)`` translation that maps that origin
    into the template's alignment, so a chunk's final local position is
    ``(base_x + offset_i, base_y)``.
    """
    chunks = flat_chunks(words)
    line = full_text(words)

    with TextMeasurer(context, template) as m:
        offsets = []
        for i, chunk in enumerate(chunks):
            # The line up to and including this chunk, spaces intact.
            body = prefix_text(words, i) + chunk
            offsets.append(m.max_x(body) - m.max_x(chunk))
        left_bounds = m.bounds(line)

    base = (0.0, 0.0)
    if template is not None and template.type == 'FONT':
        with TextMeasurer(
            context,
            template,
            align_x=template.data.align_x,
            align_y=template.data.align_y,
        ) as m:
            aligned_bounds = m.bounds(line)
        base = (
            aligned_bounds[0] - left_bounds[0],
            aligned_bounds[1] - left_bounds[1],
        )
    return offsets, base
