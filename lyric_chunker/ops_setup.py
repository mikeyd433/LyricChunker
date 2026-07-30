"""Set Up Scene (spec addendum §5.0).

Optional and strictly non-destructive: never modifies existing objects,
creates everything inside a dedicated ``LyricChunker`` collection with an
``LC_`` name prefix, and warns instead of creating a second camera when
the scene already has one. The panel works fully in a hand-built scene —
this button is never required.
"""

import math

import bpy
from bpy.types import Operator

from .properties import set_status

SETUP_COLL_NAME = "LyricChunker"
TEMPLATE_NAME = "LC_Template"
CAMERA_NAME = "LC_Camera"
LIGHT_NAME = "LC_Sun"
MATERIAL_NAME = "LC_White"


def default_material():
    """Flat, tintable white. Emission-based so renders are lighting-
    independent and tint cleanly in Fusion."""
    mat = bpy.data.materials.get(MATERIAL_NAME)
    if mat is None:
        mat = bpy.data.materials.new(MATERIAL_NAME)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        bsdf = nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.5
            if "Emission Color" in bsdf.inputs:
                bsdf.inputs["Emission Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = 1.0
    return mat


def _setup_collection(context):
    coll = bpy.data.collections.get(SETUP_COLL_NAME)
    if coll is None:
        coll = bpy.data.collections.new(SETUP_COLL_NAME)
    if coll.name not in context.scene.collection.children:
        context.scene.collection.children.link(coll)
    return coll


class LC_OT_setup_scene(Operator):
    bl_idname = "lyric_chunker.setup_scene"
    bl_label = "Set Up Scene"
    bl_description = (
        "Create a camera framed for one line of text, a minimal light, and "
        "a default template text object — all inside a LyricChunker "
        "collection, never touching existing objects"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        props = scene.lyric_chunker
        coll = _setup_collection(context)
        created = []
        notes = []

        if scene.camera is not None:
            notes.append(
                f"scene already has camera '{scene.camera.name}' — using it"
            )
        elif bpy.data.objects.get(CAMERA_NAME) is None:
            cam_data = bpy.data.cameras.new(CAMERA_NAME)
            cam_data.lens = 50.0
            cam = bpy.data.objects.new(CAMERA_NAME, cam_data)
            # Front view down +Y; at 50mm/36mm sensor this frames roughly
            # ten units of text width at the origin.
            cam.location = (0.0, -14.0, 0.0)
            cam.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
            coll.objects.link(cam)
            scene.camera = cam
            created.append(cam.name)

        if bpy.data.objects.get(LIGHT_NAME) is None:
            light_data = bpy.data.lights.new(LIGHT_NAME, type='SUN')
            light_data.energy = 3.0
            light = bpy.data.objects.new(LIGHT_NAME, light_data)
            light.location = (0.0, -4.0, 6.0)
            light.rotation_euler = (math.radians(35.0), 0.0, 0.0)
            coll.objects.link(light)
            created.append(light.name)

        template = bpy.data.objects.get(TEMPLATE_NAME)
        if template is None:
            curve = bpy.data.curves.new(TEMPLATE_NAME, type='FONT')
            curve.body = "TEMPLATE"
            curve.extrude = 0.03
            curve.bevel_depth = 0.005
            curve.align_x = 'CENTER'
            curve.align_y = 'BOTTOM_BASELINE'
            curve.materials.append(default_material())
            template = bpy.data.objects.new(TEMPLATE_NAME, curve)
            template.location = (0.0, 0.0, 0.0)
            coll.objects.link(template)
            created.append(template.name)

        if props.template_object is None:
            props.template_object = template

        message = (
            f"Created {', '.join(created)}" if created
            else "Scene already set up — nothing created"
        )
        if notes:
            message += f" ({'; '.join(notes)})"
            self.report({'WARNING'}, "; ".join(notes))
        set_status(context, message)
        return {'FINISHED'}
