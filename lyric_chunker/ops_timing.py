"""Timing capture and preview (spec addendum §4.3).

Two operators that close the timing loop inside Blender:

- **Tap Timing** — a modal operator that plays the scene and drops a
  correctly named ``Line#_Chunk#`` marker on every tap, in chunk order.
  This is the only practical route to genuine syllable-level timing
  (§4.1: no distributable format carries it), and naming the markers
  automatically is what makes it bearable for a whole song.
- **Preview Timing** — resolves the current marker/SRT timing and
  keyframes each chunk's *object color* white -> highlight at its start
  frame, so scrubbing with the song shows the karaoke flip in the
  viewport before anything reaches Resolve.

Object color is viewport-only — the render materials ignore it — so the
preview never changes a rendered pixel. Clear Preview removes it again.
"""

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator

from .manifest import chunk_name
from .ops_generate import collect_line_chunks, get_target_line
from .ops_render import compute_timing, effective_fps
from .properties import set_status
from .timing_srt import SrtParseError

PREVIEW_WHITE = (1.0, 1.0, 1.0, 1.0)
# Matches the comp generator's highlight gain, so the viewport preview
# and the Fusion output agree.
PREVIEW_HIGHLIGHT = (1.0, 0.4, 0.05, 1.0)


def _chunk_queue(context, targets, lines):
    """Flat (line_no, chunk_no, text) list in tap order."""
    queue = []
    for line_no in targets:
        _, objs = lines[line_no]
        for obj in objs:
            queue.append((line_no, int(obj["lc_chunk"]), str(obj["lc_text"])))
    return queue


class LC_OT_tap_timing(Operator):
    bl_idname = "lyric_chunker.tap_timing"
    bl_label = "Tap Timing"
    bl_description = (
        "Play the scene and tap along to the vocal — each tap drops a "
        "marker named for the next chunk, in order. Enter or click to "
        "tap, Backspace to undo the last one, Esc when done"
    )

    all_lines: BoolProperty(default=False, options={'HIDDEN'})

    _tap_events = {'RET', 'NUMPAD_ENTER', 'LEFTMOUSE'}

    def fail(self, context, message):
        set_status(context, message, error=True)
        self.report({'ERROR'}, message)
        return {'CANCELLED'}

    def invoke(self, context, event):
        scene = context.scene
        props = scene.lyric_chunker
        if props.is_tapping:
            return self.fail(context, "Already tapping")
        if props.is_rendering:
            return self.fail(context, "A render batch is running")

        lines = collect_line_chunks(scene)
        if not lines:
            return self.fail(
                context, "Generate chunks first — nothing to tap timing for"
            )
        if self.all_lines:
            targets = sorted(lines)
        else:
            target = get_target_line(context)
            if target not in lines:
                return self.fail(context, f"No chunks found for Line {target}")
            targets = [target]

        self.queue = _chunk_queue(context, targets, lines)
        self.index = 0
        self.placed = []
        props.is_tapping = True
        self._update_progress(context)

        if not context.screen.is_animation_playing:
            bpy.ops.screen.animation_play()
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _update_progress(self, context):
        props = context.scene.lyric_chunker
        if self.index >= len(self.queue):
            props.progress = "All chunks tapped — Esc to finish"
        else:
            line_no, chunk_no, text = self.queue[self.index]
            props.progress = (
                f"Tap Line {line_no} chunk {chunk_no} — '{text}' "
                f"({self.index + 1}/{len(self.queue)})"
            )
        context.workspace.status_text_set(
            props.progress + "    |    Enter/Click: tap    "
            "Backspace: undo    Esc: finish"
        )
        for area in context.screen.areas:
            if area.type in {'VIEW_3D', 'DOPESHEET_EDITOR', 'TIMELINE'}:
                area.tag_redraw()

    def _tap(self, context):
        scene = context.scene
        line_no, chunk_no, _ = self.queue[self.index]
        name = chunk_name(line_no, chunk_no, scene.lyric_chunker.zero_pad)
        for marker in list(scene.timeline_markers):
            if marker.name == name:
                scene.timeline_markers.remove(marker)
        scene.timeline_markers.new(name, frame=scene.frame_current)
        self.placed.append(name)
        self.index += 1
        self._update_progress(context)

    def _undo(self, context):
        if not self.placed:
            return
        scene = context.scene
        name = self.placed.pop()
        for marker in list(scene.timeline_markers):
            if marker.name == name:
                scene.timeline_markers.remove(marker)
        self.index = max(0, self.index - 1)
        self._update_progress(context)

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            return self.finish(context)
        if event.type == 'BACK_SPACE' and event.value == 'PRESS':
            self._undo(context)
            return {'RUNNING_MODAL'}
        if event.type in self._tap_events and event.value == 'PRESS':
            if self.index < len(self.queue):
                self._tap(context)
            if self.index >= len(self.queue):
                return self.finish(context)
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    def finish(self, context):
        props = context.scene.lyric_chunker
        if context.screen.is_animation_playing:
            bpy.ops.screen.animation_play()
        props.is_tapping = False
        props.progress = ""
        context.workspace.status_text_set(None)
        count = len(self.placed)
        set_status(
            context,
            f"Tapped {count} marker(s) — Preview Timing to check, then "
            "re-render or Refresh Timing to bake it in",
        )
        return {'FINISHED'}


class LC_OT_preview_timing(Operator):
    bl_idname = "lyric_chunker.preview_timing"
    bl_label = "Preview Timing"
    bl_description = (
        "Keyframe each chunk's viewport colour from white to the "
        "highlight at its start time, so scrubbing with the song shows "
        "the timing. Viewport only — renders are unaffected"
    )

    def fail(self, context, message):
        set_status(context, message, error=True)
        self.report({'ERROR'}, message)
        return {'CANCELLED'}

    def execute(self, context):
        scene = context.scene
        lines = collect_line_chunks(scene)
        if not lines:
            return self.fail(context, "Generate chunks first")
        targets = sorted(lines)
        try:
            timing, warnings = compute_timing(context, lines, targets)
        except SrtParseError as exc:
            return self.fail(context, f"SRT import failed: {exc}")

        fps = effective_fps(scene)
        first = scene.frame_start
        timed = 0
        untimed = 0
        for line_no in targets:
            _, objs = lines[line_no]
            chunk_times, _, _ = timing[line_no]
            for obj, (seconds, _source) in zip(objs, chunk_times):
                obj.animation_data_clear()
                obj.color = PREVIEW_WHITE
                if seconds is None:
                    untimed += 1
                    continue
                frame = max(first + 1, round(seconds * fps))
                obj.keyframe_insert("color", frame=first)
                obj.color = PREVIEW_HIGHLIGHT
                obj.keyframe_insert("color", frame=frame)
                # Hard flip, not a fade — matches the comp's one-frame
                # colour change.
                for fcurve in obj.animation_data.action.fcurves:
                    for point in fcurve.keyframe_points:
                        point.interpolation = 'CONSTANT'
                timed += 1

        # Object colour is only visible in solid shading set to Object.
        for area in context.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.color_type = 'OBJECT'

        message = f"Preview on: {timed} chunk(s) timed"
        if untimed:
            message += f", {untimed} without timing left white"
        message += " — scrub the timeline to check against the song"
        if warnings:
            for w in warnings:
                self.report({'WARNING'}, w)
        set_status(context, message)
        return {'FINISHED'}


class LC_OT_clear_preview(Operator):
    bl_idname = "lyric_chunker.clear_preview"
    bl_label = "Clear Preview"
    bl_description = "Remove the viewport timing preview from every chunk"

    def execute(self, context):
        lines = collect_line_chunks(context.scene)
        cleared = 0
        for _coll, objs in lines.values():
            for obj in objs:
                if obj.animation_data is not None:
                    obj.animation_data_clear()
                    cleared += 1
                obj.color = PREVIEW_WHITE
        set_status(context, f"Cleared timing preview from {cleared} chunk(s)")
        return {'FINISHED'}
