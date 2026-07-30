"""Lyric Chunker — registration only. All behavior lives in the modules."""

import bpy
from bpy.props import PointerProperty

from .ops_generate import (
    LC_OT_add_line,
    LC_OT_generate_chunks,
    LC_OT_import_lines,
    LC_OT_new_lyrics_text,
    LC_OT_remove_line,
)
from .ops_render import (
    LC_OT_cancel_render,
    LC_OT_contact_sheet,
    LC_OT_render_queue,
    LC_OT_rerender_chunk,
)
from .ops_setup import LC_OT_setup_scene
from .ops_verify import LC_OT_verify_line
from .presets import (
    LC_OT_preset_apply,
    LC_OT_preset_remove,
    LC_OT_preset_save,
    LC_UL_style_presets,
)
from .properties import (
    LCLyricLine,
    LCStylePreset,
    LyricChunkerPreferences,
    LyricChunkerProps,
)
from .ui import LC_PT_panel, LC_UL_lyric_lines

classes = (
    LCLyricLine,
    LCStylePreset,
    LyricChunkerProps,
    LyricChunkerPreferences,
    LC_UL_lyric_lines,
    LC_OT_setup_scene,
    LC_OT_generate_chunks,
    LC_OT_add_line,
    LC_OT_remove_line,
    LC_OT_import_lines,
    LC_OT_new_lyrics_text,
    LC_OT_render_queue,
    LC_OT_cancel_render,
    LC_OT_rerender_chunk,
    LC_OT_verify_line,
    LC_OT_contact_sheet,
    LC_OT_preset_save,
    LC_OT_preset_apply,
    LC_OT_preset_remove,
    LC_UL_style_presets,
    LC_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.lyric_chunker = PointerProperty(type=LyricChunkerProps)


def unregister():
    # Guard against double-registration on reload — still the most common
    # dev-loop error.
    if hasattr(bpy.types.Scene, "lyric_chunker"):
        del bpy.types.Scene.lyric_chunker
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
