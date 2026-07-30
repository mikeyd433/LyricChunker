#!/usr/bin/env python3
"""Build the legacy single-file add-on (and optionally the Extension zip)
from the lyric_chunker/ package.

The package (blender_manifest.toml, Blender 4.2+ Extension) is the
canonical source. The dabingabongo.com downloads page ships a single
legacy ``lyric_chunker.py``, produced here by flattening the package:
relative imports are stripped, modules are concatenated in dependency
order, and a ``bl_info`` block generated from blender_manifest.toml is
prepended. Top-level names are unique across modules, so the flattened
file resolves the same names the package does.

Usage:
    python3 scripts/build_single_file.py --out build/lyric_chunker.py
    python3 scripts/build_single_file.py --zip dist/
"""

import argparse
import ast
import re
import sys
import tomllib
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "lyric_chunker"

# Concatenation order: every module appears after everything it imports.
MODULE_ORDER = [
    "splitting",
    "manifest",
    "timing_srt",
    "timing_markers",
    "measure",
    "properties",
    "presets",
    "ops_setup",
    "ops_generate",
    "ops_render",
    "ops_verify",
    "ui",
]

HEADER = '''\
# --------------------------------------------------------------------------
# GENERATED FILE — do not edit. Built from the lyric_chunker/ package by
# scripts/build_single_file.py. Edit the package modules instead.
# --------------------------------------------------------------------------
'''

MAIN_BLOCK = '''

if __name__ == "__main__":
    # Re-run friendly for the Text Editor dev loop.
    try:
        unregister()
    except Exception:
        pass
    register()
'''

# Modules inlined into the self-contained comp generator, in
# dependency order.
COMP_MODULES = ["manifest", "comp/settings_gen"]

REPO_LOAD_START = "# --- repo-load ---"
REPO_LOAD_END = "# --- end repo-load ---"

BUNDLE_README = """\
Lyric Chunker bundle
====================

lyric_chunker.py — the Blender add-on. Install via Edit > Preferences >
  Add-ons > Install from Disk. Renders per-syllable chunk PNGs plus a
  Line#.json timing manifest per line.

generate_comp.py — the Fusion comp generator (needs Python 3, nothing
  else). Feed it the add-on's output and it writes a pasteable
  Line#.setting node graph per line:

      python generate_comp.py "C:\\path\\to\\output_root"

  Open the .setting in a text editor, copy all, paste into the Fusion
  node area in DaVinci Resolve, and wire the last Merge to MediaOut.

Docs: https://github.com/mikeyd433/LyricChunker
"""


def read_toml_meta():
    with open(PACKAGE_DIR / "blender_manifest.toml", "rb") as fh:
        meta = tomllib.load(fh)
    return meta


def package_addon_version():
    text = (PACKAGE_DIR / "manifest.py").read_text(encoding="utf-8")
    m = re.search(r'^ADDON_VERSION = "([^"]+)"', text, re.MULTILINE)
    if not m:
        sys.exit("ADDON_VERSION not found in lyric_chunker/manifest.py")
    return m.group(1)


def strip_relative_imports(source):
    """Remove `from . import ...` / `from .mod import ...` statements,
    including parenthesized multi-line forms, using AST line ranges."""
    tree = ast.parse(source)
    drop = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            drop.update(range(node.lineno, node.end_lineno + 1))
    lines = source.splitlines()
    kept = [line for i, line in enumerate(lines, start=1) if i not in drop]
    return "\n".join(kept).rstrip() + "\n"


def bl_info_block(meta):
    version = tuple(int(p) for p in meta["version"].split("."))
    blender_min = tuple(int(p) for p in meta["blender_version_min"].split("."))
    author = meta["maintainer"].split("<")[0].strip()
    return (
        "bl_info = {\n"
        f'    "name": "{meta["name"]}",\n'
        f'    "author": "{author}",\n'
        f'    "version": {version},\n'
        f'    "blender": {blender_min},\n'
        '    "location": "3D Viewport > Sidebar (N) > Lyric Chunker",\n'
        f'    "description": "{meta["tagline"]}",\n'
        '    "category": "Object",\n'
        "}\n"
    )


def build_flat_source():
    meta = read_toml_meta()
    addon_version = package_addon_version()
    if meta["version"] != addon_version:
        sys.exit(
            f"version mismatch: blender_manifest.toml has {meta['version']} "
            f"but manifest.py ADDON_VERSION is {addon_version}"
        )

    parts = [HEADER, bl_info_block(meta)]
    for name in MODULE_ORDER:
        source = (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8")
        parts.append(
            f"\n\n# ===== {name}.py "
            + "=" * max(0, 56 - len(name))
            + "\n\n"
            + strip_relative_imports(source)
        )
    init_source = (PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8")
    parts.append(
        "\n\n# ===== registration "
        + "=" * 52
        + "\n\n"
        + strip_relative_imports(init_source)
    )
    parts.append(MAIN_BLOCK)
    flat = "".join(parts)

    # The flattened file must be valid Python and must not still contain
    # relative imports.
    compile(flat, "lyric_chunker.py", "exec")
    if re.search(r"^from \.", flat, re.MULTILINE):
        sys.exit("relative import survived flattening")
    return flat, meta


def build_comp_source():
    """Flatten generate_comp.py into a self-contained script: the
    repo-load section is replaced by the inlined manifest and
    settings_gen modules, so it runs anywhere with plain Python 3."""
    cli = (REPO_ROOT / "scripts" / "generate_comp.py").read_text(encoding="utf-8")
    start = cli.index(REPO_LOAD_START)
    end = cli.index(REPO_LOAD_END) + len(REPO_LOAD_END)
    inlined = []
    for name in COMP_MODULES:
        source = (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8")
        inlined.append(
            f"# ===== {name}.py "
            + "=" * max(0, 56 - len(name))
            + "\n\n"
            + strip_relative_imports(source)
        )
    flat = (
        HEADER
        + cli[:start]
        + "\n\n".join(inlined)
        + cli[end:]
    )
    compile(flat, "generate_comp.py", "exec")
    if re.search(r"^from \.", flat, re.MULTILINE):
        sys.exit("relative import survived comp flattening")
    return flat


def build_bundle(bundle_path, addon_source, comp_source, meta):
    """Zip the flattened add-on and comp generator together. Fixed
    timestamps keep the archive byte-stable for unchanged inputs."""
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = (2020, 1, 1, 0, 0, 0)
    entries = [
        ("lyric_chunker.py", addon_source),
        ("generate_comp.py", comp_source),
        ("README.txt", BUNDLE_README),
    ]
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries:
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.external_attr = 0o644 << 16
            zf.writestr(info, content)
    return bundle_path


def build_zip(dist_dir, meta):
    """Extension zip: blender_manifest.toml and modules at the zip root."""
    dist_dir.mkdir(parents=True, exist_ok=True)
    out = dist_dir / f"lyric_chunker-{meta['version']}.zip"
    files = sorted(
        p for p in PACKAGE_DIR.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(PACKAGE_DIR).as_posix())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="write the flattened single-file add-on here")
    ap.add_argument("--comp-out", type=Path,
                    help="write the self-contained comp generator here")
    ap.add_argument("--bundle", type=Path,
                    help="write a zip bundling the add-on + comp generator here")
    ap.add_argument("--zip", type=Path, help="also build the Extension zip into this directory")
    args = ap.parse_args()
    if not any((args.out, args.comp_out, args.bundle, args.zip)):
        ap.error("nothing to do — pass --out, --comp-out, --bundle, and/or --zip")

    flat, meta = build_flat_source()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(flat, encoding="utf-8")
        print(f"wrote {args.out} ({len(flat.splitlines())} lines, v{meta['version']})")
    if args.comp_out or args.bundle:
        comp = build_comp_source()
        if args.comp_out:
            args.comp_out.parent.mkdir(parents=True, exist_ok=True)
            args.comp_out.write_text(comp, encoding="utf-8")
            print(f"wrote {args.comp_out} ({len(comp.splitlines())} lines)")
        if args.bundle:
            out = build_bundle(args.bundle, flat, comp, meta)
            print(f"wrote {out}")
    if args.zip:
        out = build_zip(args.zip, meta)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
