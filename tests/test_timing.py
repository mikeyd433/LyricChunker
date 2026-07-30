import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest_util import load

timing_srt = load("timing_srt")
timing_markers = load("timing_markers")

SRT = """\
1
00:00:12,500 --> 00:00:15,000
Something wicked this way comes

2
00:00:16,000 --> 00:00:18,250
Second line text
"""


def test_parse_srt_basic():
    entries = timing_srt.parse_srt(SRT)
    assert len(entries) == 2
    assert entries[0]["start"] == 12.5
    assert entries[0]["end"] == 15.0
    assert entries[1]["start"] == 16.0
    assert "Second line" in entries[1]["text"]


def test_parse_srt_dot_millis_and_no_index():
    entries = timing_srt.parse_srt("00:01:02.250 --> 00:01:03.000\ntext\n")
    assert entries[0]["start"] == pytest.approx(62.25)


def test_parse_srt_malformed_raises():
    with pytest.raises(timing_srt.SrtParseError):
        timing_srt.parse_srt("1\nnot a timestamp\ntext\n")


def test_entry_for_line_in_file_order():
    entries = timing_srt.parse_srt(SRT)
    assert timing_srt.entry_for_line(entries, 1)["start"] == 12.5
    assert timing_srt.entry_for_line(entries, 2)["start"] == 16.0
    assert timing_srt.entry_for_line(entries, 3) is None


def test_distribute_weighted_by_length():
    starts = timing_srt.distribute(0.0, 10.0, ["aaaa", "aaaa", "aa"])
    # weights 4,4,2 over span 10 -> starts 0, 4, 8
    assert starts == pytest.approx([0.0, 4.0, 8.0])


def test_distribute_min_weight_floor():
    starts = timing_srt.distribute(0.0, 6.0, ["a", "bbbb"])
    # weights floor to 2,4 -> starts 0, 2
    assert starts == pytest.approx([0.0, 2.0])


def test_named_markers_bind_directly():
    markers = [("Line1_Chunk2", 48), ("Line01_Chunk01", 24), ("stray", 5)]
    times, warnings = timing_markers.match_markers(
        markers, [(1, 1), (1, 2)], fps=24.0
    )
    assert times == {(1, 1): 1.0, (1, 2): 2.0}
    assert warnings == []


def test_named_marker_for_missing_chunk_warns():
    times, warnings = timing_markers.match_markers(
        [("Line9_Chunk9", 10)], [(1, 1)], fps=24.0
    )
    assert times == {}
    assert len(warnings) == 1


def test_positional_fallback_in_frame_order():
    markers = [("b", 48), ("a", 24)]
    times, warnings = timing_markers.match_markers(
        markers, [(1, 1), (1, 2)], fps=24.0
    )
    assert times == {(1, 1): 1.0, (1, 2): 2.0}
    assert warnings == []


def test_positional_count_mismatch_warns_with_counts():
    times, warnings = timing_markers.match_markers(
        [("a", 24)], [(1, 1), (1, 2), (1, 3)], fps=24.0
    )
    assert times == {(1, 1): 1.0}
    assert any("1 markers, 3 chunks" in w for w in warnings)


def test_precedence_markers_win_per_chunk():
    chunk_times, span, source = timing_markers.resolve_line_timing(
        line_no=1,
        chunk_texts=["Some", "thing"],
        marker_times={(1, 2): 13.7},
        srt_entry={"start": 12.5, "end": 15.0},
        distribute=timing_srt.distribute,
    )
    assert chunk_times[0] == (pytest.approx(12.5), "srt")
    assert chunk_times[1] == (pytest.approx(13.7), "marker")
    assert span == (12.5, 15.0)
    assert source == "srt"


def test_no_sources_yields_none():
    chunk_times, span, source = timing_markers.resolve_line_timing(
        1, ["a", "b"], {}, None, timing_srt.distribute
    )
    assert chunk_times == [(None, "none"), (None, "none")]
    assert span == (None, None)
    assert source == "none"
