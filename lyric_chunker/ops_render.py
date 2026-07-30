"""Render pipeline (spec addendum §3): modal job queue, render-settings
assertions, manifest writing, single-chunk re-render (§5.1), and the
contact sheet preview (§5.4).

The per-chunk render strategy is isolated in
:func:`render_single_chunk` (§3.2) so the v1.5 Object-Index single-pass
strategy (§6.4) is a one-function swap.
"""

import datetime
import glob
import os

import bpy
from bpy.types import Operator
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from .manifest import (
    ADDON_ID,
    ADDON_VERSION,
    build_chunk_entry,
    build_manifest,
    manifest_filename,
    read_manifest,
    seconds_to_frame,
    write_manifest,
)
from .comp.settings_gen import generate_line_setting
from .ops_generate import (
    collect_line_chunks,
    find_line_collection,
    get_target_line,
)
from .properties import active_camera, set_status
from .timing_markers import match_markers, resolve_line_timing
from .timing_srt import SrtParseError, distribute, entry_for_line, parse_srt


def effective_fps(scene):
    return scene.render.fps / scene.render.fps_base


def now_utc_iso():
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Render settings (§3.3)
# ---------------------------------------------------------------------------

class RenderSettingsGuard:
    """Save/restore everything the batch mutates. Restore is tolerant of
    format/mode combinations the prior format did not support."""

    def __init__(self, scene):
        self.scene = scene
        render = scene.render
        img = render.image_settings
        self.saved = {
            "filepath": render.filepath,
            "file_format": img.file_format,
            "color_mode": img.color_mode,
            "color_depth": img.color_depth,
            "film_transparent": render.film_transparent,
            "resolution_percentage": render.resolution_percentage,
        }

    def restore(self):
        render = self.scene.render
        img = render.image_settings
        render.filepath = self.saved["filepath"]
        render.film_transparent = self.saved["film_transparent"]
        render.resolution_percentage = self.saved["resolution_percentage"]
        img.file_format = self.saved["file_format"]
        try:
            img.color_mode = self.saved["color_mode"]
            img.color_depth = self.saved["color_depth"]
        except TypeError:
            pass


def assert_render_settings(scene):
    """Force the §3.3 invariants before every batch — silently losing
    film_transparent ruins an entire batch invisibly. Returns notes for
    anything that had to be corrected."""
    notes = []
    render = scene.render
    img = render.image_settings
    if not render.film_transparent:
        render.film_transparent = True
        notes.append("enabled Film > Transparent")
    if img.file_format != 'PNG':
        img.file_format = 'PNG'
        notes.append("set output format to PNG")
    if img.color_mode != 'RGBA':
        img.color_mode = 'RGBA'
        notes.append("set color mode to RGBA")
    if img.color_depth != '16':
        img.color_depth = '16'
        notes.append("set color depth to 16-bit")
    return notes


class ChunkVisibilityGuard:
    """Hide/restore chunk objects, the template, and target collections'
    renderability for the duration of a batch."""

    def __init__(self, context, lines, targets, template):
        self.saved_hide = {}
        self.saved_coll = {}
        self.template = template
        all_chunks = [obj for _, objs in lines.values() for obj in objs]
        for obj in all_chunks:
            self.saved_hide[obj] = obj.hide_render
        if template is not None and template not in self.saved_hide:
            self.saved_hide[template] = template.hide_render
            template.hide_render = True
        for line_no in targets:
            coll, _ = lines[line_no]
            layer_coll = _find_layer_collection(
                context.view_layer.layer_collection, coll
            )
            was_excluded = layer_coll is not None and layer_coll.exclude
            self.saved_coll[coll] = (coll.hide_render, layer_coll, was_excluded)
            coll.hide_render = False
            if was_excluded:
                layer_coll.exclude = False
        self.all_chunks = all_chunks

    def restore(self):
        for obj, hidden in self.saved_hide.items():
            try:
                obj.hide_render = hidden
            except ReferenceError:
                pass
        for coll, (hide, layer_coll, was_excluded) in self.saved_coll.items():
            try:
                coll.hide_render = hide
                if layer_coll is not None and was_excluded:
                    layer_coll.exclude = True
            except ReferenceError:
                pass


def _find_layer_collection(layer_coll, coll):
    if layer_coll.collection == coll:
        return layer_coll
    for child in layer_coll.children:
        found = _find_layer_collection(child, coll)
        if found is not None:
            return found
    return None


# ---------------------------------------------------------------------------
# Render strategy (§3.2) — the §6.4 single-pass swap point
# ---------------------------------------------------------------------------

def render_single_chunk(scene, obj, filepath, all_chunk_objs):
    """Render one chunk in isolation to ``filepath``."""
    for other in all_chunk_objs:
        other.hide_render = other is not obj
    scene.render.filepath = filepath
    bpy.ops.render.render(write_still=True)


# ---------------------------------------------------------------------------
# Timing (§4)
# ---------------------------------------------------------------------------

def compute_timing(context, lines, targets):
    """Resolve per-chunk timing for the target lines.

    Returns ``(timing, warnings)`` with ``timing`` mapping
    ``line_no -> (chunk_times, line_span, line_source)``. Raises
    SrtParseError (with a readable message) on a malformed SRT file.
    """
    props = context.scene.lyric_chunker
    warnings = []

    entries = None
    if props.srt_path.strip():
        path = bpy.path.abspath(props.srt_path)
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                entries = parse_srt(fh.read())
        except OSError as exc:
            raise SrtParseError(f"cannot read SRT file: {exc}") from exc
        if len(entries) < max(targets):
            warnings.append(
                f"SRT has {len(entries)} entries but line "
                f"{max(targets)} was requested — unmatched lines fall back "
                "to markers or 'none'"
            )

    marker_times = {}
    if props.use_markers and context.scene.timeline_markers:
        chunk_keys = []
        for line_no in targets:
            _, objs = lines[line_no]
            chunk_keys.extend((line_no, int(o["lc_chunk"])) for o in objs)
        markers = [(m.name, m.frame) for m in context.scene.timeline_markers]
        marker_times, marker_warnings = match_markers(
            markers, chunk_keys, effective_fps(context.scene)
        )
        warnings.extend(marker_warnings)

    timing = {}
    for line_no in targets:
        _, objs = lines[line_no]
        chunk_texts = [str(o["lc_text"]) for o in objs]
        srt_entry = entry_for_line(entries, line_no) if entries else None
        timing[line_no] = resolve_line_timing(
            line_no, chunk_texts, marker_times, srt_entry, distribute
        )
    return timing, warnings


# ---------------------------------------------------------------------------
# Manifest gathering (§1)
# ---------------------------------------------------------------------------

def _pixel_resolution(scene):
    pct = scene.render.resolution_percentage / 100.0
    return (
        max(1, round(scene.render.resolution_x * pct)),
        max(1, round(scene.render.resolution_y * pct)),
    )


def chunk_bbox_px(scene, camera, obj):
    """Pixel bbox [x_min, y_min, x_max, y_max], origin bottom-left,
    from the object's bound_box corners projected into camera view."""
    res_x, res_y = _pixel_resolution(scene)
    xs, ys = [], []
    for corner in obj.bound_box:
        world = obj.matrix_world @ Vector(corner)
        co = world_to_camera_view(scene, camera, world)
        xs.append(co.x * res_x)
        ys.append(co.y * res_y)
    return [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]


def chunk_manifest_entry(context, obj, filename, chunk_time):
    scene = context.scene
    props = scene.lyric_chunker
    camera = active_camera(context)
    template = props.template_object

    world_pos = obj.matrix_world.translation
    screen = world_to_camera_view(scene, camera, world_pos)

    manual_offset = 0.0
    if template is not None and "lc_local_x" in obj:
        local = template.matrix_world.inverted() @ obj.location
        manual_offset = local.x - float(obj["lc_local_x"])

    seconds, source = chunk_time
    fps = scene.render.fps
    fps_base = scene.render.fps_base
    return build_chunk_entry(
        index=int(obj["lc_chunk"]),
        name=obj.name,
        text=str(obj["lc_text"]),
        filename=filename,
        world_position=tuple(world_pos),
        screen_position=(screen.x, screen.y),
        bbox_px=chunk_bbox_px(scene, camera, obj),
        offset_x=float(obj.get("lc_offset_x", 0.0)),
        manual_offset_x=manual_offset,
        start_seconds=seconds,
        start_frame=seconds_to_frame(seconds, fps, fps_base),
        timing_source=source,
    )


def gather_line_manifest(context, line_no, coll, objs, completed, timing_entry,
                         verification=None):
    """Build the manifest document for one line. ``completed`` is the set
    of chunk indices whose PNGs exist — on cancel or error this writes a
    partial manifest with the chunks that did complete (§3.1)."""
    scene = context.scene
    props = scene.lyric_chunker
    camera = active_camera(context)
    chunk_times, line_span, line_source = timing_entry

    render = scene.render
    render_block = {
        "engine": render.engine,
        "resolution_x": render.resolution_x,
        "resolution_y": render.resolution_y,
        "resolution_percentage": render.resolution_percentage,
        "fps": render.fps,
        "fps_base": round(render.fps_base, 6),
        "film_transparent": render.film_transparent,
        "color_depth": render.image_settings.color_depth,
        "file_format": render.image_settings.file_format,
    }
    project_block = {
        "blend_file": os.path.basename(bpy.data.filepath) or "",
        "scene": scene.name,
        "camera": camera.name if camera else "",
        "style_preset": props.active_preset,
        "template_object": props.template_object.name if props.template_object else "",
    }
    start_s, end_s = line_span
    line_block = {
        "index": line_no,
        "text_raw": str(coll.get("lc_text_raw", "")),
        "delimiter": str(coll.get("lc_delimiter", props.delimiter)),
        "output_dir": coll.name,
        "start_seconds": None if start_s is None else round(start_s, 4),
        "end_seconds": None if end_s is None else round(end_s, 4),
        "timing_source": line_source,
    }
    chunks = []
    for obj, chunk_time in zip(objs, chunk_times):
        index = int(obj["lc_chunk"])
        if index not in completed:
            continue
        chunks.append(
            chunk_manifest_entry(context, obj, f"{obj.name}.png", chunk_time)
        )
    generator = {
        "addon": ADDON_ID,
        "addon_version": ADDON_VERSION,
        "blender_version": bpy.app.version_string.split()[0],
    }
    return build_manifest(
        generator,
        project_block,
        render_block,
        line_block,
        chunks,
        verification=verification,
        rendered_at=now_utc_iso(),
    )


# ---------------------------------------------------------------------------
# Modal render queue (§3.1)
# ---------------------------------------------------------------------------

class LC_OT_render_queue(Operator):
    bl_idname = "lyric_chunker.render_queue"
    bl_label = "Render Chunks"
    bl_description = (
        "Render each chunk in isolation as a transparent 16-bit PNG and "
        "write a JSON manifest per line, via a cancellable modal queue"
    )
    bl_options = {'REGISTER'}

    all_lines: bpy.props.BoolProperty(default=False, options={'HIDDEN'})

    _timer = None

    def fail(self, context, message):
        set_status(context, message, error=True)
        self.report({'ERROR'}, message)
        return {'CANCELLED'}

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        scene = context.scene
        props = scene.lyric_chunker
        if props.is_rendering:
            return self.fail(context, "A render batch is already running")
        if not props.output_root:
            return self.fail(context, "Set an output root folder first")
        if active_camera(context) is None:
            return self.fail(
                context, "No camera — pick one or run Set Up Scene"
            )

        self.out_root = bpy.path.abspath(props.output_root)
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

        try:
            self.timing, timing_warnings = compute_timing(context, lines, targets)
        except SrtParseError as exc:
            return self.fail(context, f"SRT import failed: {exc}")
        for w in timing_warnings:
            self.report({'WARNING'}, w)

        self.jobs = []
        for line_no in targets:
            coll, objs = lines[line_no]
            folder = os.path.join(self.out_root, coll.name)
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as exc:
                return self.fail(context, f"Output path not writable: {exc}")
            for obj in objs:
                self.jobs.append({
                    "line_no": line_no,
                    "coll": coll,
                    "obj": obj,
                    "chunk": int(obj["lc_chunk"]),
                    "filepath": os.path.join(folder, f"{obj.name}.png"),
                })

        self.lines = lines
        self.targets = targets
        self.job_index = 0
        self.completed = {line_no: set() for line_no in targets}
        self.written = set()
        self.notes = assert_render_settings(scene)
        self.guard = RenderSettingsGuard(scene)
        self.visibility = ChunkVisibilityGuard(
            context, lines, targets, props.template_object
        )
        props.is_rendering = True
        props.render_cancel = False
        props.progress = f"Starting — 0/{len(self.jobs)}"

        wm = context.window_manager
        wm.progress_begin(0, len(self.jobs))
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        props = context.scene.lyric_chunker
        if event.type == 'ESC':
            props.render_cancel = True
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        if props.render_cancel:
            self.finish(context, f"Cancelled after {self.job_index}/{len(self.jobs)} chunks")
            return {'CANCELLED'}

        if self.job_index >= len(self.jobs):
            self.finish(
                context,
                f"Rendered {len(self.jobs)} chunks across "
                f"{len(self.targets)} line(s) to {self.out_root}",
            )
            return {'FINISHED'}

        job = self.jobs[self.job_index]
        line_objs = self.lines[job["line_no"]][1]
        props.progress = (
            f"Rendering Line {job['line_no']}, chunk {job['chunk']} of "
            f"{len(line_objs)} — {self.job_index + 1}/{len(self.jobs)}"
        )
        try:
            render_single_chunk(
                context.scene, job["obj"], job["filepath"],
                self.visibility.all_chunks,
            )
        except Exception as exc:
            self.finish(
                context,
                f"Render failed at Line {job['line_no']} chunk "
                f"{job['chunk']}: {exc}",
                error=True,
            )
            return {'CANCELLED'}

        self.completed[job["line_no"]].add(job["chunk"])
        self.job_index += 1
        context.window_manager.progress_update(self.job_index)
        if len(self.completed[job["line_no"]]) == len(line_objs):
            self.write_line_manifest(context, job["line_no"])
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'RUNNING_MODAL'}

    def write_line_manifest(self, context, line_no):
        coll, objs = self.lines[line_no]
        doc = gather_line_manifest(
            context, line_no, coll, objs,
            self.completed[line_no], self.timing[line_no],
        )
        path = os.path.join(
            self.out_root, coll.name,
            manifest_filename(line_no, context.scene.lyric_chunker.zero_pad),
        )
        write_manifest(path, doc)
        self.written.add(line_no)

    def finish(self, context, message, error=False):
        # Partial manifests for lines that completed some chunks (§3.1).
        for line_no in self.targets:
            if line_no not in self.written and self.completed[line_no]:
                try:
                    self.write_line_manifest(context, line_no)
                except OSError:
                    pass
        props = context.scene.lyric_chunker
        self.visibility.restore()
        self.guard.restore()
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        props.is_rendering = False
        props.render_cancel = False
        props.progress = ""
        if self.notes:
            message += f" ({'; '.join(self.notes)})"
        set_status(context, message, error=error)
        if error:
            self.report({'ERROR'}, message)


class LC_OT_cancel_render(Operator):
    bl_idname = "lyric_chunker.cancel_render"
    bl_label = "Cancel"
    bl_description = "Stop the batch cleanly after the in-flight render"

    def execute(self, context):
        context.scene.lyric_chunker.render_cancel = True
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Single-chunk re-render (§5.1)
# ---------------------------------------------------------------------------

class LC_OT_rerender_chunk(Operator):
    bl_idname = "lyric_chunker.rerender_chunk"
    bl_label = "Re-render Chunk"
    bl_description = (
        "Re-render one chunk without regenerating the line: overwrites its "
        "PNG and updates its manifest entry (select a chunk object first)"
    )

    def fail(self, context, message):
        set_status(context, message, error=True)
        self.report({'ERROR'}, message)
        return {'CANCELLED'}

    def execute(self, context):
        scene = context.scene
        props = scene.lyric_chunker
        obj = context.active_object
        if obj is None or "lc_chunk" not in obj:
            return self.fail(
                context, "Select a generated chunk object to re-render"
            )
        if not props.output_root:
            return self.fail(context, "Set an output root folder first")
        if active_camera(context) is None:
            return self.fail(context, "No camera")

        line_no = int(obj["lc_line"])
        chunk_no = int(obj["lc_chunk"])
        # The chunk is live editable text (§2.2): a typo fix is an edit to
        # the body, so pick up the current string before rendering.
        obj["lc_text"] = obj.data.body
        coll = find_line_collection(scene, line_no)
        if coll is None:
            return self.fail(context, f"Line {line_no} collection not found")
        out_root = bpy.path.abspath(props.output_root)
        manifest_path = os.path.join(
            out_root, coll.name, manifest_filename(line_no, props.zero_pad)
        )
        if not os.path.exists(manifest_path):
            return self.fail(
                context,
                f"No manifest at {manifest_path} — render the line once first",
            )
        try:
            doc = read_manifest(manifest_path)
        except (ValueError, OSError) as exc:
            return self.fail(context, f"Cannot read manifest: {exc}")

        entry_index = next(
            (i for i, c in enumerate(doc["chunks"]) if c["index"] == chunk_no),
            None,
        )

        lines = collect_line_chunks(scene)
        notes = assert_render_settings(scene)
        guard = RenderSettingsGuard(scene)
        visibility = ChunkVisibilityGuard(
            context, lines, [line_no], props.template_object
        )
        filepath = os.path.join(out_root, coll.name, f"{obj.name}.png")
        try:
            render_single_chunk(scene, obj, filepath, visibility.all_chunks)
        except Exception as exc:
            return self.fail(context, f"Re-render failed: {exc}")
        finally:
            visibility.restore()
            guard.restore()

        # Keep the stored timing; refresh geometry-derived fields.
        if entry_index is not None:
            old = doc["chunks"][entry_index]
            chunk_time = (old.get("start_seconds"), old.get("timing_source", "none"))
        else:
            chunk_time = (None, "none")
        new_entry = chunk_manifest_entry(context, obj, f"{obj.name}.png", chunk_time)
        if entry_index is not None:
            doc["chunks"][entry_index] = new_entry
        else:
            doc["chunks"].append(new_entry)
            doc["chunks"].sort(key=lambda c: c["index"])
        doc["rendered_at"] = now_utc_iso()
        write_manifest(manifest_path, doc)

        message = f"Re-rendered {obj.name}"
        if notes:
            message += f" ({'; '.join(notes)})"
        set_status(context, message)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Fusion comp generation (§6) — same generator as scripts/generate_comp.py,
# run against the output root without leaving Blender.
# ---------------------------------------------------------------------------

class LC_OT_generate_comps(Operator):
    bl_idname = "lyric_chunker.generate_comps"
    bl_label = "Generate Fusion Comps"
    bl_description = (
        "Write a pasteable Fusion node graph (Line#.setting) next to every "
        "rendered line manifest in the output root — open one in a text "
        "editor, copy all, and paste into Resolve's Fusion node area"
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
        manifests = sorted(glob.glob(os.path.join(out_root, "Line*", "Line*.json")))
        if not manifests:
            return self.fail(
                context,
                f"No Line#.json manifests under {out_root} — render lines first",
            )

        written = 0
        warned = []
        for path in manifests:
            try:
                doc = read_manifest(path)
            except (ValueError, OSError) as exc:
                warned.append(f"{os.path.basename(path)}: {exc}")
                continue
            folder = os.path.dirname(path)
            text, warnings = generate_line_setting(
                doc, folder,
                untimed_seconds=props.untimed_spread,
                untimed_frames=(
                    props.untimed_spread_frames
                    if props.untimed_spread_unit == 'FRAMES' else None
                ),
            )
            warned.extend(warnings)
            setting_path = os.path.splitext(path)[0] + ".setting"
            try:
                with open(setting_path, "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError as exc:
                return self.fail(context, f"Cannot write {setting_path}: {exc}")
            written += 1

        message = (
            f"Wrote {written} .setting file(s) — open in a text editor, copy "
            "all, paste into Fusion, wire the last Merge to MediaOut"
        )
        if warned:
            message += f" — {len(warned)} warning(s), see console"
            for w in warned:
                self.report({'WARNING'}, w)
        set_status(context, message, error=written == 0)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Contact sheet (§5.4)
# ---------------------------------------------------------------------------

CONTACT_SHEET_IMAGE = "LC_ContactSheet"
CONTACT_SHEET_WIDTH = 480


def load_pixels(path):
    """Load an image file as a float32 (h, w, 4) array, bottom-up rows."""
    import numpy as np

    img = bpy.data.images.load(path)
    try:
        w, h = img.size
        pixels = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    finally:
        bpy.data.images.remove(img)
    return pixels


def alpha_over(base, top):
    """Straight-alpha over-composite: top over base, in place on base."""
    import numpy as np

    top_a = top[..., 3:4]
    base_a = base[..., 3:4]
    out_a = top_a + base_a * (1.0 - top_a)
    prem = top[..., :3] * top_a + base[..., :3] * base_a * (1.0 - top_a)
    base[..., :3] = prem / np.maximum(out_a, 1e-6)
    base[..., 3:4] = out_a
    return base


class LC_OT_contact_sheet(Operator):
    bl_idname = "lyric_chunker.contact_sheet"
    bl_label = "Contact Sheet"
    bl_description = (
        "Low-resolution pass over all chunks, composited into one preview "
        "image — catches bad splits and kerning drift before a full batch"
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
        if active_camera(context) is None:
            return self.fail(context, "No camera")
        lines = collect_line_chunks(scene)
        if not lines:
            return self.fail(context, "No Line# collections with chunks found")

        targets = sorted(lines)
        tmp_dir = os.path.join(bpy.app.tempdir, "lc_contact_sheet")
        os.makedirs(tmp_dir, exist_ok=True)

        assert_render_settings(scene)
        guard = RenderSettingsGuard(scene)
        visibility = ChunkVisibilityGuard(
            context, lines, targets, props.template_object
        )
        wm = context.window_manager
        total = sum(len(lines[t][1]) for t in targets)
        done = 0
        wm.progress_begin(0, total)
        row_images = []
        try:
            scene.render.resolution_percentage = max(
                2, round(CONTACT_SHEET_WIDTH / max(1, scene.render.resolution_x) * 100)
            )
            for line_no in targets:
                _, objs = lines[line_no]
                row = None
                for obj in objs:
                    path = os.path.join(tmp_dir, f"{obj.name}.png")
                    render_single_chunk(scene, obj, path, visibility.all_chunks)
                    pixels = load_pixels(path)
                    row = pixels if row is None else alpha_over(row, pixels)
                    done += 1
                    wm.progress_update(done)
                row_images.append(row)
        except Exception as exc:
            return self.fail(context, f"Contact sheet failed after {done}/{total}: {exc}")
        finally:
            visibility.restore()
            guard.restore()
            wm.progress_end()

        h, w = row_images[0].shape[:2]
        sheet = np.zeros((h * len(row_images), w, 4), dtype=np.float32)
        # Line 1 at the top; pixel rows are bottom-up.
        for i, row in enumerate(row_images):
            offset = (len(row_images) - 1 - i) * h
            sheet[offset:offset + h] = row

        existing = bpy.data.images.get(CONTACT_SHEET_IMAGE)
        if existing is not None:
            bpy.data.images.remove(existing)
        img = bpy.data.images.new(
            CONTACT_SHEET_IMAGE, width=w, height=h * len(row_images), alpha=True
        )
        img.pixels[:] = sheet.ravel()
        if props.output_root:
            out = os.path.join(bpy.path.abspath(props.output_root), "contact_sheet.png")
            img.filepath_raw = out
            img.file_format = 'PNG'
            try:
                img.save()
            except (OSError, RuntimeError) as exc:
                self.report({'WARNING'}, f"Could not save contact sheet: {exc}")

        set_status(
            context,
            f"Contact sheet ready: open '{CONTACT_SHEET_IMAGE}' in the Image Editor "
            f"({len(targets)} lines, {total} chunks)",
        )
        return {'FINISHED'}
