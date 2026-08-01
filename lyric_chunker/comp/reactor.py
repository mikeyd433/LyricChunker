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

# Travel mode: the element hops between words, arriving on each chunk's
# start frame rather than leaving on it — a bouncing-ball pointer lands
# on the beat.
DEFAULT_HOP_FRAMES = 6
DEFAULT_ARC_HEIGHT = 0.12
DEFAULT_TRAVEL_OFFSET = (0.0, 0.08)

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
            "motion: 'travel' hops the element from word to word, landing",
            "on each chunk as it lights up; 'bob' dips it in place.",
            "Travel wants a tight cut-out (it is positioned for you); bob",
            "wants a full-frame PNG with the image already in place.",
            "offset: [x, y] from the word's top-centre, so 0, 0.08 rides",
            "just above the text. hop_frames is how long the arc takes,",
            "arc_height how high it peaks.",
            "Two elements set to 'odd' and 'even' alternate; one set to",
            "'all' reacts to every chunk.",
            "Avoid names ending in digits (head1.png, head2.png) — Fusion",
            "may read those as an image sequence. Use head_left.png etc.",
        ],
        "elements": [
            {
                "name": "HeadOne",
                "image": "elements/head_one.png",
                "motion": "travel",
                "chunks": "odd",
                "lines": "all",
                "offset": list(DEFAULT_TRAVEL_OFFSET),
                "size": 1.0,
                "hop_frames": DEFAULT_HOP_FRAMES,
                "arc_height": DEFAULT_ARC_HEIGHT,
                "in_front": True,
                "enabled": True,
            },
            {
                "name": "HeadTwo",
                "image": "elements/head_two.png",
                "motion": "travel",
                "chunks": "even",
                "lines": "all",
                "offset": list(DEFAULT_TRAVEL_OFFSET),
                "size": 1.0,
                "hop_frames": DEFAULT_HOP_FRAMES,
                "arc_height": DEFAULT_ARC_HEIGHT,
                "in_front": True,
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


def _dedupe(keys):
    """Sorted, one key per frame — later keys win."""
    merged = {}
    for frame, value in keys:
        merged[frame] = value
    return [(frame, merged[frame]) for frame in sorted(merged)]


def travel_keys(starts, landings, hop_frames=DEFAULT_HOP_FRAMES,
                arc_height=DEFAULT_ARC_HEIGHT):
    """X and Y keyframes for an element hopping between word positions.

    The element rests on a word, then arcs to the next one so that it
    *lands* exactly on that chunk's start frame — the hop occupies the
    frames before the beat, not after it. The arc peaks between the two
    landings, ``arc_height`` above the higher of them.

    Returns ``(x_keys, y_keys, warnings)``.
    """
    warnings = []
    if not starts:
        return [], [], warnings

    x_keys = [(starts[0], landings[0][0])]
    y_keys = [(starts[0], landings[0][1])]
    for index in range(1, len(starts)):
        previous, current = starts[index - 1], starts[index]
        gap = current - previous
        if gap <= 0:
            warnings.append(
                f"hop landing on frame {current} is not after the previous "
                "one — skipped"
            )
            continue
        hop = max(1, min(hop_frames, gap))
        launch = current - hop
        from_x, from_y = landings[index - 1]
        to_x, to_y = landings[index]
        if launch > previous:
            # Hold on the current word until the hop begins.
            x_keys.append((launch, from_x))
            y_keys.append((launch, from_y))
        apex_frame = launch + hop // 2
        if launch < apex_frame < current:
            y_keys.append((apex_frame, max(from_y, to_y) + arc_height))
        x_keys.append((current, to_x))
        y_keys.append((current, to_y))
    return _dedupe(x_keys), _dedupe(y_keys), warnings


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
