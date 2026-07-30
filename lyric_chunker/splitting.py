"""Lyric line splitting (spec addendum §9).

Pure logic, no bpy — unit-testable outside Blender.

Rules:
  1. Split the line on whitespace into words.
  2. Split each word on the delimiter into chunks.
  3. Whitespace is always a chunk boundary; the delimiter creates
     sub-word splits.
  4. Discard zero-length chunks; warn if any were produced (usually a
     doubled delimiter typo).

The delimiter is configurable, default ``|``. Hyphens are literal
characters — they no longer split (and the old ``\\-`` escape is gone).
"""

DEFAULT_DELIMITER = "|"


def split_line(raw, delimiter=DEFAULT_DELIMITER):
    """Split one delimited lyric line.

    Returns ``(words, warnings)`` where ``words`` is a list of words,
    each word a list of chunk strings, and ``warnings`` is a list of
    human-readable strings for anything discarded.
    """
    words = []
    warnings = []
    for word in raw.split():
        parts = word.split(delimiter) if delimiter else [word]
        chunks = [p for p in parts if p]
        if len(chunks) != len(parts):
            warnings.append(
                f"'{word}' produced a zero-length chunk (doubled or stray "
                f"'{delimiter}'?) — discarded"
            )
        if chunks:
            words.append(chunks)
    return words, warnings


def flat_chunks(words):
    """Flatten the word/chunk structure into the left-to-right chunk list."""
    return [chunk for word in words for chunk in word]


def full_text(words):
    """The line as it should render, delimiters stripped, single-spaced."""
    return " ".join("".join(word) for word in words)


def prefix_text(words, chunk_index):
    """Text of everything before flat chunk ``chunk_index`` (0-based),
    including the space separating a preceding word — i.e. the exact
    string the chunk's glyphs follow in the full line."""
    out = []
    seen = 0
    for w, word in enumerate(words):
        for chunk in word:
            if seen == chunk_index:
                return "".join(out)
            out.append(chunk)
            seen += 1
        out.append(" ")
    return "".join(out)


def parse_block(text, delimiter=DEFAULT_DELIMITER, start_index=1):
    """Parse a multi-line lyrics block (§5.3).

    One lyric line per row; blank rows are skipped and do not consume a
    line number. Returns ``(lines, warnings)`` where ``lines`` is a list
    of ``(line_number, raw_text, words)`` tuples numbered from
    ``start_index``.
    """
    lines = []
    warnings = []
    number = start_index
    for row, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        words, w = split_line(raw, delimiter)
        warnings.extend(f"row {row}: {msg}" for msg in w)
        if not words:
            warnings.append(f"row {row}: no chunks after splitting — skipped")
            continue
        lines.append((number, raw.strip(), words))
        number += 1
    return lines, warnings
