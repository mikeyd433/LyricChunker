"""Scene state, add-on preferences, and shared helpers."""

import textwrap

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import AddonPreferences, PropertyGroup

from .splitting import DEFAULT_DELIMITER

# Resolves to the extension's full module path when installed as an
# Extension, the package name in a dev checkout, and the module name in
# the flattened single-file build.
ADDON_KEY = __package__ or "lyric_chunker"

DEFAULT_VERIFY_THRESHOLD = 2


def set_status(context, message, error=False):
    props = context.scene.lyric_chunker
    props.status = message
    props.status_error = error


def status_lines(props, width=44, max_rows=6):
    return textwrap.wrap(props.status, width=width)[:max_rows]


def get_prefs(context):
    addon = context.preferences.addons.get(ADDON_KEY)
    return addon.preferences if addon is not None else None


def verify_threshold(context):
    prefs = get_prefs(context)
    if prefs is None:
        return DEFAULT_VERIFY_THRESHOLD
    return prefs.verify_threshold


def active_camera(context):
    props = context.scene.lyric_chunker
    return props.camera_object or context.scene.camera


def _poll_camera(self, obj):
    return obj.type == 'CAMERA'


def _poll_font(self, obj):
    return obj.type == 'FONT'


def _sync_selected_line(self, context):
    """Keep line_number pointing at the selected list row so the
    Generate/Render Line N buttons target what's highlighted."""
    if 0 <= self.lyric_line_index < len(self.lyric_lines):
        self.line_number = self.start_index + self.lyric_line_index


class LCLyricLine(PropertyGroup):
    text: StringProperty(name="Line", default="")


class LCStylePreset(PropertyGroup):
    """Named style configuration captured from the template object (§5.2)."""
    name: StringProperty(name="Name", default="Preset")
    font_path: StringProperty(default="")
    size: FloatProperty(default=1.0)
    extrude: FloatProperty(default=0.0)
    bevel_depth: FloatProperty(default=0.0)
    bevel_resolution: IntProperty(default=4)
    shear: FloatProperty(default=0.0)
    space_character: FloatProperty(default=1.0)
    space_word: FloatProperty(default=1.0)
    align_x: StringProperty(default='LEFT')
    align_y: StringProperty(default='BOTTOM_BASELINE')
    material_name: StringProperty(default="")


class LyricChunkerProps(PropertyGroup):
    lyrics_text: PointerProperty(
        name="Lyrics",
        description=(
            "Text datablock with one delimited lyric line per row (edit it "
            "in the Text Editor). Leave empty to use the single-line field"
        ),
        type=bpy.types.Text,
    )
    line_text: StringProperty(
        name="Lyric Line",
        description=(
            "Single delimited lyric line, e.g. 'Some|thing wick|ed this "
            "way comes'. The delimiter splits syllables, whitespace splits "
            "words, hyphens are literal"
        ),
        default="",
    )
    delimiter: StringProperty(
        name="Delimiter",
        description=(
            "Sub-word split marker. '|' never appears in sung text, which "
            "is why it is the default"
        ),
        default=DEFAULT_DELIMITER,
        maxlen=8,
    )
    lyric_lines: CollectionProperty(type=LCLyricLine)
    lyric_line_index: IntProperty(default=0, update=_sync_selected_line)
    start_index: IntProperty(
        name="Start Index",
        description=(
            "Line number of the first row in the lyrics list, so lines "
            "12-20 can be rendered without renumbering (also offsets SRT "
            "entry mapping)"
        ),
        default=1,
        min=1,
        update=_sync_selected_line,
    )
    line_number: IntProperty(
        name="Line Number",
        description="Target line for single-line generate/render/verify",
        default=1,
        min=1,
    )
    force_uppercase: BoolProperty(
        name="Force Uppercase",
        description="Uppercase the text before generating",
        default=True,
    )
    template_object: PointerProperty(
        name="Template",
        description=(
            "Styled text object to copy font, extrude, bevel, materials, "
            "placement, and alignment from"
        ),
        type=bpy.types.Object,
        poll=_poll_font,
    )
    camera_object: PointerProperty(
        name="Camera",
        description="Camera to render through (falls back to the scene camera)",
        type=bpy.types.Object,
        poll=_poll_camera,
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
    srt_path: StringProperty(
        name="SRT File",
        description=(
            "Subtitle file supplying line start/end times; entry N maps to "
            "line N in order. Text content still comes from the lyrics "
            "block, not the SRT"
        ),
        subtype='FILE_PATH',
        default="",
    )
    untimed_spread: FloatProperty(
        name="Untimed Spread",
        description=(
            "With no SRT or marker timing, Generate Fusion Comps cascades "
            "each line's chunks across this many seconds"
        ),
        default=3.0,
        min=0.1,
        max=30.0,
    )
    untimed_spread_frames: IntProperty(
        name="Untimed Spread",
        description=(
            "With no SRT or marker timing, Generate Fusion Comps cascades "
            "each line's chunks across this many frames"
        ),
        default=24,
        min=1,
        max=10000,
    )
    untimed_spread_unit: EnumProperty(
        name="Spread Unit",
        items=(
            ('SECONDS', "Seconds", "Set the untimed cascade in seconds"),
            ('FRAMES', "Frames", "Set the untimed cascade in frames"),
        ),
        default='SECONDS',
    )
    use_markers: BoolProperty(
        name="Use Timeline Markers",
        description=(
            "Read chunk timing from timeline markers. A marker named "
            "Line1_Chunk1 binds directly; unnamed markers map to chunks in "
            "order. Markers win over SRT per chunk"
        ),
        default=True,
    )
    style_presets: CollectionProperty(type=LCStylePreset)
    style_preset_index: IntProperty(default=0)
    active_preset: StringProperty(
        description="Name of the last applied style preset, recorded in manifests",
        default="",
    )
    status: StringProperty(default="Ready")
    status_error: BoolProperty(default=False)
    last_line: IntProperty(default=0)
    is_rendering: BoolProperty(default=False)
    is_tapping: BoolProperty(default=False)
    render_cancel: BoolProperty(default=False)
    progress: StringProperty(default="")


class LyricChunkerPreferences(AddonPreferences):
    bl_idname = ADDON_KEY

    verify_threshold: IntProperty(
        name="Verify Threshold",
        description=(
            "Maximum per-pixel delta (0-255 scale) for Verify Line to pass"
        ),
        default=DEFAULT_VERIFY_THRESHOLD,
        min=0,
        max=255,
    )

    def draw(self, context):
        self.layout.prop(self, "verify_threshold")
