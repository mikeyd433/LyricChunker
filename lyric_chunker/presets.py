"""Style presets (spec addendum §5.2): save and load named style
configurations (font, size, extrude, bevel, material, alignment) on the
scene. The active preset name is recorded in each manifest's
``project.style_preset``."""

import bpy
from bpy.types import Operator, UIList

from .properties import set_status

PRESET_FIELDS = (
    "size",
    "extrude",
    "bevel_depth",
    "bevel_resolution",
    "shear",
    "space_character",
    "space_word",
    "align_x",
    "align_y",
)


def capture_preset(preset, template):
    data = template.data
    preset.font_path = data.font.filepath if data.font is not None else ""
    for field in PRESET_FIELDS:
        setattr(preset, field, getattr(data, field))
    mats = [s.material for s in template.material_slots if s.material]
    preset.material_name = mats[0].name if mats else ""


def apply_preset(preset, template):
    """Write a preset onto the template object. Returns warnings."""
    warnings = []
    data = template.data
    if preset.font_path:
        try:
            data.font = bpy.data.fonts.load(preset.font_path, check_existing=True)
        except RuntimeError:
            warnings.append(f"font file unresolved: {preset.font_path}")
    for field in PRESET_FIELDS:
        setattr(data, field, getattr(preset, field))
    if preset.material_name:
        mat = bpy.data.materials.get(preset.material_name)
        if mat is None:
            warnings.append(f"material '{preset.material_name}' not found")
        else:
            data.materials.clear()
            data.materials.append(mat)
    return warnings


class LC_UL_style_presets(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_prop, index):
        layout.prop(item, "name", text="", emboss=False, icon='PRESET')


class LC_OT_preset_save(Operator):
    bl_idname = "lyric_chunker.preset_save"
    bl_label = "Save Preset"
    bl_description = "Capture the template object's current style as a named preset"

    def execute(self, context):
        props = context.scene.lyric_chunker
        template = props.template_object
        if template is None or template.type != 'FONT':
            set_status(context, "Pick a text template object first", error=True)
            self.report({'ERROR'}, "Pick a text template object first")
            return {'CANCELLED'}
        preset = props.style_presets.add()
        preset.name = f"Preset {len(props.style_presets)}"
        capture_preset(preset, template)
        props.style_preset_index = len(props.style_presets) - 1
        props.active_preset = preset.name
        set_status(context, f"Saved style preset '{preset.name}'")
        return {'FINISHED'}


class LC_OT_preset_apply(Operator):
    bl_idname = "lyric_chunker.preset_apply"
    bl_label = "Apply Preset"
    bl_description = "Apply the selected preset to the template object"

    def execute(self, context):
        props = context.scene.lyric_chunker
        template = props.template_object
        if template is None or template.type != 'FONT':
            set_status(context, "Pick a text template object first", error=True)
            self.report({'ERROR'}, "Pick a text template object first")
            return {'CANCELLED'}
        if not (0 <= props.style_preset_index < len(props.style_presets)):
            set_status(context, "No preset selected", error=True)
            return {'CANCELLED'}
        preset = props.style_presets[props.style_preset_index]
        warnings = apply_preset(preset, template)
        props.active_preset = preset.name
        message = f"Applied style preset '{preset.name}'"
        if warnings:
            message += f" — {'; '.join(warnings)}"
            for w in warnings:
                self.report({'WARNING'}, w)
        set_status(context, message, error=False)
        return {'FINISHED'}


class LC_OT_preset_remove(Operator):
    bl_idname = "lyric_chunker.preset_remove"
    bl_label = "Remove Preset"
    bl_description = "Delete the selected preset"

    def execute(self, context):
        props = context.scene.lyric_chunker
        index = props.style_preset_index
        if not (0 <= index < len(props.style_presets)):
            return {'CANCELLED'}
        name = props.style_presets[index].name
        props.style_presets.remove(index)
        props.style_preset_index = min(index, len(props.style_presets) - 1)
        if props.active_preset == name:
            props.active_preset = ""
        set_status(context, f"Removed style preset '{name}'")
        return {'FINISHED'}
