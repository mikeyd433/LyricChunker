"""Chunk generation via per-chunk Text objects (spec addendum §2).

One Text object per chunk, positioned by cumulative-prefix measurement.
No mesh conversion — extrude and bevel live on the Text objects, chunks
stay editable strings, and there is no island analysis to go wrong.
"""

import re

import bpy
from bpy.types import Operator
from mathutils import Vector

from .manifest import chunk_name, line_dirname
from .measure import copy_font_metrics, measure_layout
from .ops_setup import apply_house_style, default_material, load_house_font
from .properties import set_status
from .splitting import flat_chunks, parse_block, split_line

LINE_COLL_RE = re.compile(r"^Line0*(\d+)$")
CHUNK_OBJ_RE = re.compile(r"^Line0*(\d+)_Chunk0*(\d+)")


def find_line_collection(scene, line_no):
    for coll in scene.collection.children_recursive:
        m = LINE_COLL_RE.match(coll.name)
        if m and int(m.group(1)) == line_no:
            return coll
    return None


def collect_line_chunks(scene):
    """Map line number -> (collection, [chunk objects sorted by chunk #])."""
    lines = {}
    for coll in scene.collection.children_recursive:
        m = LINE_COLL_RE.match(coll.name)
        if not m:
            continue
        entries = []
        for obj in coll.objects:
            cm = CHUNK_OBJ_RE.match(obj.name)
            if cm and obj.type == 'FONT':
                entries.append((int(cm.group(2)), obj))
        if entries:
            entries.sort(key=lambda e: e[0])
            lines[int(m.group(1))] = (coll, [obj for _, obj in entries])
    return lines


def get_target_line(context):
    """Line the single-line buttons act on: the active object's line if it
    is a chunk, else the last generated line, else the panel field."""
    obj = context.active_object
    if obj is not None:
        for coll in obj.users_collection:
            m = LINE_COLL_RE.match(coll.name)
            if m:
                return int(m.group(1))
    props = context.scene.lyric_chunker
    if props.last_line > 0:
        return props.last_line
    return props.line_number


def remove_object_and_data(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        if isinstance(data, bpy.types.Curve):
            bpy.data.curves.remove(data)
        elif isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)


def remove_existing_line(context, line_no):
    coll = find_line_collection(context.scene, line_no)
    if coll is None:
        return False
    for obj in list(coll.objects):
        remove_object_and_data(obj)
    # Remove the collection too, or the regenerated line would land in a
    # 'Line1.001' collection that the name-based lookups can't see.
    bpy.data.collections.remove(coll)
    return True


def apply_template_style(text_data, template):
    """Copy font metrics and materials from the template onto a chunk's
    text datablock. Alignment is NOT copied — chunks are LEFT/BASELINE
    and the template's alignment is folded into the measured base offset."""
    if template is not None and template.type == 'FONT':
        copy_font_metrics(template.data, text_data)
        mats = [s.material for s in template.material_slots if s.material]
        for mat in mats or [default_material()]:
            text_data.materials.append(mat)
    else:
        apply_house_style(text_data)
        font = load_house_font()
        if font is not None:
            text_data.font = font
        text_data.materials.append(default_material())
    text_data.align_x = 'LEFT'
    text_data.align_y = 'BOTTOM_BASELINE'


def chunk_local_position(base, offset_x):
    return (base[0] + offset_x, base[1])


def place_chunk(obj, template, cursor_location, local_x, local_y):
    if template is not None:
        obj.location = template.matrix_world @ Vector((local_x, local_y, 0.0))
        obj.rotation_euler = template.rotation_euler.copy()
        obj.scale = template.scale.copy()
    else:
        obj.location = cursor_location + Vector((local_x, local_y, 0.0))


def generate_line(context, line_no, raw_text, words, props):
    """Create the per-chunk Text objects for one line. Returns
    (chunk_objects, replaced)."""
    scene = context.scene
    template = props.template_object
    pad = props.zero_pad

    replaced = remove_existing_line(context, line_no)
    offsets, base = measure_layout(context, template, words)
    chunks = flat_chunks(words)

    coll = bpy.data.collections.new(line_dirname(line_no, pad))
    scene.collection.children.link(coll)
    coll["lc_line"] = line_no
    coll["lc_text_raw"] = raw_text
    coll["lc_delimiter"] = props.delimiter

    cursor = scene.cursor.location.copy()
    objs = []
    for i, (text, offset_x) in enumerate(zip(chunks, offsets), start=1):
        name = chunk_name(line_no, i, pad)
        curve = bpy.data.curves.new(name, type='FONT')
        curve.body = text
        apply_template_style(curve, template)
        obj = bpy.data.objects.new(name, curve)
        local_x, local_y = chunk_local_position(base, offset_x)
        place_chunk(obj, template, cursor, local_x, local_y)
        obj["lc_line"] = line_no
        obj["lc_chunk"] = i
        obj["lc_text"] = text
        obj["lc_offset_x"] = offset_x
        obj["lc_local_x"] = local_x
        obj["lc_local_y"] = local_y
        coll.objects.link(obj)
        objs.append(obj)
    return objs, replaced


def parse_input_lines(props):
    """Lines to generate from the panel state, in priority order: the
    panel lyric list, else an attached lyrics text block (§5.3), else
    the single-line field. Returns (lines, warnings) with lines as
    (line_no, raw, words) tuples."""
    if len(props.lyric_lines):
        lines = []
        warnings = []
        # List rows map 1:1 to numbers (start_index + row) so the panel
        # labels, generate targets, and SRT mapping all agree — an empty
        # row is skipped but keeps its number.
        for row, item in enumerate(props.lyric_lines):
            number = props.start_index + row
            raw = item.text.strip()
            if not raw:
                warnings.append(f"Line {number}: empty row — skipped")
                continue
            words, w = split_line(raw, props.delimiter)
            warnings.extend(f"Line {number}: {msg}" for msg in w)
            if not words:
                warnings.append(f"Line {number}: no chunks after splitting — skipped")
                continue
            lines.append((number, raw, words))
    elif props.lyrics_text is not None:
        text = props.lyrics_text.as_string()
        lines, warnings = parse_block(text, props.delimiter, props.start_index)
    else:
        words, warnings = split_line(props.line_text, props.delimiter)
        lines = [(props.line_number, props.line_text.strip(), words)] if words else []
    if props.force_uppercase:
        lines = [
            (no, raw.upper(), [[c.upper() for c in word] for word in words])
            for no, raw, words in lines
        ]
    return lines, warnings


class LC_OT_generate_chunks(Operator):
    bl_idname = "lyric_chunker.generate_chunks"
    bl_label = "Generate Chunks"
    bl_description = (
        "Create one styled Text object per chunk, positioned by prefix "
        "measurement, filed into a Line# collection"
    )
    bl_options = {'REGISTER', 'UNDO'}

    all_lines: bpy.props.BoolProperty(default=False, options={'HIDDEN'})

    def fail(self, context, message):
        set_status(context, message, error=True)
        self.report({'ERROR'}, message)
        return {'CANCELLED'}

    def execute(self, context):
        props = context.scene.lyric_chunker
        if not props.delimiter:
            return self.fail(context, "Delimiter is empty")
        if props.template_object is None:
            self.report(
                {'WARNING'},
                "No template set — default style at the 3D cursor "
                "(pick one, or run Set Up Scene)",
            )

        lines, warnings = parse_input_lines(props)
        if not lines:
            return self.fail(
                context,
                "Nothing to generate — enter a lyric line or pick a lyrics text",
            )
        if not self.all_lines:
            if len(props.lyric_lines) or props.lyrics_text is not None:
                wanted = props.line_number
                lines = [entry for entry in lines if entry[0] == wanted]
                if not lines:
                    return self.fail(
                        context,
                        f"Line {wanted} is not in the lyrics "
                        f"(rows start at {props.start_index})",
                    )
            # Single-line field mode already targets props.line_number.

        if context.object is not None and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        total_chunks = 0
        replaced_any = False
        for line_no, raw, words in lines:
            objs, replaced = generate_line(context, line_no, raw, words, props)
            total_chunks += len(objs)
            replaced_any = replaced_any or replaced
            props.last_line = line_no

        if (not len(props.lyric_lines) and props.lyrics_text is None
                and not self.all_lines):
            props.line_number = lines[-1][0] + 1

        message = f"Generated {len(lines)} line(s), {total_chunks} chunks"
        if replaced_any:
            message += " (replaced existing)"
        if warnings:
            message += f" — {'; '.join(warnings[:3])}"
            for w in warnings:
                self.report({'WARNING'}, w)
        set_status(context, message, error=False)
        return {'FINISHED'}


class LC_OT_add_line(Operator):
    bl_idname = "lyric_chunker.add_line"
    bl_label = "Add Line"
    bl_description = (
        "Add the typed lyric line to the list below, numbered after the "
        "last entry"
    )

    def execute(self, context):
        props = context.scene.lyric_chunker
        raw = props.line_text.strip()
        if not raw:
            set_status(context, "Type a lyric line first", error=True)
            self.report({'ERROR'}, "Type a lyric line first")
            return {'CANCELLED'}
        words, warnings = split_line(raw, props.delimiter)
        if not words:
            set_status(context, "Line has no chunks after splitting", error=True)
            self.report({'ERROR'}, "Line has no chunks after splitting")
            return {'CANCELLED'}
        item = props.lyric_lines.add()
        item.text = raw
        props.lyric_line_index = len(props.lyric_lines) - 1
        props.line_text = ""
        number = props.start_index + len(props.lyric_lines) - 1
        message = f"Added Line {number}: {raw}"
        if warnings:
            message += f" — {'; '.join(warnings)}"
        set_status(context, message)
        return {'FINISHED'}


class LC_OT_remove_line(Operator):
    bl_idname = "lyric_chunker.remove_line"
    bl_label = "Remove Line"
    bl_description = (
        "Remove the selected line from the list (later rows shift down a "
        "number, so regenerate them if already generated)"
    )

    def execute(self, context):
        props = context.scene.lyric_chunker
        index = props.lyric_line_index
        if not (0 <= index < len(props.lyric_lines)):
            return {'CANCELLED'}
        removed = props.lyric_lines[index].text
        props.lyric_lines.remove(index)
        props.lyric_line_index = min(index, len(props.lyric_lines) - 1)
        set_status(context, f"Removed line: {removed}")
        return {'FINISHED'}


class LC_OT_import_lines(Operator):
    bl_idname = "lyric_chunker.import_lines"
    bl_label = "Import Rows"
    bl_description = (
        "Append every non-empty row of the picked lyrics text block to "
        "the line list (paste a whole song in the Text Editor, then pull "
        "it in here)"
    )

    def execute(self, context):
        props = context.scene.lyric_chunker
        if props.lyrics_text is None:
            set_status(context, "Pick a lyrics text block to import from", error=True)
            self.report({'ERROR'}, "Pick a lyrics text block to import from")
            return {'CANCELLED'}
        added = 0
        for raw in props.lyrics_text.as_string().splitlines():
            if raw.strip():
                item = props.lyric_lines.add()
                item.text = raw.strip()
                added += 1
        if added:
            props.lyric_line_index = len(props.lyric_lines) - 1
        set_status(
            context,
            f"Imported {added} line(s) from '{props.lyrics_text.name}'",
        )
        return {'FINISHED'}


class LC_OT_new_lyrics_text(Operator):
    bl_idname = "lyric_chunker.new_lyrics_text"
    bl_label = "New Lyrics Text"
    bl_description = (
        "Create a text datablock for multi-line lyrics (edit it in the "
        "Text Editor, one delimited line per row)"
    )

    def execute(self, context):
        props = context.scene.lyric_chunker
        text = bpy.data.texts.new("Lyrics")
        text.write("Some|thing wick|ed this way comes\n")
        props.lyrics_text = text
        set_status(
            context,
            f"Created '{text.name}' — edit it in the Text Editor, one line per row",
        )
        return {'FINISHED'}
