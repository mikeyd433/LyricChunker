"""Verify Line (spec addendum §2.5).

Renders the full line as a single Text object, composites the already-
rendered chunk PNGs, and diffs the two. Reports the max per-pixel delta
(0-255 scale) against the preferences threshold and writes the result
into the line's manifest ``verification`` block. This is the difference
between "kerning is probably fine" and "kerning is fine for this font."
"""

import os

import bpy
from bpy.types import Operator

from .manifest import manifest_filename, read_manifest, write_manifest
from .measure import copy_font_metrics
from .ops_generate import collect_line_chunks, get_target_line
from .ops_render import (
    ChunkVisibilityGuard,
    RenderSettingsGuard,
    alpha_over,
    assert_render_settings,
    load_pixels,
    now_utc_iso,
)
from .ops_setup import apply_house_style, default_material, load_house_font
from .properties import active_camera, set_status, verify_threshold
from .splitting import full_text, split_line

VERIFY_TEMP_NAME = "LC_verify_temp"


def build_full_line_object(context, coll, props):
    """Temporary single Text object holding the whole line, styled and
    placed exactly as the template — the reference the chunks must match."""
    raw = str(coll.get("lc_text_raw", ""))
    delimiter = str(coll.get("lc_delimiter", props.delimiter))
    words, _ = split_line(raw, delimiter)
    body = full_text(words)

    template = props.template_object
    curve = bpy.data.curves.new(VERIFY_TEMP_NAME, type='FONT')
    curve.body = body
    if template is not None and template.type == 'FONT':
        copy_font_metrics(template.data, curve)
        curve.align_x = template.data.align_x
        curve.align_y = template.data.align_y
        mats = [s.material for s in template.material_slots if s.material]
        for mat in mats or [default_material()]:
            curve.materials.append(mat)
    else:
        apply_house_style(curve)
        font = load_house_font()
        if font is not None:
            curve.font = font
        curve.materials.append(default_material())

    obj = bpy.data.objects.new(VERIFY_TEMP_NAME, curve)
    if template is not None:
        obj.location = template.location.copy()
        obj.rotation_euler = template.rotation_euler.copy()
        obj.scale = template.scale.copy()
    else:
        obj.location = context.scene.cursor.location.copy()
    context.scene.collection.objects.link(obj)
    return obj


class LC_OT_verify_line(Operator):
    bl_idname = "lyric_chunker.verify_line"
    bl_label = "Verify Line"
    bl_description = (
        "Render the full line as one text object, composite the rendered "
        "chunk PNGs, and diff — catches kerning drift for this exact font"
    )

    def fail(self, context, message):
        set_status(context, message, error=True)
        self.report({'ERROR'}, message)
        return {'CANCELLED'}

    def execute(self, context):
        import numpy as np

        scene = context.scene
        props = scene.lyric_chunker
        if props.is_rendering:
            return self.fail(context, "A render batch is already running")
        if not props.output_root:
            return self.fail(context, "Set an output root folder first")
        if active_camera(context) is None:
            return self.fail(context, "No camera")

        lines = collect_line_chunks(scene)
        line_no = get_target_line(context)
        if line_no not in lines:
            return self.fail(context, f"No chunks found for Line {line_no}")
        coll, objs = lines[line_no]

        out_root = bpy.path.abspath(props.output_root)
        chunk_paths = [
            os.path.join(out_root, coll.name, f"{obj.name}.png") for obj in objs
        ]
        missing = [p for p in chunk_paths if not os.path.exists(p)]
        if missing:
            return self.fail(
                context,
                f"Render Line {line_no} first — {len(missing)} chunk PNG(s) missing",
            )

        assert_render_settings(scene)
        guard = RenderSettingsGuard(scene)
        visibility = ChunkVisibilityGuard(
            context, lines, [line_no], props.template_object
        )
        reference_path = os.path.join(bpy.app.tempdir, f"lc_verify_line{line_no}.png")
        full_obj = build_full_line_object(context, coll, props)
        try:
            for obj in visibility.all_chunks:
                obj.hide_render = True
            scene.render.filepath = reference_path
            bpy.ops.render.render(write_still=True)
        except Exception as exc:
            return self.fail(context, f"Verify render failed: {exc}")
        finally:
            data = full_obj.data
            bpy.data.objects.remove(full_obj, do_unlink=True)
            bpy.data.curves.remove(data)
            visibility.restore()
            guard.restore()

        reference = load_pixels(reference_path)
        composite = None
        for path in chunk_paths:
            pixels = load_pixels(path)
            composite = pixels if composite is None else alpha_over(composite, pixels)
        if composite.shape != reference.shape:
            return self.fail(
                context,
                "Chunk PNGs and the current render resolution differ — "
                "re-render the line before verifying",
            )

        # Compare premultiplied so fully transparent pixels with junk RGB
        # cannot fail the diff.
        ref_p = reference[..., :3] * reference[..., 3:4]
        com_p = composite[..., :3] * composite[..., 3:4]
        delta_rgb = np.abs(ref_p - com_p).max()
        delta_a = np.abs(reference[..., 3] - composite[..., 3]).max()
        max_delta = int(round(float(max(delta_rgb, delta_a)) * 255.0))

        threshold = verify_threshold(context)
        passed = max_delta <= threshold
        verification = {
            "run": True,
            "max_pixel_delta": max_delta,
            "passed": passed,
        }

        manifest_path = os.path.join(
            out_root, coll.name, manifest_filename(line_no, props.zero_pad)
        )
        if os.path.exists(manifest_path):
            try:
                doc = read_manifest(manifest_path)
                doc["verification"] = verification
                doc["rendered_at"] = doc.get("rendered_at") or now_utc_iso()
                write_manifest(manifest_path, doc)
            except (ValueError, OSError) as exc:
                self.report({'WARNING'}, f"Could not update manifest: {exc}")

        verdict = "PASS" if passed else "FAIL"
        message = (
            f"Verify Line {line_no}: {verdict} — max pixel delta {max_delta} "
            f"(threshold {threshold})"
        )
        set_status(context, message, error=not passed)
        if not passed:
            self.report({'WARNING'}, message)
        return {'FINISHED'}
