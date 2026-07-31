#!/usr/bin/env python3
"""Generate pasteable Fusion node graphs from Lyric Chunker manifests.

For each Line#.json manifest, writes a Line#.setting next to it (or to
--out-dir). Open the .setting in a text editor, copy everything, click
an empty spot in the Fusion node area, and paste — the chunk graph
appears with color-flip and bounce keyframed from the manifest timing.
Wire the last Merge to MediaOut to finish.

Usage:
    python3 scripts/generate_comp.py <output_root_or_manifest> [more...]
    python3 scripts/generate_comp.py Line16/Line16.json --clip-dir "C:\\path\\Line 16"

--clip-dir sets the folder Loader nodes point at, for when the comp
runs on a different machine than the one that rendered (paths are baked
into the Loaders). Defaults to each manifest's own folder.
"""

import argparse
import importlib.util
import sys
from pathlib import Path

# --- repo-load --- (this whole section is replaced by inlined modules
# in the self-contained single-file build)
_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "lyric_chunker"


def _load(name, relpath):
    # Loaded by file path so importing never touches the package
    # __init__, which needs Blender's bpy.
    spec = importlib.util.spec_from_file_location(name, _PACKAGE_DIR / relpath)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_package(name, relpath):
    """Load comp/ as a real package so its relative imports resolve."""
    directory = _PACKAGE_DIR / relpath
    spec = importlib.util.spec_from_file_location(
        name, str(directory / "__init__.py"),
        submodule_search_locations=[str(directory)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load_package("lc_comp", "comp")
_gen = sys.modules["lc_comp.settings_gen"]
_reactor = sys.modules["lc_comp.reactor"]
_manifest = _load("lc_manifest", "manifest.py")

DEFAULT_DIP_DEPTH = _gen.DEFAULT_DIP_DEPTH
DEFAULT_DIP_IN = _gen.DEFAULT_DIP_IN
DEFAULT_DIP_OUT = _gen.DEFAULT_DIP_OUT
DEFAULT_HIGHLIGHT_GAIN = _gen.DEFAULT_HIGHLIGHT_GAIN
DEFAULT_UNTIMED_SECONDS = _gen.DEFAULT_UNTIMED_SECONDS
generate_line_setting = _gen.generate_line_setting
read_manifest = _manifest.read_manifest
ELEMENTS_FILENAME = _reactor.ELEMENTS_FILENAME
load_elements = _reactor.load_elements
template_elements = _reactor.template_elements
# --- end repo-load ---


def find_manifests(paths):
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found = sorted(path.glob("Line*/Line*.json")) or sorted(
                path.glob("Line*.json")
            )
            if not found:
                sys.exit(f"no Line#.json manifests under {path}")
            yield from found
        else:
            yield path


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+",
                    help="Line#.json manifest(s), or an output root to scan")
    ap.add_argument("--out-dir", type=Path,
                    help="write .setting files here (default: next to each manifest)")
    ap.add_argument("--clip-dir",
                    help="folder the Loader nodes read PNGs from "
                         "(default: each manifest's folder)")
    ap.add_argument("--highlight", nargs=3, type=float, metavar=("R", "G", "B"),
                    default=list(DEFAULT_HIGHLIGHT_GAIN),
                    help="highlight gain, default 1.0 0.4 0.05 (the orange)")
    ap.add_argument("--dip-depth", type=float, default=DEFAULT_DIP_DEPTH,
                    help="bounce depth in normalized frame height, default 0.015")
    ap.add_argument("--dip-in", type=int, default=DEFAULT_DIP_IN,
                    help="frames from chunk start to full dip/color, default 1")
    ap.add_argument("--dip-out", type=int, default=DEFAULT_DIP_OUT,
                    help="frames to recover from the dip, default 3")
    ap.add_argument("--untimed-seconds", type=float,
                    default=DEFAULT_UNTIMED_SECONDS,
                    help="with no timing data, cascade chunks across this "
                         "many seconds (default 3)")
    ap.add_argument("--untimed-frames", type=int, default=None,
                    help="with no timing data, cascade chunks across exactly "
                         "this many frames (overrides --untimed-seconds)")
    ap.add_argument("--init-elements", action="store_true",
                    help="write a starter elements.json beside the manifests "
                         "and exit")
    args = ap.parse_args()

    if args.init_elements:
        import json
        root = Path(args.paths[0])
        root = root if root.is_dir() else root.parent
        target = root / ELEMENTS_FILENAME
        if target.exists():
            sys.exit(f"{target} already exists")
        (root / "elements").mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(template_elements(), indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {target} — add element PNGs under {root / 'elements'}")
        return

    manifests = list(find_manifests(args.paths))
    elements_root = manifests[0].parent.parent if manifests else Path(".")
    elements, element_warnings = load_elements(
        str(elements_root / ELEMENTS_FILENAME)
    )
    for warning in element_warnings:
        print(f"  warning: {warning}")

    for manifest_path in manifests:
        doc = read_manifest(manifest_path)
        clip_dir = args.clip_dir or str(manifest_path.parent)
        text, warnings = generate_line_setting(
            doc,
            clip_dir,
            highlight=tuple(args.highlight),
            dip_depth=args.dip_depth,
            dip_in=args.dip_in,
            dip_out=args.dip_out,
            untimed_seconds=args.untimed_seconds,
            untimed_frames=args.untimed_frames,
            elements=elements,
            elements_dir=str(elements_root),
        )
        out_dir = args.out_dir or manifest_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / (manifest_path.stem + ".setting")
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out} ({len(doc['chunks'])} chunks)")
        for w in warnings:
            print(f"  warning: {w}")
    print(
        "\nPaste into Fusion: open the .setting in a text editor, copy all, "
        "click an empty spot in the node area, Ctrl+V, then wire the last "
        "Merge to MediaOut."
    )


if __name__ == "__main__":
    main()
