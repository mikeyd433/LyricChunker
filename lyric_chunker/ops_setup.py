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
    """White Principled BSDF matching the project's house material:
    metallic 0, roughness 0.5, alpha 1 — lit by the scene, tinted in
    Fusion."""
    mat = bpy.data.materials.get(MATERIAL_NAME)
    if mat is None:
        mat = bpy.data.materials.new(MATERIAL_NAME)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        bsdf = nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            bsdf.inputs["Metallic"].default_value = 0.0
            bsdf.inputs["Roughness"].default_value = 0.5
    return mat


# The project's house style (from the reference Text object): Georgia
# Bold Italic, extrude 0.12, round bevel 0.03 @ resolution 4, character
# spacing 1.1, word spacing 1.4, Left / Top Baseline alignment.
HOUSE_STYLE = {
    "extrude": 0.12,
    "bevel_depth": 0.03,
    "bevel_resolution": 4,
    "space_character": 1.1,
    "space_word": 1.4,
    "align_x": 'LEFT',
    "align_y": 'TOP_BASELINE',
}

# Where Georgia Bold Italic usually lives, per platform. If none of
# these resolve, the template falls back to Blender's built-in font and
# the operator says so — the style is otherwise identical.
HOUSE_FONT_CANDIDATES = (
    "C:\\Windows\\Fonts\\georgiaz.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold Italic.ttf",
    "/Library/Fonts/Georgia Bold Italic.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Georgia_Bold_Italic.ttf",
)


def load_house_font():
    for path in HOUSE_FONT_CANDIDATES:
        try:
            return bpy.data.fonts.load(path, check_existing=True)
        except RuntimeError:
            continue
    return None


def apply_house_style(curve):
    for attr, value in HOUSE_STYLE.items():
        setattr(curve, attr, value)


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
            apply_house_style(curve)
            font = load_house_font()
            if font is not None:
                curve.font = font
            else:
                notes.append(
                    "Georgia Bold Italic not found on this machine — "
                    "template uses the built-in font; pick yours in the "
                    "Font panel"
                )
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
