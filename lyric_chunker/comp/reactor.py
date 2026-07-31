"""Reactor elements — extra images that bounce on chunk timing.

The second consumer of the manifest (§1): anything that should react to
the vocal — a cut-out head, a logo, a prop rendered out of Blender —
reads the same per-chunk start frames the lyrics use, so timing is
captured once and drives everything.

An element is a transparent PNG plus a rule for *which* chunks it
reacts to. Two elements set to ``odd`` and ``even`` alternate; one
element set to ``all`` bounces on every chunk. ``enabled`` switches an
element off without deleting its configuration.

Config lives in ``elements.json`` at the render output root, beside the
Line#/ folders. Generation is otherwise identical to a lyric chunk:

    Loader -> Place (static position/size) -> Bounce (PolyPath) -> Merge

The bounce reuses the verified 3-point PolyPath, but an element bounces
many times in one line, so its Displacement spline alternates direction
each time — 0 -> 0.5 -> 1, then 1 -> 0.5 -> 0. Both ends of the path
are the rest position, so consecutive bounces need no reset key and the
element sits still between them.
"""

import os
import re

ELEMENTS_FILENAME = "elements.json"
ELEMENTS_VERSION = 1

DEFAULT_ELEMENT_DEPTH = 0.03
DEFAULT_ELEMENT_DIP_IN = 1
DEFAULT_ELEMENT_DIP_OUT = 3
DEFAULT_ELEMENT_POSITION = (0.5, 0.5)

_NAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_]")


def template_elements():
    """Starter config: two heads alternating odd/even chunks.

    Switching to a single bouncing object is two edits — set one
    element's ``chunks`` to ``"all"`` and the other's ``enabled`` to
    false.
    """
    return {
        "elements_version": ELEMENTS_VERSION,
        "_readme": [
            "Elements bounce on chunk timing alongside the lyrics.",
            "image: transparent PNG, relative to this file or absolute.",
            "chunks: 'all', 'odd', 'even', or a list like [1, 3, 5] (1-based).",
            "lines: 'all' or a list of line numbers like [17, 18].",
            "position: normalized [x, y]; 0.5, 0.5 is frame centre.",
            "in_front: true to sit over the lyrics, false to sit behind.",
            "enabled: false switches an element off without deleting it.",
            "Two elements set to 'odd' and 'even' alternate; one set to",
            "'all' bounces on every chunk.",
            "Avoid names ending in digits (head1.png, head2.png) — Fusion",
            "may read those as an image sequence. Use head_left.png etc.",
        ],
        "elements": [
            {
                "name": "HeadLeft",
                "image": "elements/head_left.png",
                "chunks": "odd",
                "lines": "all",
                "position": [0.22, 0.35],
                "size": 1.0,
                "bounce_depth": DEFAULT_ELEMENT_DEPTH,
                "dip_in": DEFAULT_ELEMENT_DIP_IN,
                "dip_out": DEFAULT_ELEMENT_DIP_OUT,
                "in_front": False,
                "enabled": True,
            },
            {
                "name": "HeadRight",
                "image": "elements/head_right.png",
                "chunks": "even",
                "lines": "all",
                "position": [0.78, 0.35],
                "size": 1.0,
                "bounce_depth": DEFAULT_ELEMENT_DEPTH,
                "dip_in": DEFAULT_ELEMENT_DIP_IN,
                "dip_out": DEFAULT_ELEMENT_DIP_OUT,
                "in_front": False,
                "enabled": True,
            },
        ],
    }


def load_elements(path):
    """Read an elements.json. Returns ``(elements, warnings)`` with only
    the enabled entries; a missing file is not an error."""
    import json

    if not os.path.exists(path):
        return [], []
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    version = doc.get("elements_version")
    if version != ELEMENTS_VERSION:
        raise ValueError(
            f"elements_version {version!r} in {path} — this build reads "
            f"version {ELEMENTS_VERSION}"
        )
    warnings = []
    elements = []
    for index, element in enumerate(doc.get("elements", []), start=1):
        name = element.get("name") or f"Element{index}"
        if not element.get("enabled", True):
            continue
        if not element.get("image"):
            warnings.append(f"element '{name}' has no image — skipped")
            continue
        elements.append(element)
    return elements, warnings


def safe_name(name):
    cleaned = _NAME_SAFE_RE.sub("_", str(name)).strip("_")
    return cleaned or "Element"


def is_absolute(image):
    return os.path.isabs(image) or bool(re.match(r"^[A-Za-z]:", image))


def applies_to_line(element, line_no):
    lines = element.get("lines", "all")
    if isinstance(lines, str):
        return lines.lower() == "all"
    return line_no in lines


def chunk_indices(element, chunk_count):
    """0-based chunk indices this element reacts to."""
    selector = element.get("chunks", "all")
    if isinstance(selector, str):
        key = selector.lower()
        if key == "all":
            return list(range(chunk_count))
        if key == "odd":
            return [i for i in range(chunk_count) if i % 2 == 0]
        if key == "even":
            return [i for i in range(chunk_count) if i % 2 == 1]
        return []
    return [n - 1 for n in selector if 1 <= n <= chunk_count]


def displacement_keys(starts, dip_in, dip_out):
    """Alternating-direction bounce keys for one element.

    Each bounce traverses the 3-point path in the opposite direction to
    the last, so the element rests between bounces without a reset key.
    Bounces that would overlap the previous one are dropped.
    """
    keys = []
    warnings = []
    value = 0.0
    last_end = None
    for start in starts:
        if last_end is not None and start < last_end:
            warnings.append(
                f"bounce at frame {start} overlaps the previous one — skipped"
            )
            continue
        target = 1.0 - value
        end = start + dip_in + dip_out
        if keys and keys[-1][0] == start:
            keys.pop()
        keys.append((start, value))
        keys.append((start + dip_in, 0.5))
        keys.append((end, target))
        value = target
        last_end = end
    return keys, warnings
