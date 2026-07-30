import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest_util import PACKAGE_DIR, load  # noqa: E402

import importlib.util


def _load_comp():
    spec = importlib.util.spec_from_file_location(
        "lc_test_settings_gen", PACKAGE_DIR / "comp" / "settings_gen.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["lc_test_settings_gen"] = module
    spec.loader.exec_module(module)
    return module


gen = _load_comp()


def make_doc(n_chunks=4, line_start=12.5, fps=24):
    chunks = []
    for i in range(1, n_chunks + 1):
        start_seconds = line_start + (i - 1) * 0.25
        chunks.append({
            "index": i,
            "name": f"Line16_Chunk{i}",
            "text": f"chunk{i}",
            "filename": f"Line16_Chunk{i}.png",
            "start_seconds": start_seconds,
            "start_frame": round(start_seconds * fps),
            "timing_source": "srt",
        })
    return {
        "manifest_version": 1,
        "render": {"fps": fps, "fps_base": 1.0},
        "line": {
            "index": 16,
            "start_seconds": line_start,
            "end_seconds": line_start + 1.0,
        },
        "chunks": chunks,
    }


def test_line_local_frames_are_relative_to_line_start():
    doc = make_doc()
    frames, warnings = gen.line_local_frames(doc)
    assert frames == [0, 6, 12, 18]
    assert warnings == []


def test_partially_untimed_chunk_lands_at_zero_with_warning():
    doc = make_doc(n_chunks=2)
    doc["chunks"][1]["start_frame"] = None
    doc["chunks"][1]["start_seconds"] = None
    doc["chunks"][1]["timing_source"] = "none"
    frames, warnings = gen.line_local_frames(doc)
    assert frames[1] == 0
    assert len(warnings) == 1


def test_fully_untimed_line_cascades_across_default_span():
    doc = make_doc(n_chunks=4)
    for chunk in doc["chunks"]:
        chunk["start_frame"] = None
        chunk["start_seconds"] = None
        chunk["timing_source"] = "none"
    doc["line"]["start_seconds"] = None
    doc["line"]["end_seconds"] = None
    frames, warnings = gen.line_local_frames(doc)
    # Equal-length chunks over 3s at 24fps -> 72 frames / 4 = 18 apart.
    assert frames == [0, 18, 36, 54]
    assert any("scaffold" in w for w in warnings)
    # Weighted: a longer chunk holds the cursor longer.
    doc["chunks"][0]["text"] = "aaaaaaaaaaaa"
    frames, _ = gen.line_local_frames(doc)
    assert frames[0] == 0
    assert frames[1] > 18


def test_generated_setting_structure():
    doc = make_doc()
    text, warnings = gen.generate_line_setting(doc, "C:\\renders\\Line 16")
    assert warnings == []
    assert text.count("{") == text.count("}")
    assert text.startswith("{")
    # One branch per chunk, merges chaining them.
    assert text.count("= Loader {") == 4
    assert text.count("= ColorGain {") == 4
    assert text.count("= Transform {") == 4
    assert text.count("= Merge {") == 3
    assert 'ActiveTool = "Merge_Line16_3"' in text
    # Windows path escaped for Lua.
    assert "C:\\\\renders\\\\Line 16\\\\Line16_Chunk1.png" in text


def test_color_keyframes_at_chunk_start():
    doc = make_doc()
    text, _ = gen.generate_line_setting(doc, "/renders/Line16")
    # Chunk 3 starts at local frame 12: white at 12, orange at 13.
    assert "[12] = { 1, Flags = { Linear = true } }" in text
    assert "[13] = { 0.4, Flags = { Linear = true } }" in text
    assert "[13] = { 0.05, Flags = { Linear = true } }" in text


def test_bounce_path_matches_reference_structure():
    doc = make_doc(n_chunks=1)
    text, _ = gen.generate_line_setting(doc, "/r")
    # 3-point PolyPath: rest, dip of -0.015, rest.
    assert "= PolyPath {" in text
    assert "Y = -0.015" in text
    assert text.count("{ Linear = true, LockY = true, X = 0, Y = 0 }") == 2
    # Displacement keyed 0 -> 0.5 -> 1 at S, S+1, S+4 (S=0 here).
    assert "[0] = { 0, Flags = { Linear = true, LockedY = true } }" in text
    assert "[1] = { 0.5, Flags = { Linear = true, LockedY = true } }" in text
    assert "[4] = { 1, Flags = { Linear = true, LockedY = true } }" in text


def test_single_chunk_line_has_no_merges():
    doc = make_doc(n_chunks=1)
    text, _ = gen.generate_line_setting(doc, "/r")
    assert "= Merge {" not in text
    assert 'ActiveTool = "Move_Line16_Chunk1"' in text


def test_empty_manifest_rejected():
    doc = make_doc()
    doc["chunks"] = []
    with pytest.raises(ValueError):
        gen.generate_line_setting(doc, "/r")
