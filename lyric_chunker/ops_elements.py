"""Reactor elements — Blender-side helpers.

The reactor itself is comp-side (``comp/reactor.py``): elements are
transparent PNGs that bounce on chunk timing, configured in
``elements.json`` at the render output root. These two operators cover
the Blender end of that:

- **Create Elements File** writes the starter config (two heads
  alternating odd/even chunks) plus the ``elements/`` folder.
- **Render Element** renders the selected objects alone, full-frame and
  transparent, straight into ``elements/`` — so an element modelled in
  Blender enters the pipeline exactly like a photo cut-out does.
"""

import json
import os

import bpy
from bpy.types import Operator

from .comp.reactor import ELEMENTS_FILENAME, template_elements
from .ops_render import RenderSettingsGuard, assert_render_settings
from .properties import active_camera, set_status

ELEMENTS_DIRNAME = "elements"


class LC_OT_create_elements(Operator):
    bl_idname = "lyric_chunker.create_elements"
    bl_label = "Create Elements File"
    bl_description = (
        "Write a starter elements.json at the output root — two images "
        "alternating on odd and even chunks, with notes on switching to "
        "a single bouncing element"
    )

    def fail(self, context, message):
        set_status(context, message, error=True)
        self.report({'ERROR'}, message)
        return {'CANCELLED'}

    def execute(self, context):
        props = context.scene.lyric_chunker
        if not props.output_root:
            return self.fail(context, "Set an output root folder first")
        out_root = bpy.path.abspath(props.output_root)
        path = os.path.join(out_root, ELEMENTS_FILENAME)
        if os.path.exists(path):
            return self.fail(
                context, f"{ELEMENTS_FILENAME} already exists — edit it"
            )
        try:
            os.makedirs(os.path.join(out_root, ELEMENTS_DIRNAME), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(template_elements(), fh, indent=2)
                fh.write("\n")
        except OSError as exc:
            return self.fail(context, f"Cannot write {path}: {exc}")
        set_status(
            context,
            f"Wrote {path} — put element PNGs in {ELEMENTS_DIRNAME}/, edit "
            "the file, then Generate Fusion Comps",
        )
        return {'FINISHED'}


class LC_OT_render_element(Operator):
    bl_idname = "lyric_chunker.render_element"
    bl_label = "Render Element"
    bl_description = (
        "Render the selected objects alone as a full-frame transparent "
        "PNG into elements/, ready to use as a bouncing element"
    )

    def fail(self, context, message):
        set_status(context, message, error=True)
        self.report({'ERROR'}, message)
        return {'CANCELLED'}

    def execute(self, context):
        scene = context.scene
        props = scene.lyric_chunker
        if props.is_rendering:
            return self.fail(context, "A render batch is running")
        if not props.output_root:
            return self.fail(context, "Set an output root folder first")
        if active_camera(context) is None:
            return self.fail(context, "No camera")
        selected = [obj for obj in context.selected_objects]
        if not selected:
            return self.fail(
                context, "Select the object(s) to render as an element"
            )

        name = (context.active_object or selected[0]).name
        out_dir = os.path.join(
            bpy.path.abspath(props.output_root), ELEMENTS_DIRNAME
        )
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            return self.fail(context, f"Output path not writable: {exc}")
        filepath = os.path.join(out_dir, f"{name}.png")

        keep = set(selected)
        saved = {}
        assert_render_settings(scene)
        guard = RenderSettingsGuard(scene)
        try:
            # Everything except the selection is hidden, so the element
            # lands full-frame and transparent like a lyric chunk.
            for obj in scene.objects:
                saved[obj] = obj.hide_render
                obj.hide_render = obj not in keep
            scene.render.filepath = filepath
            bpy.ops.render.render(write_still=True)
        except Exception as exc:
            return self.fail(context, f"Element render failed: {exc}")
        finally:
            for obj, hidden in saved.items():
                try:
                    obj.hide_render = hidden
                except ReferenceError:
                    pass
            guard.restore()

        set_status(
            context,
            f"Rendered element to {filepath} — reference it as "
            f"'{ELEMENTS_DIRNAME}/{name}.png' in {ELEMENTS_FILENAME}",
        )
        return {'FINISHED'}
