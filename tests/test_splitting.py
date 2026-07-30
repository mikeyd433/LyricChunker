import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest_util import load

splitting = load("splitting")


def test_spec_example():
    words, warnings = splitting.split_line("Some|thing wick|ed this way comes")
    assert splitting.flat_chunks(words) == [
        "Some", "thing", "wick", "ed", "this", "way", "comes",
    ]
    assert warnings == []


def test_hyphen_is_literal():
    words, warnings = splitting.split_line("well-worn boots")
    assert splitting.flat_chunks(words) == ["well-worn", "boots"]
    assert warnings == []


def test_unsplit_words_are_single_chunks():
    words, _ = splitting.split_line("salazar has my boots")
    assert [len(w) for w in words] == [1, 1, 1, 1]


def test_zero_length_chunks_discarded_with_warning():
    words, warnings = splitting.split_line("some||thing")
    assert splitting.flat_chunks(words) == ["some", "thing"]
    assert len(warnings) == 1


def test_custom_delimiter():
    words, _ = splitting.split_line("some/thing", delimiter="/")
    assert splitting.flat_chunks(words) == ["some", "thing"]


def test_full_text_strips_delimiters():
    words, _ = splitting.split_line("Some|thing wick|ed this way comes")
    assert splitting.full_text(words) == "Something wicked this way comes"


def test_prefix_text_includes_word_spaces():
    words, _ = splitting.split_line("Some|thing wick|ed")
    # chunks: Some, thing, wick, ed
    assert splitting.prefix_text(words, 0) == ""
    assert splitting.prefix_text(words, 1) == "Some"
    assert splitting.prefix_text(words, 2) == "Something "
    assert splitting.prefix_text(words, 3) == "Something wick"


def test_parse_block_numbering_and_blank_rows():
    text = "first line\n\nsec|ond line\n   \nthird"
    lines, warnings = splitting.parse_block(text, start_index=12)
    assert [(no, raw) for no, raw, _ in lines] == [
        (12, "first line"),
        (13, "sec|ond line"),
        (14, "third"),
    ]
    assert warnings == []


def test_parse_block_delimiter_only_row_warns():
    lines, warnings = splitting.parse_block("|||\nreal")
    assert len(lines) == 1
    assert lines[0][0] == 1
    assert any("skipped" in w for w in warnings)
