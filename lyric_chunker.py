bl_info = {
    "name": "Lyric Chunker",
    "author": "Mikey D",
    "version": (1, 0, 1),
    "blender": (4, 0, 0),
    "location": "3D Viewport > Sidebar (N) > Lyric Chunker",
    "description": "Generate styled 3D text split into syllable chunks and batch-render each as a transparent PNG",
    "category": "Object",
}

import os
import re
import textwrap

import bpy
from bpy.props import (
    BoolProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup

BACKUP_COLL_NAME = "_LyricBackups"
# Custom property stamped on collections this add-on creates, so that a
# user's own collection that happens to be named "Line5" is never treated
# as (or deleted as) a generated line.
LC_COLL_TAG = "lyric_chunker_line"
LINE_COLL_RE = re.compile(r"^Line0*(\d+)$")
CHUNK_NAME_RE = re.compile(r"^Line0*(\d+)_Chunk0*(\d+)$")
SOURCE_NAME_RE = re.compile(r"^Line0*(\d+)_source")

# Fraction of the incoming island's width that must overlap the current
# cluster's X-range to be considered part of the same glyph. Full overlap
# (i/j dots, colons, ?/! dots) is ~1.0; kerning bleed between adjacent
# letters is well under this.
GLYPH_OVERLAP_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Pure helpers (no bpy state) — kept bpy-free so they can be unit-tested
# outside Blender.
# ---------------------------------------------------------------------------

def parse_line(raw):
    """Parse a delimited lyric line into chunks.

    '-' splits syllables within a word, whitespace splits words, and '\\-'
    produces a literal hyphen. Returns (chunks, full_text) where chunks is
    the flat left-to-right list of chunk strings and full_text is the line
    with delimiters stripped (what the text object will contain).
    """
    words = []
    cur_word = []
    cur_syl = []

    def end_syllable():
        if cur_syl:
            cur_word.append("".join(cur_syl))
            cur_syl.clear()

    def end_word():
        end_syllable()
        if cur_word:
            words.append(list(cur_word))
            cur_word.clear()

    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw) and raw[i + 1] == "-":
            cur_syl.append("-")
            i += 2
        elif ch == "-":
            end_syllable()
            i += 1
        elif ch.isspace():
            end_word()
            i += 1
        else:
            cur_syl.append(ch)
            i += 1
    end_word()

    chunks = [syl for word in words for syl in word]
    full_text = " ".join("".join(word) for word in words)
    return chunks, full_text


def fmt_num(n, pad):
    return f"{n:02d}" if pad else str(n)


def line_coll_name(line_no, pad):
    return f"Line{fmt_num(line_no, pad)}"


def chunk_obj_name(line_no, chunk_no, pad):
    return f"Line{fmt_num(line_no, pad)}_Chunk{fmt_num(chunk_no, pad)}"


def cluster_spans(spans):
    """Group X-ranges into glyph clusters.

    spans: list of (min_x, max_x, payload). Islands whose X-range overlaps
    the running cluster by more than GLYPH_OVERLAP_THRESHOLD of their own
    width belong to the same glyph (dots of i/j, stacked punctuation).
    Returns a left-to-right list of payload lists.
    """
    items = sorted(spans, key=lambda s: (s[0], s[1]))
    clusters = []
    cur = None
    cur_max = None
    for mn, mx, payload in items:
        width = max(mx - mn, 1e-9)
        if cur is not None and (cur_max - mn) > GLYPH_OVERLAP_THRESHOLD * width:
            cur.append(payload)
            cur_max = max(cur_max, mx)
        else:
            cur = [payload]
            clusters.append(cur)
            cur_max = mx
    return clusters


# ---------------------------------------------------------------------------
# Scene helpers
# ---------------------------------------------------------------------------

def set_status(context, message, error=False):
    props = context.scene.lyric_chunker
    props.status = message
    props.status_error = error


def deselect_all(context):
    for obj in context.selected_objects:
        obj.select_set(False)


def line_collection_number(coll):
    """Line number if coll is a line collection this add-on made, else None.

    Requires the LC_COLL_TAG custom property; collections generated before
    the tag existed are recognized by containing their own chunk objects."""
    m = LINE_COLL_RE.match(coll.name)
    if not m:
        return None
    n = int(m.group(1))
    if coll.get(LC_COLL_TAG):
        return n
    for obj in coll.objects:
        cm = CHUNK_NAME_RE.match(obj.name)
        if cm and int(cm.group(1)) == n:
            return n
    return None


def find_line_collection(scene, line_no):
    for coll in scene.collection.children_recursive:
        if line_collection_number(coll) == line_no:
            return coll
    return None


def get_backup_collection(context):
    coll = bpy.data.collections.get(BACKUP_COLL_NAME)
    if coll is None:
        coll = bpy.data.collections.new(BACKUP_COLL_NAME)
    if coll.name not in context.scene.collection.children:
        context.scene.collection.children.link(coll)
    coll.hide_render = True
    coll.hide_viewport = True
    return coll


def remove_object_and_data(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        if isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)
        elif isinstance(data, bpy.types.Curve):
            bpy.data.curves.remove(data)


def remove_existing_line(context, line_no):
    """Delete a previously generated line (chunks + backup). Returns True if
    anything was removed."""
    removed = False
    coll = find_line_collection(context.scene, line_no)
    if coll is not None:
        for obj in list(coll.objects):
            remove_object_and_data(obj)
            removed = True
    backup = bpy.data.collections.get(BACKUP_COLL_NAME)
    if backup is not None:
        for obj in list(backup.objects):
            m = SOURCE_NAME_RE.match(obj.name)
            if m and int(m.group(1)) == line_no:
                remove_object_and_data(obj)
                removed = True
    return removed


def default_material():
    mat = bpy.data.materials.get("LyricChunker_White")
    if mat is None:
        mat = bpy.data.materials.new("LyricChunker_White")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.5
    return mat


def apply_style(context, text_obj, template):
    """Copy style + placement from the template object onto a new text
    object. Returns a warning string, or None if everything applied cleanly."""
    data = text_obj.data
    warning = None

    if template is None:
        data.extrude = 0.05
        data.bevel_depth = 0.01
        data.materials.append(default_material())
        text_obj.location = context.scene.cursor.location.copy()
        return "No template set — used default style at 3D cursor"

    if template.type == 'FONT':
        src = template.data
        if src.font is not None:
            data.font = src.font
        data.size = src.size
        data.shear = src.shear
        data.extrude = src.extrude
        data.bevel_depth = src.bevel_depth
        data.bevel_resolution = src.bevel_resolution
        data.resolution_u = src.resolution_u
        data.space_character = src.space_character
        data.space_word = src.space_word
        data.align_x = src.align_x
        data.align_y = src.align_y
    else:
        data.extrude = 0.05
        data.bevel_depth = 0.01
        warning = (
            f"Template '{template.name}' is not a text object — copied "
            "transform and materials only"
        )

    mats = [slot.material for slot in template.material_slots if slot.material]
    if mats:
        for mat in mats:
            data.materials.append(mat)
    else:
        data.materials.append(default_material())

    text_obj.location = template.location.copy()
    text_obj.rotation_euler = template.rotation_euler.copy()
    text_obj.scale = template.scale.copy()
    return warning


def island_span(obj):
    """Local-space X bounds of a mesh island. Local space keeps left-to-right
    ordering valid no matter how the object is rotated in the world."""
    xs = [corner[0] for corner in obj.bound_box]
    return min(xs), max(xs)


def collect_line_chunks(scene):
    """Map line number -> (collection, [chunk objects sorted by chunk #])."""
    lines = {}
    for coll in scene.collection.children_recursive:
        n = line_collection_number(coll)
        if n is None:
            continue
        entries = []
        for obj in coll.objects:
            cm = CHUNK_NAME_RE.match(obj.name)
            if cm and obj.type == 'MESH':
                entries.append((int(cm.group(2)), obj))
        if entries:
            entries.sort(key=lambda e: e[0])
            lines[n] = (coll, [obj for _, obj in entries])
    return lines


def get_target_line(context):
    """Line number the 'Render Line' button acts on: the active object's line
    if it is a chunk, else the last generated line, else the panel field."""
    obj = context.active_object
    if obj is not None:
        for coll in obj.users_collection:
            n = line_collection_number(coll)
            if n is not None:
                return n
    props = context.scene.lyric_chunker
    if props.last_line > 0:
        return props.last_line
    return props.line_number


def find_layer_collection(layer_coll, coll):
    if layer_coll.collection == coll:
        return layer_coll
    for child in layer_coll.children:
        found = find_layer_collection(child, coll)
        if found is not None:
            return found
    return None


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class LyricChunkerProps(PropertyGroup):
    line_text: StringProperty(
        name="Lyric Line",
        description=(
            "Delimited lyric line, e.g. 'sa-la-zar has my boots'. "
            "'-' splits syllables, space splits words, '\\-' is a literal hyphen"
        ),
        default="",
    )
    line_number: IntProperty(
        name="Line Number",
        description="Line number for naming; auto-increments after each generate",
        default=1,
        min=1,
    )
    force_uppercase: BoolProperty(
        name="Force Uppercase",
        description=(
            "Uppercase the text before generating (matches the existing "
            "visual style and avoids i/j dot islands)"
        ),
        default=True,
    )
    template_object: PointerProperty(
        name="Template",
        description=(
            "Styled text object to copy font, extrude, bevel, materials, "
            "scale, rotation, and placement from"
        ),
        type=bpy.types.Object,
    )
    output_root: StringProperty(
        name="Output Root",
        description="Renders save to <output root>/Line#/Line#_Chunk#.png",
        subtype='DIR_PATH',
        default="",
    )
    zero_pad: BoolProperty(
        name="Zero-pad Numbers",
        description="Name as Line01_Chunk01 instead of Line1_Chunk1",
        default=False,
    )
    status: StringProperty(default="Ready")
    status_error: BoolProperty(default=False)
    last_line: IntProperty(default=0)


# ---------------------------------------------------------------------------
# Generate operator
# ---------------------------------------------------------------------------

class LC_OT_generate_chunks(Operator):
    bl_idname = "lyric_chunker.generate_chunks"
    bl_label = "Generate Chunks"
    bl_description = (
        "Create styled 3D text for the line, split it into syllable chunks, "
        "and file them into a Line# collection"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def fail(self, context, message):
        set_status(context, message, error=True)
        self.report({'ERROR'}, message)
        return {'CANCELLED'}

    def execute(self, context):
        scene = context.scene
        props = scene.lyric_chunker

        chunks, full_text = parse_line(props.line_text)
        if not chunks:
            return self.fail(context, "Enter a lyric line first")
        if props.force_uppercase:
            chunks = [c.upper() for c in chunks]
            full_text = full_text.upper()

        line_no = props.line_number
        pad = props.zero_pad
        coll_name = line_coll_name(line_no, pad)

        # A foreign collection holding the target name would silently hijack
        # the naming (Blender appends .001) — refuse before touching anything.
        coll = find_line_collection(scene, line_no)
        existing = bpy.data.collections.get(coll_name)
        if existing is not None and existing is not coll:
            return self.fail(
                context,
                f"A collection named '{coll_name}' already exists but is "
                "not this line's collection — rename it or use a different "
                "line number",
            )

        if context.object is not None and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # One text object for the whole line so Blender handles kerning.
        curve = bpy.data.curves.new(f"{coll_name}_text", type='FONT')
        curve.body = full_text
        text_obj = bpy.data.objects.new(curve.name, curve)
        scene.collection.objects.link(text_obj)
        warning = apply_style(context, text_obj, props.template_object)
        context.view_layer.update()

        # Untouched backup of the styled text before any destructive step.
        # It keeps the copy's placeholder name until the old line is removed
        # below, so a failed run can't collide with the previous backup.
        backup_coll = get_backup_collection(context)
        source_obj = text_obj.copy()
        source_obj.data = text_obj.data.copy()
        source_obj.hide_render = True
        backup_coll.objects.link(source_obj)

        # Convert to mesh and separate into loose islands.
        deselect_all(context)
        text_obj.select_set(True)
        context.view_layer.objects.active = text_obj
        bpy.ops.object.convert(target='MESH')
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.separate(type='LOOSE')
        bpy.ops.object.mode_set(mode='OBJECT')
        islands = [o for o in context.selected_objects if o.type == 'MESH']

        # Cluster islands into glyphs, then map glyph counts onto chunks.
        clusters = cluster_spans(
            [island_span(o) + (o,) for o in islands]
        )
        expected = sum(len(c) for c in chunks)
        if len(clusters) != expected:
            for obj in islands:
                remove_object_and_data(obj)
            source_obj.name = f"{coll_name}_source"
            return self.fail(
                context,
                f"Line {line_no}: expected {expected} glyphs but found "
                f"{len(clusters)} clusters — ligatures or split glyphs "
                "(e.g. straight double quotes) break count mapping. The "
                f"source text is saved in {BACKUP_COLL_NAME}/{source_obj.name}"
                " and any existing line was left untouched",
            )

        # The new line is valid — only now replace the old one, so a failed
        # generate never costs previously placed chunks.
        replaced = remove_existing_line(context, line_no)
        source_obj.name = f"{coll_name}_source"

        chunk_objs = []
        cursor = 0
        for idx, chunk_text in enumerate(chunks, start=1):
            members = [
                obj
                for cluster in clusters[cursor:cursor + len(chunk_text)]
                for obj in cluster
            ]
            cursor += len(chunk_text)
            deselect_all(context)
            for obj in members:
                obj.select_set(True)
            context.view_layer.objects.active = members[0]
            if len(members) > 1:
                bpy.ops.object.join()
            joined = context.view_layer.objects.active
            joined.name = chunk_obj_name(line_no, idx, pad)
            joined.data.name = joined.name
            chunk_objs.append(joined)

        # Individual origins so each chunk can be transformed on its own.
        deselect_all(context)
        for obj in chunk_objs:
            obj.select_set(True)
        context.view_layer.objects.active = chunk_objs[0]
        bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_MASS', center='MEDIAN')

        if coll is None:
            coll = bpy.data.collections.new(coll_name)
            scene.collection.children.link(coll)
        else:
            coll.name = coll_name
        coll[LC_COLL_TAG] = True
        for obj in chunk_objs:
            for other in list(obj.users_collection):
                other.objects.unlink(obj)
            coll.objects.link(obj)

        props.last_line = line_no
        props.line_number = line_no + 1

        message = f"Line {line_no}: {len(chunk_objs)} chunks created"
        if replaced:
            message += " (replaced existing)"
        if warning:
            message += f" — {warning}"
            self.report({'WARNING'}, warning)
        set_status(context, message)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Render operator
# ---------------------------------------------------------------------------

class LC_OT_render_chunks(Operator):
    bl_idname = "lyric_chunker.render_chunks"
    bl_label = "Render Chunks"
    bl_description = "Render each chunk in isolation as a transparent 16-bit PNG"
    bl_options = {'REGISTER'}

    all_lines: BoolProperty(default=False, options={'HIDDEN'})

    def fail(self, context, message):
        set_status(context, message, error=True)
        self.report({'ERROR'}, message)
        return {'CANCELLED'}

    def execute(self, context):
        scene = context.scene
        props = scene.lyric_chunker

        if not props.output_root:
            return self.fail(context, "Set an output root folder first")
        out_root = bpy.path.abspath(props.output_root)
        if scene.camera is None:
            return self.fail(context, "Scene has no camera")

        lines = collect_line_chunks(scene)
        if not lines:
            return self.fail(context, "No Line# collections with chunks found")
        if self.all_lines:
            targets = sorted(lines)
        else:
            target = get_target_line(context)
            if target not in lines:
                return self.fail(context, f"No chunks found for Line {target}")
            targets = [target]

        notes = []
        if not scene.render.film_transparent:
            scene.render.film_transparent = True
            notes.append("enabled Film > Transparent")

        render = scene.render
        img = render.image_settings
        saved_output = {
            'filepath': render.filepath,
            'file_format': img.file_format,
            'color_mode': img.color_mode,
            'color_depth': img.color_depth,
        }
        all_chunks = [obj for _, objs in lines.values() for obj in objs]
        saved_hide = {obj: obj.hide_render for obj in all_chunks}
        template = props.template_object
        if template is not None and template not in saved_hide:
            saved_hide[template] = template.hide_render
        # Target collections must be renderable for the duration of the run.
        saved_coll = {}
        for line_no in targets:
            coll, _ = lines[line_no]
            layer_coll = find_layer_collection(context.view_layer.layer_collection, coll)
            was_excluded = layer_coll is not None and layer_coll.exclude
            saved_coll[coll] = (coll.hide_render, layer_coll, was_excluded)
            coll.hide_render = False
            if was_excluded:
                layer_coll.exclude = False

        wm = context.window_manager
        total = sum(len(lines[t][1]) for t in targets)
        done = 0
        wm.progress_begin(0, total)
        try:
            img.file_format = 'PNG'
            img.color_mode = 'RGBA'
            img.color_depth = '16'
            if template is not None:
                template.hide_render = True
            for line_no in targets:
                coll, objs = lines[line_no]
                folder = os.path.join(out_root, coll.name)
                os.makedirs(folder, exist_ok=True)
                for obj in objs:
                    for other in all_chunks:
                        other.hide_render = other is not obj
                    render.filepath = os.path.join(folder, f"{obj.name}.png")
                    bpy.ops.render.render(write_still=True)
                    done += 1
                    wm.progress_update(done)
        except Exception as exc:
            return self.fail(context, f"Render failed after {done}/{total}: {exc}")
        finally:
            for obj, hidden in saved_hide.items():
                obj.hide_render = hidden
            for coll, (hide, layer_coll, was_excluded) in saved_coll.items():
                coll.hide_render = hide
                if layer_coll is not None and was_excluded:
                    layer_coll.exclude = True
            render.filepath = saved_output['filepath']
            img.file_format = saved_output['file_format']
            try:
                img.color_mode = saved_output['color_mode']
                img.color_depth = saved_output['color_depth']
            except TypeError:
                pass  # prior format may not support the saved mode/depth combo
            wm.progress_end()

        if self.all_lines:
            message = f"Rendered {done}/{total} chunks across {len(targets)} lines to {out_root}"
        else:
            message = f"Rendered {done}/{total} chunks to {os.path.join(out_root, lines[targets[0]][0].name)}"
        if notes:
            message += f" ({'; '.join(notes)})"
        set_status(context, message)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class LC_PT_panel(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Lyric Chunker"
    bl_label = "Lyric Chunker"

    def draw(self, context):
        layout = self.layout
        props = context.scene.lyric_chunker

        box = layout.box()
        box.label(text="Line Input", icon='OUTLINER_OB_FONT')
        box.prop(props, "line_text", text="")
        box.prop(props, "line_number")
        box.prop(props, "force_uppercase")
        row = box.row()
        row.scale_y = 1.4
        row.operator(LC_OT_generate_chunks.bl_idname, icon='MOD_BUILD')

        box = layout.box()
        box.label(text="Style", icon='MATERIAL')
        box.prop(props, "template_object")
        if props.template_object is None:
            box.label(text="No template — defaults will be used", icon='ERROR')

        box = layout.box()
        box.label(text="Output", icon='OUTPUT')
        box.prop(props, "output_root", text="")
        box.prop(props, "zero_pad")
        target = get_target_line(context)
        op = box.operator(
            LC_OT_render_chunks.bl_idname,
            text=f"Render Line {target}",
            icon='RENDER_STILL',
        )
        op.all_lines = False
        op = box.operator(
            LC_OT_render_chunks.bl_idname,
            text="Render All Lines",
            icon='RENDERLAYERS',
        )
        op.all_lines = True

        box = layout.box()
        icon = 'ERROR' if props.status_error else 'INFO'
        box.label(text="Status", icon=icon)
        for row_text in textwrap.wrap(props.status, width=44)[:5]:
            box.label(text=row_text)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    LyricChunkerProps,
    LC_OT_generate_chunks,
    LC_OT_render_chunks,
    LC_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.lyric_chunker = PointerProperty(type=LyricChunkerProps)


def unregister():
    if hasattr(bpy.types.Scene, "lyric_chunker"):
        del bpy.types.Scene.lyric_chunker
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


if __name__ == "__main__":
    # Re-run friendly for the Text Editor test loop.
    try:
        unregister()
    except Exception:
        pass
    register()
