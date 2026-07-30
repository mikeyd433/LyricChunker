import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest_util import load

manifest = load("manifest")


def test_naming_unpadded_and_padded():
    assert manifest.line_dirname(1) == "Line1"
    assert manifest.line_dirname(1, pad=True) == "Line01"
    assert manifest.chunk_name(3, 2) == "Line3_Chunk2"
    assert manifest.chunk_filename(3, 2, pad=True) == "Line03_Chunk02.png"
    assert manifest.manifest_filename(7) == "Line7.json"


def test_manifest_filename_never_reserved():
    for n in range(1, 200):
        for pad in (False, True):
            assert manifest.manifest_filename(n, pad) not in manifest.RESERVED_FILENAMES


def test_round_trip(tmp_path):
    entry = manifest.build_chunk_entry(
        index=1,
        name="Line1_Chunk1",
        text="Some",
        filename="Line1_Chunk1.png",
        world_position=(0.0, 0.0, 0.0),
        screen_position=(0.312, 0.5),
        bbox_px=(412, 476, 588, 604),
        offset_x=0.0,
        start_seconds=12.5,
        start_frame=300,
        timing_source="srt",
    )
    doc = manifest.build_manifest(
        generator={"addon": manifest.ADDON_ID, "addon_version": manifest.ADDON_VERSION,
                   "blender_version": "4.2.1"},
        project={"blend_file": "x.blend", "scene": "Scene", "camera": "Camera",
                 "style_preset": "", "template_object": "LC_Template"},
        render={"engine": "BLENDER_EEVEE_NEXT", "resolution_x": 1920,
                "resolution_y": 1080, "resolution_percentage": 100, "fps": 24,
                "fps_base": 1.0, "film_transparent": True, "color_depth": "16",
                "file_format": "PNG"},
        line={"index": 1, "text_raw": "Some|thing", "delimiter": "|",
              "output_dir": "Line1", "start_seconds": 12.5, "end_seconds": 15.0,
              "timing_source": "srt"},
        chunks=[entry],
        rendered_at="2026-07-30T00:00:00+00:00",
    )
    path = tmp_path / "Line1.json"
    manifest.write_manifest(path, doc)
    loaded = manifest.read_manifest(path)
    assert loaded == doc
    assert loaded["manifest_version"] == manifest.MANIFEST_VERSION
    assert loaded["chunks"][0]["start_seconds"] == 12.5


def test_read_rejects_unknown_version(tmp_path):
    path = tmp_path / "Line1.json"
    path.write_text('{"manifest_version": 99}')
    with pytest.raises(ValueError):
        manifest.read_manifest(path)


def test_seconds_to_frame():
    assert manifest.seconds_to_frame(12.5, 24) == 300
    assert manifest.seconds_to_frame(12.5, 24, fps_base=1.001) == 300
    assert manifest.seconds_to_frame(None, 24) is None


def test_chunk_entry_defaults():
    entry = manifest.build_chunk_entry(
        1, "Line1_Chunk1", "a", "Line1_Chunk1.png",
        (0, 0, 0), (0.5, 0.5), (0, 0, 1, 1), 0.0,
    )
    assert entry["start_seconds"] is None
    assert entry["start_frame"] is None
    assert entry["timing_source"] == "none"
    assert entry["manual_offset_x"] == 0.0
