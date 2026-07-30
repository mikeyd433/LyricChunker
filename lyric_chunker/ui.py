"""Panel (3D Viewport sidebar > Lyric Chunker)."""

from bpy.types import Panel

from .ops_generate import LC_OT_generate_chunks, LC_OT_new_lyrics_text, get_target_line
from .ops_render import (
    LC_OT_cancel_render,
    LC_OT_contact_sheet,
    LC_OT_render_queue,
    LC_OT_rerender_chunk,
)
from .ops_setup import LC_OT_setup_scene
from .ops_verify import LC_OT_verify_line
from .presets import LC_OT_preset_apply, LC_OT_preset_remove, LC_OT_preset_save
from .properties import status_lines


class LC_PT_panel(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Lyric Chunker"
    bl_label = "Lyric Chunker"

    def draw(self, context):
        layout = self.layout
        props = context.scene.lyric_chunker

        box = layout.box()
        box.label(text="Scene", icon='SCENE_DATA')
        box.operator(LC_OT_setup_scene.bl_idname, icon='ADD')
        box.prop(props, "template_object")
        if props.template_object is None:
            box.label(text="No template — defaults will be used", icon='ERROR')
        box.prop(props, "camera_object")

        box = layout.box()
        box.label(text="Lyrics", icon='OUTLINER_OB_FONT')
        row = box.row(align=True)
        row.prop(props, "lyrics_text", text="")
        row.operator(LC_OT_new_lyrics_text.bl_idname, text="", icon='ADD')
        if props.lyrics_text is None:
            box.prop(props, "line_text", text="")
        else:
            box.label(text="Edit lines in the Text Editor", icon='INFO')
            box.prop(props, "start_index")
        row = box.row(align=True)
        row.prop(props, "delimiter")
        row.prop(props, "line_number")
        box.prop(props, "force_uppercase")
        col = box.column(align=True)
        col.scale_y = 1.3
        op = col.operator(
            LC_OT_generate_chunks.bl_idname,
            text=f"Generate Line {props.line_number}"
            if props.lyrics_text is not None else "Generate Chunks",
            icon='MOD_BUILD',
        )
        op.all_lines = False
        if props.lyrics_text is not None:
            op = col.operator(
                LC_OT_generate_chunks.bl_idname,
                text="Generate All Lines",
                icon='MOD_BUILD',
            )
            op.all_lines = True

        box = layout.box()
        box.label(text="Timing", icon='TIME')
        box.prop(props, "srt_path", text="SRT")
        box.prop(props, "use_markers")

        box = layout.box()
        box.label(text="Style Presets", icon='PRESET')
        row = box.row()
        row.template_list(
            "LC_UL_style_presets", "", props, "style_presets",
            props, "style_preset_index", rows=2,
        )
        col = row.column(align=True)
        col.operator(LC_OT_preset_save.bl_idname, text="", icon='ADD')
        col.operator(LC_OT_preset_remove.bl_idname, text="", icon='REMOVE')
        col.operator(LC_OT_preset_apply.bl_idname, text="", icon='CHECKMARK')

        box = layout.box()
        box.label(text="Output", icon='OUTPUT')
        box.prop(props, "output_root", text="")
        box.prop(props, "zero_pad")
        if props.is_rendering:
            box.label(text=props.progress or "Rendering…", icon='RENDER_STILL')
            row = box.row()
            row.scale_y = 1.3
            row.operator(LC_OT_cancel_render.bl_idname, icon='CANCEL')
        else:
            target = get_target_line(context)
            col = box.column(align=True)
            col.scale_y = 1.3
            op = col.operator(
                LC_OT_render_queue.bl_idname,
                text=f"Render Line {target}",
                icon='RENDER_STILL',
            )
            op.all_lines = False
            op = col.operator(
                LC_OT_render_queue.bl_idname,
                text="Render All Lines",
                icon='RENDERLAYERS',
            )
            op.all_lines = True
            row = box.row(align=True)
            row.operator(LC_OT_rerender_chunk.bl_idname, icon='FILE_REFRESH')
            row = box.row(align=True)
            row.operator(LC_OT_verify_line.bl_idname, icon='CHECKMARK')
            row.operator(LC_OT_contact_sheet.bl_idname, icon='IMAGE_DATA')

        box = layout.box()
        icon = 'ERROR' if props.status_error else 'INFO'
        box.label(text="Status", icon=icon)
        for row_text in status_lines(props):
            box.label(text=row_text)
