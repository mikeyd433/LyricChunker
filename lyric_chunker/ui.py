"""Panel (3D Viewport sidebar > Lyric Chunker)."""

import textwrap

from bpy.types import Panel, UIList

from .ops_generate import (
    LC_OT_add_line,
    LC_OT_generate_chunks,
    LC_OT_import_lines,
    LC_OT_new_lyrics_text,
    LC_OT_remove_line,
    get_target_line,
)
from .ops_render import (
    LC_OT_cancel_render,
    LC_OT_contact_sheet,
    LC_OT_generate_comps,
    LC_OT_render_queue,
    LC_OT_rerender_chunk,
)
from .ops_setup import LC_OT_setup_scene
from .ops_timing import (
    LC_OT_clear_preview,
    LC_OT_preview_timing,
    LC_OT_tap_timing,
)
from .ops_verify import LC_OT_verify_line
from .presets import LC_OT_preset_apply, LC_OT_preset_remove, LC_OT_preset_save
from .properties import status_lines


class LC_UL_lyric_lines(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_prop, index):
        # Number-only label keeps most of the row width for the text;
        # the full selected line is drawn wrapped under the list.
        split = layout.split(factor=0.15)
        split.label(text=str(data.start_index + index))
        split.prop(item, "text", text="", emboss=False)


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
        row.prop(props, "line_text", text="", placeholder="Type a lyric line…")
        row.operator(LC_OT_add_line.bl_idname, text="", icon='ADD')
        has_list = len(props.lyric_lines) > 0
        if has_list:
            row = box.row()
            row.template_list(
                "LC_UL_lyric_lines", "", props, "lyric_lines",
                props, "lyric_line_index", rows=4,
            )
            col = row.column(align=True)
            col.operator(LC_OT_remove_line.bl_idname, text="", icon='REMOVE')
            index = props.lyric_line_index
            if 0 <= index < len(props.lyric_lines):
                full = props.lyric_lines[index].text
                view = box.column(align=True)
                view.scale_y = 0.85
                wrapped = textwrap.wrap(
                    f"Line {props.start_index + index}:  {full}", width=42
                ) or [""]
                for text_row in wrapped[:6]:
                    view.label(text=text_row)
        row = box.row(align=True)
        row.prop(props, "start_index")
        if not has_list:
            row.prop(props, "line_number")
        row = box.row(align=True)
        row.prop(props, "delimiter")
        box.prop(props, "force_uppercase")
        col = box.column(align=True)
        col.scale_y = 1.3
        multi = has_list or props.lyrics_text is not None
        op = col.operator(
            LC_OT_generate_chunks.bl_idname,
            text=f"Generate Line {props.line_number}" if multi
            else "Generate Chunks",
            icon='MOD_BUILD',
        )
        op.all_lines = False
        if multi:
            op = col.operator(
                LC_OT_generate_chunks.bl_idname,
                text="Generate All Lines",
                icon='MOD_BUILD',
            )
            op.all_lines = True
        row = box.row(align=True)
        row.prop(props, "lyrics_text", text="")
        row.operator(LC_OT_new_lyrics_text.bl_idname, text="", icon='ADD')
        row.operator(LC_OT_import_lines.bl_idname, text="", icon='IMPORT')

        box = layout.box()
        box.label(text="Timing", icon='TIME')
        box.prop(props, "srt_path", text="SRT")
        box.prop(props, "use_markers")
        row = box.row(align=True)
        if props.untimed_spread_unit == 'FRAMES':
            row.prop(props, "untimed_spread_frames")
        else:
            row.prop(props, "untimed_spread")
        row.prop(props, "untimed_spread_unit", text="")

        col = box.column(align=True)
        if props.is_tapping:
            col.label(text=props.progress, icon='REC')
            col.label(text="Enter/Click: tap · Backspace: undo · Esc: done")
        else:
            row = col.row(align=True)
            row.scale_y = 1.2
            op = row.operator(
                LC_OT_tap_timing.bl_idname,
                text=f"Tap Line {get_target_line(context)}", icon='REC',
            )
            op.all_lines = False
            op = row.operator(
                LC_OT_tap_timing.bl_idname, text="Tap All", icon='REC',
            )
            op.all_lines = True
            row = col.row(align=True)
            row.operator(LC_OT_preview_timing.bl_idname, icon='PLAY')
            row.operator(LC_OT_clear_preview.bl_idname, text="", icon='X')

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
            row = box.row()
            row.scale_y = 1.3
            row.operator(LC_OT_generate_comps.bl_idname, icon='NODETREE')

        box = layout.box()
        icon = 'ERROR' if props.status_error else 'INFO'
        box.label(text="Status", icon=icon)
        for row_text in status_lines(props):
            box.label(text=row_text)
